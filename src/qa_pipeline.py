import hashlib
import json
import os
from pathlib import Path

from src.qa_evaluator import score_case, summarize_scores


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}: {path}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row must be an object: {path}:{line_number}")
        rows.append(row)
    return rows


def append_raw_prediction(path: Path, row: dict[str, object]) -> None:
    run_id = row.get("runId")
    case_id = row.get("caseId")
    raw_output = row.get("rawOutput")
    if not isinstance(run_id, str) or not isinstance(case_id, str) or not isinstance(raw_output, str):
        raise ValueError("raw prediction requires string runId, caseId, and rawOutput")
    if path.exists():
        existing = _read_jsonl(path)
        if any(item.get("caseId") == case_id for item in existing):
            raise ValueError(f"duplicate raw prediction case: {case_id}")
        if any(item.get("runId") != run_id for item in existing):
            raise ValueError("raw prediction runId mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def score_prediction_files(case_path: Path, raw_path: Path, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=False)
    cases = _read_jsonl(case_path)
    predictions = _read_jsonl(raw_path)
    case_by_id = {str(case.get("caseId")): case for case in cases}
    prediction_by_id = {str(row.get("caseId")): row for row in predictions}
    if len(case_by_id) != len(cases) or len(prediction_by_id) != len(predictions):
        raise ValueError("duplicate case identity")
    if case_by_id.keys() != prediction_by_id.keys():
        raise ValueError("case and prediction identities differ")

    evaluated: list[dict[str, object]] = []
    for case in cases:
        prediction = prediction_by_id[str(case["caseId"])]
        raw_output = prediction.get("rawOutput")
        if not isinstance(raw_output, str):
            raise ValueError("prediction rawOutput must be a string")
        evaluated.append(
            {
                **score_case(case, prediction),
                "runId": prediction.get("runId"),
                "rawOutputSha256": hashlib.sha256(raw_output.encode()).hexdigest(),
            }
        )
    metrics = summarize_scores(evaluated)
    with (output_dir / "evaluated_cases.jsonl").open("x", encoding="utf-8") as handle:
        for row in evaluated:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with (output_dir / "metrics.json").open("x", encoding="utf-8") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    failures = [row for row in evaluated if row["errors"]]
    with (output_dir / "failures.jsonl").open("x", encoding="utf-8") as handle:
        for row in failures:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with (output_dir / "report.md").open("x", encoding="utf-8") as handle:
        handle.write("# Task 2 evaluation\n\n")
        handle.write(f"- Cases: {metrics['caseCount']}\n")
        handle.write(f"- Answer accuracy: {metrics['answerAccuracy']}\n")
        handle.write(f"- Valid citation rate: {metrics['validCitationRate']}\n")
        handle.write(f"- P95 latency ms: {metrics['latencyMs']['p95']}\n")  # type: ignore[index]
    return metrics
