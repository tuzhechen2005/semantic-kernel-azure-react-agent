import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function

from src.frozen_runner import (
    FrozenRunError,
    build_prediction_row,
    run_frozen_dataset,
    verify_sha256,
)
from src.react_runner import ReactRunner, ScriptedModel, build_test_prompt


class FakeDocumentPlugin:
    @kernel_function(name="search_documents")
    def search_documents(self, query: str, top_k: int = 3) -> str:
        return json.dumps(
            {
                "status": "success",
                "query": query,
                "results": [
                    {
                        "documentId": "managed_disk_types",
                        "source": "https://learn.microsoft.com/disk-types",
                    }
                ],
            }
        )

    @kernel_function(name="read_document")
    def read_document(self, document_id: str) -> str:
        return json.dumps(
            {
                "status": "success",
                "documentId": document_id,
                "content": "Standard HDD is suitable for backups.",
                "source": "https://learn.microsoft.com/disk-types",
            }
        )


SCRIPT = [
    "Thought: I need to search the documentation.\n"
    "Action: search_documents\n"
    'Action Input: {"query":"Azure disk backup","top_k":1}',
    "Thought: The search result contains enough evidence.\n"
    "Final Answer: Standard HDD is suitable for backups.\n"
    "Source: https://learn.microsoft.com/disk-types",
]


def _runner(outputs: list[str]) -> tuple[ReactRunner, ScriptedModel]:
    kernel = Kernel()
    kernel.add_plugin(FakeDocumentPlugin(), plugin_name="azure_docs")
    model = ScriptedModel(outputs)
    return ReactRunner(
        kernel=kernel, model=model, prompt_builder=build_test_prompt, max_steps=6
    ), model


def _cases(count: int) -> list[dict[str, object]]:
    return [
        {
            "caseId": f"case_{index}",
            "question": f"question {index}",
            "answerability": "answerable",
            "goldFactPoints": ["Standard HDD"],
            "goldSources": ["https://learn.microsoft.com/disk-types"],
            "requiredDocumentIds": ["managed_disk_types"],
            "language": "en",
            "category": "single_document",
            "difficulty": "easy",
            "split": "frozen_test",
        }
        for index in range(1, count + 1)
    ]


class FrozenRunnerTests(unittest.TestCase):
    def test_prediction_row_preserves_raw_bytes_and_marks_executed_steps(self) -> None:
        runner, _ = _runner(list(SCRIPT))
        result = asyncio.run(runner.run("which disk for backups"))
        row = build_prediction_row(
            result, run_id="frozen-1", case_id="case_1", latency_ms=12.5
        )
        self.assertEqual(row["runId"], "frozen-1")
        self.assertEqual(row["caseId"], "case_1")
        self.assertEqual(row["status"], "completed")
        self.assertEqual(
            row["rawOutput"], "\n".join(step.raw_model_output for step in result.trace)
        )
        self.assertFalse(row["cacheHit"])
        self.assertEqual(row["latencyMs"], 12.5)
        self.assertEqual([step["executed"] for step in row["trace"]], [True, False])
        self.assertEqual(row["trace"][0]["action"], "search_documents")
        self.assertIn("results", row["trace"][0]["observation"])
        self.assertEqual(
            row["rawStepSha256"][0],
            hashlib.sha256(result.trace[0].raw_model_output.encode()).hexdigest(),
        )

    def test_run_writes_raw_trace_manifest_and_refuses_existing_directory(self) -> None:
        cases = _cases(2)
        runner, _ = _runner(list(SCRIPT) * 2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "cases.jsonl"
            case_path.write_text(
                "".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8"
            )
            run_dir = run_frozen_dataset(
                cases,
                runner,
                run_id="frozen-1",
                output_root=root / "runs",
                manifest_extra={
                    "dataset": {
                        "sha256": verify_sha256(
                            case_path,
                            hashlib.sha256(case_path.read_bytes()).hexdigest(),
                        )
                    }
                },
                model_metadata={"file": "scripted", "backend": "test"},
            )
            raw_rows = [
                json.loads(line)
                for line in (run_dir / "raw_predictions.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["caseId"] for row in raw_rows], ["case_1", "case_2"])
            self.assertTrue((run_dir / "trace.jsonl").is_file())
            self.assertTrue((run_dir / "trace.shared.jsonl").is_file())
            manifest = json.loads((run_dir / "run_manifest.json").read_text())
            self.assertEqual(manifest["runId"], "frozen-1")
            self.assertEqual(manifest["runType"], "frozen_final")
            self.assertEqual(manifest["caseCount"], 2)
            self.assertIsNotNone(manifest["finishedAtUtc"])
            trace_rows = [
                json.loads(line)
                for line in (run_dir / "trace.jsonl").read_text().splitlines()
            ]
            self.assertEqual(
                [row["caseId"] for row in trace_rows], ["case_1", "case_2"]
            )
            with self.assertRaises(FileExistsError):
                run_frozen_dataset(
                    cases,
                    runner,
                    run_id="frozen-1",
                    output_root=root / "runs",
                    manifest_extra={},
                    model_metadata={},
                )

    def test_sha256_mismatch_and_duplicate_case_ids_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.jsonl"
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(FrozenRunError):
                verify_sha256(path, "0" * 64)
            runner, _ = _runner(list(SCRIPT))
            cases = _cases(1) * 2
            with self.assertRaises(FrozenRunError):
                run_frozen_dataset(
                    cases,
                    runner,
                    run_id="dup",
                    output_root=Path(directory) / "runs",
                    manifest_extra={},
                    model_metadata={},
                )


if __name__ == "__main__":
    unittest.main()
