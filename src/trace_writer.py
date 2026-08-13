import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.react_runner import ReactRunResult


def build_trace_record(
    result: ReactRunResult,
    *,
    started_at_utc: datetime,
    finished_at_utc: datetime,
    model_metadata: dict[str, Any],
) -> dict[str, Any]:
    if started_at_utc.tzinfo is None or finished_at_utc.tzinfo is None:
        raise ValueError("trace 时间必须包含时区")

    latency_seconds = (
        finished_at_utc - started_at_utc
    ).total_seconds()

    return {
        "runId": str(uuid4()),
        "startedAtUtc": started_at_utc.astimezone(timezone.utc).isoformat(),
        "finishedAtUtc": finished_at_utc.astimezone(timezone.utc).isoformat(),
        "latencySeconds": round(latency_seconds, 6),
        "question": result.question,
        "status": result.status,
        "answer": result.answer,
        "error": result.error,
        "model": model_metadata,
        "trace": [asdict(step) for step in result.trace],
    }


def append_trace_record(
    output_path: Path,
    record: dict[str, Any],
) -> None:
    resolved_path = output_path.expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    with resolved_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False))
        file.write("\n")
