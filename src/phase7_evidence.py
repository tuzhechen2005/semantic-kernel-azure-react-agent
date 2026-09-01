"""Task 2 adapter for shared Phase 7 evidence and security contracts."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import sys
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.react_runner import ReactRunResult, ReactTraceStep


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = PROJECT_ROOT.parent
SHARED_EVALUATION = SHARED_ROOT / "evaluation"
TRACE_SCHEMA = SHARED_EVALUATION / "contracts" / "trace_event.schema.json"
ERROR_TAXONOMY = SHARED_EVALUATION / "contracts" / "error_taxonomy.yaml"
SECURITY_CANARIES = SHARED_EVALUATION / "contracts" / "security_canaries.yaml"
SCHEMA_VERSION = "task2-react-evidence-v1"
CACHE_VERSION = "task2-semantic-cache-v2"
SECURITY_DOMAIN = "public-microsoft-learn"
PROMPT_VERSION = "task2-react-v1"
REDACTED = "[REDACTED]"

_OUTCOME_ERRORS = {
    "answer_error": "schema",
    "parse_error": "parse",
    "protocol_error": "state",
    "model_error": "model",
    "tool_error": "tool",
    "model_timeout": "timeout",
    "tool_timeout": "timeout",
}
_STATUS_ERRORS = {
    "evidence_insufficient": "retrieval",
    "max_steps": "state",
    "parse_error": "parse",
    "model_error": "model",
    "tool_error": "tool",
    "model_timeout": "timeout",
    "tool_timeout": "timeout",
    "correction_limit": "state",
}
_TERMINAL_STATES = {
    "completed": "completed",
    "evidence_insufficient": "degraded",
    "model_timeout": "timeout",
    "tool_timeout": "timeout",
    "max_steps": "degraded",
    "parse_error": "failed",
    "model_error": "failed",
    "tool_error": "failed",
    "correction_limit": "failed",
}


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"shared contract is missing: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_shared_manifest_extension() -> dict[str, str]:
    """Pin the exact shared contracts used by a Task 2 run."""
    return {
        "contract_version": "phase7-v1",
        "trace_schema_sha256": _sha256(TRACE_SCHEMA),
        "error_taxonomy_sha256": _sha256(ERROR_TAXONOMY),
        "security_canaries_sha256": _sha256(SECURITY_CANARIES),
        "schema_version": SCHEMA_VERSION,
        "cache_version": CACHE_VERSION,
        "security_domain": SECURITY_DOMAIN,
    }


def build_task2_cache_probe(
    *,
    probe_id: str,
    baseline_calls: int,
    optimized_calls: int,
    equivalent_response: bool,
    hard_negative_mis_hits: int,
    hit_latency_ms: float,
    miss_latency_ms: float,
    invalidation_verified: bool,
    security_domain_isolated: bool,
) -> dict[str, Any]:
    """Build a shared-schema probe from caller-supplied measured observations."""
    return {
        "probe_id": probe_id,
        "task": "task2",
        "cache_version": CACHE_VERSION,
        "baseline_calls": baseline_calls,
        "optimized_calls": optimized_calls,
        "equivalent_response": equivalent_response,
        "hard_negative_mis_hits": hard_negative_mis_hits,
        "hit_latency_ms": hit_latency_ms,
        "miss_latency_ms": miss_latency_ms,
        "invalidation_verified": invalidation_verified,
        "security_domain_isolated": security_domain_isolated,
    }


@lru_cache(maxsize=1)
def _shared_canary_values() -> tuple[str, ...]:
    if str(SHARED_ROOT) not in sys.path:
        sys.path.insert(0, str(SHARED_ROOT))
    from evaluation.contract_validator import load_canary_registry

    registry = load_canary_registry(SECURITY_CANARIES)
    return tuple(str(value) for value in registry["canaries"].values())


def redact_evidence(value: Any) -> Any:
    """Remove every exact shared canary without changing evidence structure."""
    if isinstance(value, str):
        result = value
        for canary in _shared_canary_values():
            result = result.replace(canary, REDACTED)
        return result
    if isinstance(value, dict):
        return {str(key): redact_evidence(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_evidence(item) for item in value]
    return value


def count_shared_canary_leaks(text: str) -> int:
    """Count exact registered canaries without returning their values."""
    return sum(text.count(canary) for canary in _shared_canary_values())


def _step_name(step: ReactTraceStep) -> str:
    if step.action == "search_documents":
        return "retrieval"
    if step.action == "read_document":
        return "citation"
    if step.outcome in {"model_error", "model_timeout"}:
        return "model"
    if step.outcome in {"tool_error", "tool_timeout"}:
        return "tool"
    return "validation"


def _error_category(
    result: ReactRunResult,
    step: ReactTraceStep,
    *,
    is_last: bool,
) -> str | None:
    category = _OUTCOME_ERRORS.get(step.outcome)
    if category is not None:
        return category
    if is_last:
        return _STATUS_ERRORS.get(result.status)
    return None


def _duration_ms(step: ReactTraceStep) -> float:
    return max(0.0, float(step.model_latency_ms or 0.0)) + max(
        0.0, float(step.tool_latency_ms or 0.0)
    )


def _retry_decision(error_category: str | None, *, is_last: bool) -> str:
    if error_category is None:
        return "none"
    if not is_last:
        return "retry"
    if error_category in {"model", "parse", "schema", "state", "timeout"}:
        return "exhausted"
    return "blocked"


def _retry_attempt(step: ReactTraceStep, error_category: str | None) -> int:
    if step.retry_count < 0:
        raise ValueError("retry_count cannot be negative")
    attempt = (
        max(0, step.retry_count - 1) if error_category is not None else step.retry_count
    )
    if attempt > 2:
        raise ValueError("shared retry attempt cannot exceed two")
    return attempt


def build_task2_trace_events(
    result: ReactRunResult,
    *,
    started_at: datetime,
    model: str,
    prompt_version: str,
    run_id: str,
    trace_id: str,
    input_hash: str,
    cache_status: str,
    cache_reason: str,
) -> list[dict[str, Any]]:
    """Convert Task 2 ReAct steps into strict shared trace events."""
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("started_at must be timezone-aware")
    if not result.trace:
        raise ValueError("Task 2 shared trace requires at least one ReAct step")

    events: list[dict[str, Any]] = []
    cursor = started_at
    peak_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    for index, step in enumerate(result.trace):
        is_last = index == len(result.trace) - 1
        duration_ms = _duration_ms(step)
        ended_at = cursor + timedelta(milliseconds=duration_ms)
        error_category = _error_category(result, step, is_last=is_last)
        retry_attempt = _retry_attempt(step, error_category)
        if is_last:
            termination_state = _TERMINAL_STATES[result.status]
            termination_reason = step.termination_reason or result.status
        else:
            termination_state = "running"
            termination_reason = step.validation_result or step.outcome
        event = {
            "trace_id": trace_id,
            "run_id": run_id,
            "task": "task2",
            "step": _step_name(step),
            "start_at": cursor.isoformat(),
            "end_at": ended_at.isoformat(),
            "duration_ms": duration_ms,
            "model": model,
            "prompt_version": prompt_version,
            "input_hash": input_hash,
            "validation": {
                "status": "failed" if error_category is not None else "passed",
                "schema_version": SCHEMA_VERSION,
                "error_category": error_category,
            },
            "retry": {
                "attempt": retry_attempt,
                "max_retries": 2,
                "decision": _retry_decision(error_category, is_last=is_last),
            },
            "cache": {
                "status": cache_status,
                "key_version": CACHE_VERSION,
                "reason": cache_reason,
            },
            "termination": {
                "state": termination_state,
                "reason": termination_reason,
            },
            "resource_usage": {
                "wall_ms": duration_ms,
                "peak_rss_bytes": peak_rss,
                "input_tokens": None,
                "output_tokens": None,
            },
        }
        events.append(redact_evidence(event))
        cursor = ended_at
    return validate_shared_trace_events(events)


def validate_shared_trace_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Redact and validate a complete event batch before any append begins."""
    if str(SHARED_ROOT) not in sys.path:
        sys.path.insert(0, str(SHARED_ROOT))
    from evaluation.contract_validator import validate_trace_event

    safe_events: list[dict[str, Any]] = []
    for event in events:
        safe_event = redact_evidence(event)
        if not isinstance(safe_event, dict):
            raise TypeError("shared trace event must remain an object")
        validate_trace_event(safe_event)
        safe_events.append(safe_event)
    return safe_events


def append_shared_trace_events(path: Path, events: list[dict[str, Any]]) -> None:
    """Validate, append, and fsync shared events without persisting payloads."""
    safe_events = validate_shared_trace_events(events)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for safe_event in safe_events:
            handle.write(
                json.dumps(
                    safe_event,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        handle.flush()
        os.fsync(handle.fileno())
