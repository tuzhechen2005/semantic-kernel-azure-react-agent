import hashlib
import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.react_runner import ReactRunResult


MAX_TRACE_TEXT_LENGTH = 1024
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)^(password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token|token|secret)$"
)
PATH_KEY_PATTERN = re.compile(r"(?i)(^path$|_path$|Path$)")
INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token|token)\s*[:=]\s*[^\s,;]+"
)
CANARY_PATTERN = re.compile(r"CANARY_SECRET_[A-Za-z0-9_-]+")
LOCAL_PATH_PATTERN = re.compile(
    r"(?<!https:)(?<!http:)(?<![A-Za-z0-9])/(?:Users|home|private|tmp|var|Volumes)/[^\n\r\"']+"
)


def _sanitize_text(value: str) -> str:
    sanitized = INLINE_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    sanitized = CANARY_PATTERN.sub("[REDACTED_CANARY]", sanitized)
    sanitized = LOCAL_PATH_PATTERN.sub("[LOCAL_PATH]", sanitized)
    if len(sanitized) > MAX_TRACE_TEXT_LENGTH:
        digest = hashlib.sha256(sanitized.encode()).hexdigest()
        sanitized = sanitized[:MAX_TRACE_TEXT_LENGTH] + f"...[TRUNCATED sha256={digest}]"
    return sanitized


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    if key is not None and SENSITIVE_KEY_PATTERN.search(key):
        return "[REDACTED]"
    if key is not None and PATH_KEY_PATTERN.search(key) and isinstance(value, str):
        return "[LOCAL_PATH]"
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, dict):
        return {str(item_key): _sanitize(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


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

    raw_record = {
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
    record = _sanitize(raw_record)
    record["questionHash"] = hashlib.sha256(result.question.encode()).hexdigest()
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
    record["redaction"] = {
        "policy": "task2-trace-redaction-v1",
        "maxTextLength": MAX_TRACE_TEXT_LENGTH,
        "canaryLeaks": len(CANARY_PATTERN.findall(serialized)),
    }
    return record


def append_trace_record(
    output_path: Path,
    record: dict[str, Any],
) -> None:
    resolved_path = output_path.expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    with resolved_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False))
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
