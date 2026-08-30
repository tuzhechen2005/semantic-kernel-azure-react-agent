import tempfile
import unittest
from pathlib import Path

from src.corpus_contract import build_corpus_manifest
from src.qa_dataset import build_frozen_cases, validate_cases, write_jsonl_exclusive
from src.freeze_qa_dataset import freeze_qa_dataset


class QaDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parent.parent
        self.manifest = build_corpus_manifest(root / "docs" / "corpus")

    def test_builds_balanced_traceable_frozen_dataset(self) -> None:
        cases = build_frozen_cases(self.manifest)
        report = validate_cases(cases, self.manifest, require_frozen_gates=True)

        self.assertGreaterEqual(report["caseCount"], 60)
        self.assertGreaterEqual(report["languageCounts"]["en"], 20)
        self.assertGreaterEqual(report["languageCounts"]["zh"], 20)
        for category in (
            "single_document", "multi_document", "similar_concept",
            "unanswerable", "ambiguous", "prompt_injection",
        ):
            self.assertGreaterEqual(report["categoryCounts"][category], 5)
        self.assertGreaterEqual(report["answerabilityCounts"]["unanswerable"], 15)
        self.assertEqual(report["invalidSourceCount"], 0)

    def test_gold_contract_distinguishes_answerable_and_unanswerable(self) -> None:
        cases = build_frozen_cases(self.manifest)
        for case in cases:
            if case["answerability"] == "answerable":
                self.assertTrue(case["goldFactPoints"])
                self.assertTrue(case["goldSources"])
                self.assertTrue(case["requiredDocumentIds"])
            else:
                self.assertEqual(case["goldFactPoints"], [])
                self.assertEqual(case["goldSources"], [])
                self.assertTrue(case["safeFallback"])

    def test_writer_refuses_to_replace_frozen_bytes(self) -> None:
        cases = build_frozen_cases(self.manifest)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "frozen.jsonl"
            write_jsonl_exclusive(target, cases)
            with self.assertRaises(FileExistsError):
                write_jsonl_exclusive(target, cases)

    def test_freeze_writes_hash_manifest_and_refuses_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "frozen.jsonl"
            freeze_manifest = root / "frozen.sha256.json"
            corpus_manifest = root / "corpus.json"
            result = freeze_qa_dataset(
                corpus_dir=Path(__file__).resolve().parent.parent / "docs" / "corpus",
                corpus_manifest_path=corpus_manifest,
                dataset_path=dataset,
                dataset_manifest_path=freeze_manifest,
                frozen_at="2026-08-30T12:00:00+08:00",
            )
            self.assertEqual(result["sampleCount"], 72)
            self.assertEqual(result["lineCount"], 72)
            self.assertRegex(result["sha256"], r"^[0-9a-f]{64}$")
            with self.assertRaises(FileExistsError):
                freeze_qa_dataset(
                    corpus_dir=Path(__file__).resolve().parent.parent / "docs" / "corpus",
                    corpus_manifest_path=corpus_manifest,
                    dataset_path=dataset,
                    dataset_manifest_path=freeze_manifest,
                    frozen_at="2026-08-30T12:00:01+08:00",
                )

    def test_freeze_rejects_invalid_timestamp_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = (root / "corpus.json", root / "frozen.jsonl", root / "manifest.json")
            with self.assertRaises(ValueError):
                freeze_qa_dataset(
                    corpus_dir=Path(__file__).resolve().parent.parent / "docs" / "corpus",
                    corpus_manifest_path=targets[0],
                    dataset_path=targets[1],
                    dataset_manifest_path=targets[2],
                    frozen_at="2026-08-30T11:29:12:z",
                )
            self.assertFalse(any(path.exists() for path in targets))


if __name__ == "__main__":
    unittest.main()
