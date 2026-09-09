"""Append-only frozen-final batch runner for the Task 2 ReAct agent.

The runner never repairs, extracts or overwrites model output. Every case is
appended to ``raw_predictions.jsonl`` as soon as it finishes, the full trace
is written through the existing redacting trace writer, and the run directory
is created exclusively so a run ID can never be reused.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from semantic_kernel import Kernel

from src.azure_document_plugin import AzureDocumentPlugin
from src.document_store import DocumentStore
from src.local_phi3_model import LocalPhi3Model, Phi3GenerationConfig
from src.phase7_evidence import PROMPT_VERSION, SCHEMA_VERSION
from src.qa_pipeline import append_raw_prediction
from src.react_prompt import build_react_prompt
from src.react_runner import ReactRunner, ReactRunResult
from src.trace_writer import append_trace_record, build_trace_record

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_STEP_SEPARATOR = "\n"


class FrozenRunError(RuntimeError):
    """Raised when frozen-final preconditions or evidence integrity fail."""


def verify_sha256(path: Path, expected: str) -> str:
    """Return the file digest, failing closed on any mismatch."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise FrozenRunError(f"SHA-256 mismatch for {path.name}")
    return actual


def build_prediction_row(
    result: ReactRunResult,
    *,
    run_id: str,
    case_id: str,
    latency_ms: float,
) -> dict[str, Any]:
    """Convert one ReAct result into the scoring row consumed by qa_evaluator."""
    steps: list[dict[str, Any]] = []
    raw_step_hashes: list[str] = []
    for step in result.trace:
        raw_step_hashes.append(
            hashlib.sha256(step.raw_model_output.encode("utf-8")).hexdigest()
        )
        steps.append(
            {
                "stepNumber": step.step_number,
                "outcome": step.outcome,
                "action": step.action,
                "arguments": step.arguments,
                "observation": step.observation,
                "executed": step.outcome == "action",
                "error": step.error,
                "modelLatencyMs": step.model_latency_ms,
                "toolLatencyMs": step.tool_latency_ms,
                "retryCount": step.retry_count,
                "validationResult": step.validation_result,
                "readDocumentId": step.read_document_id,
                "terminationReason": step.termination_reason,
            }
        )
    return {
        "runId": run_id,
        "caseId": case_id,
        "status": result.status,
        "answer": result.answer,
        "error": result.error,
        "latencyMs": float(latency_ms),
        "cacheHit": False,
        "rawOutput": RAW_STEP_SEPARATOR.join(
            step.raw_model_output for step in result.trace
        ),
        "rawStepSha256": raw_step_hashes,
        "stepCount": len(result.trace),
        "trace": steps,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def run_frozen_dataset(
    cases: list[dict[str, Any]],
    runner: ReactRunner,
    *,
    run_id: str,
    output_root: Path,
    manifest_extra: dict[str, Any],
    model_metadata: dict[str, Any],
) -> Path:
    """Run every case once, appending raw output and traces as each completes."""
    if not run_id or Path(run_id).name != run_id:
        raise FrozenRunError("run_id must be one safe path component")
    case_ids = [str(case.get("caseId")) for case in cases]
    if len(set(case_ids)) != len(case_ids) or any(not item for item in case_ids):
        raise FrozenRunError("frozen cases must have unique non-empty caseId values")
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = output_root / run_id
    run_dir.mkdir(exist_ok=False)
    raw_path = run_dir / "raw_predictions.jsonl"
    trace_path = run_dir / "trace.jsonl"
    started_at = datetime.now(timezone.utc)
    manifest: dict[str, Any] = {
        "runId": run_id,
        "runType": "frozen_final",
        "task": "task2",
        "caseCount": len(cases),
        "startedAtUtc": started_at.isoformat(),
        "finishedAtUtc": None,
        "codeCommit": _git_commit(),
        "promptVersion": PROMPT_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "model": model_metadata,
        "runner": {
            "maxSteps": runner.max_steps,
            "maxParseRetries": runner.max_parse_retries,
            "maxCorrections": runner.max_corrections,
            "modelTimeoutSeconds": runner.model_timeout_seconds,
            "toolTimeoutSeconds": runner.tool_timeout_seconds,
        },
        "cache": {"status": "bypass", "reason": "frozen_final_single_variable"},
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        **manifest_extra,
    }
    _write_json(run_dir / "run_manifest.json", manifest)

    for index, case in enumerate(cases, start=1):
        case_id = str(case["caseId"])
        question = str(case["question"])
        case_started = datetime.now(timezone.utc)
        clock = time.perf_counter()
        result = asyncio.run(runner.run(question))
        latency_ms = (time.perf_counter() - clock) * 1000
        case_finished = datetime.now(timezone.utc)
        record = build_trace_record(
            result,
            started_at_utc=case_started,
            finished_at_utc=case_finished,
            model_metadata=model_metadata,
            cache_status="bypass",
            cache_reason="frozen_final_single_variable",
        )
        record["frozenRunId"] = run_id
        record["caseId"] = case_id
        append_trace_record(trace_path, record)
        row = build_prediction_row(
            result, run_id=run_id, case_id=case_id, latency_ms=round(latency_ms, 3)
        )
        append_raw_prediction(raw_path, row)
        print(
            f"[{index}/{len(cases)}] {case_id} {result.status} {latency_ms / 1000:.1f}s",
            flush=True,
        )

    manifest["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest["rawPredictionsSha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    _write_json(run_dir / "run_manifest.json", manifest)
    return run_dir


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise FrozenRunError("frozen case rows must be objects")
        rows.append(value)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--expected-dataset-sha256", required=True)
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        default=PROJECT_ROOT / "data" / "corpus_manifest_v2.json",
    )
    parser.add_argument("--expected-corpus-sha256", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--expected-model-sha256", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--max-parse-retries", type=int, default=2)
    parser.add_argument("--max-corrections", type=int, default=2)
    parser.add_argument("--model-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--tool-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_sha256 = verify_sha256(args.cases, args.expected_dataset_sha256)
    corpus_sha256 = verify_sha256(args.corpus_manifest, args.expected_corpus_sha256)
    model_sha256 = verify_sha256(args.model, args.expected_model_sha256)
    cases = _read_jsonl(args.cases)
    if args.limit is not None:
        cases = cases[: args.limit]

    store = DocumentStore(PROJECT_ROOT / "docs" / "corpus")
    store.load()
    kernel = Kernel()
    kernel.add_plugin(AzureDocumentPlugin(store), plugin_name="azure_docs")
    config = Phi3GenerationConfig(
        n_gpu_layers=0 if args.cpu else -1,
        max_tokens=args.max_tokens,
    )
    model = LocalPhi3Model(args.model, config, verbose=False)
    runner = ReactRunner(
        kernel=kernel,
        model=model,
        prompt_builder=build_react_prompt,
        max_steps=args.max_steps,
        max_parse_retries=args.max_parse_retries,
        max_corrections=args.max_corrections,
        model_timeout_seconds=args.model_timeout_seconds,
        tool_timeout_seconds=args.tool_timeout_seconds,
    )
    model_metadata = {
        "file": model.model_path.name,
        "sha256": model_sha256,
        "backend": "llama-cpp-python",
        "acceleration": "CPU" if config.n_gpu_layers == 0 else "Apple Metal",
        "generationConfig": {
            **{key: value for key, value in asdict(config).items() if key != "stop"},
            "stop": list(config.stop),
        },
    }
    run_dir = run_frozen_dataset(
        cases,
        runner,
        run_id=args.run_id,
        output_root=args.output_root,
        manifest_extra={
            "dataset": {
                "path": args.cases.name,
                "sha256": dataset_sha256,
                "lineCount": len(cases),
            },
            "corpus": {"manifest": args.corpus_manifest.name, "sha256": corpus_sha256},
        },
        model_metadata=model_metadata,
    )
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
