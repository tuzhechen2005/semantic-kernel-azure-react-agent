from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.phase7_evidence import (
    append_shared_trace_events,
    build_shared_manifest_extension,
    build_task2_cache_probe,
    build_task2_trace_events,
    redact_evidence,
)
from src.react_runner import ReactRunResult, ReactTraceStep
from src.trace_writer import append_trace_record, build_trace_record


ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = ROOT.parent
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from evaluation.contract_validator import (  # noqa: E402
    load_canary_registry,
    validate_cache_probe,
    validate_trace_event,
)


class Phase7EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.started = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.common = {
            "started_at": self.started,
            "model": "fixture.gguf",
            "prompt_version": "react-v1",
            "run_id": "task2-phase7-test",
            "trace_id": "11111111-1111-4111-8111-111111111111",
            "input_hash": "a" * 64,
            "cache_status": "miss",
            "cache_reason": "key_miss",
        }

    def test_retrieval_citation_and_validation_spans_conform_and_append(self) -> None:
        result = ReactRunResult(
            status="completed",
            question="Which disk?",
            answer="Use Standard HDD with the observed citation.",
            trace=(
                ReactTraceStep(
                    step_number=1,
                    prompt="search",
                    raw_model_output="search",
                    outcome="action",
                    action="search_documents",
                    model_latency_ms=4,
                    tool_latency_ms=2,
                    validation_result="observation_validated",
                ),
                ReactTraceStep(
                    step_number=2,
                    prompt="read",
                    raw_model_output="read",
                    outcome="action",
                    action="read_document",
                    model_latency_ms=3,
                    tool_latency_ms=2,
                    validation_result="observation_validated",
                ),
                ReactTraceStep(
                    step_number=3,
                    prompt="answer",
                    raw_model_output="answer",
                    outcome="final",
                    model_latency_ms=3,
                    validation_result="valid_sources",
                    termination_reason="completed",
                ),
            ),
        )
        events = build_task2_trace_events(result, **self.common)
        self.assertEqual(
            [event["step"] for event in events],
            ["retrieval", "citation", "validation"],
        )
        self.assertEqual(events[-1]["termination"]["state"], "completed")
        for event in events:
            validate_trace_event(event)
            self.assertEqual(event["trace_id"], self.common["trace_id"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shared_trace.jsonl"
            append_shared_trace_events(path, events)
            stored = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(stored, events)

    def test_no_result_and_timeout_have_truthful_shared_terminal_categories(
        self,
    ) -> None:
        no_result = ReactRunResult(
            status="evidence_insufficient",
            question="Live price?",
            answer="INSUFFICIENT_EVIDENCE: no local source.",
            trace=(
                ReactTraceStep(
                    step_number=1,
                    prompt="answer",
                    raw_model_output="fallback",
                    outcome="final",
                    model_latency_ms=1,
                    validation_result="safe_fallback",
                    termination_reason="insufficient_evidence",
                ),
            ),
        )
        no_result_event = build_task2_trace_events(no_result, **self.common)[0]
        self.assertEqual(no_result_event["validation"]["error_category"], "retrieval")
        self.assertEqual(no_result_event["termination"]["state"], "degraded")
        validate_trace_event(no_result_event)

        timeout = ReactRunResult(
            status="model_timeout",
            question="Question",
            answer=None,
            trace=(
                ReactTraceStep(
                    step_number=1,
                    prompt="prompt",
                    raw_model_output="",
                    outcome="model_timeout",
                    model_latency_ms=5,
                    termination_reason="model_timeout",
                ),
            ),
        )
        timeout_event = build_task2_trace_events(timeout, **self.common)[0]
        self.assertEqual(timeout_event["step"], "model")
        self.assertEqual(timeout_event["validation"]["error_category"], "timeout")
        self.assertEqual(timeout_event["termination"]["state"], "timeout")
        validate_trace_event(timeout_event)

    def test_recovered_validation_failure_records_retry_decision(self) -> None:
        result = ReactRunResult(
            status="completed",
            question="Question",
            answer="Answer",
            trace=(
                ReactTraceStep(
                    step_number=1,
                    prompt="prompt",
                    raw_model_output="bad",
                    outcome="parse_error",
                    model_latency_ms=1,
                    retry_count=1,
                ),
                ReactTraceStep(
                    step_number=2,
                    prompt="prompt",
                    raw_model_output="answer",
                    outcome="final",
                    model_latency_ms=1,
                    validation_result="valid_sources",
                    retry_count=1,
                    termination_reason="completed",
                ),
            ),
        )
        events = build_task2_trace_events(result, **self.common)
        self.assertEqual(events[0]["validation"]["error_category"], "parse")
        self.assertEqual(events[0]["retry"]["attempt"], 0)
        self.assertEqual(events[0]["retry"]["decision"], "retry")
        self.assertEqual(events[1]["retry"]["attempt"], 1)
        self.assertEqual(events[1]["retry"]["decision"], "none")

    def test_initial_attempt_plus_two_failed_retries_maps_to_attempt_two(self) -> None:
        steps = tuple(
            ReactTraceStep(
                step_number=index,
                prompt="prompt",
                raw_model_output="bad",
                outcome="protocol_error",
                model_latency_ms=1,
                retry_count=index,
                termination_reason="correction_limit" if index == 3 else None,
            )
            for index in (1, 2, 3)
        )
        result = ReactRunResult(
            status="correction_limit",
            question="Question",
            answer=None,
            trace=steps,
        )
        events = build_task2_trace_events(result, **self.common)
        self.assertEqual(
            [event["retry"]["attempt"] for event in events],
            [0, 1, 2],
        )
        self.assertEqual(events[-1]["retry"]["decision"], "exhausted")

    def test_manifest_hashes_and_all_registered_canaries_are_enforced(self) -> None:
        extension = build_shared_manifest_extension()
        self.assertEqual(extension["contract_version"], "phase7-v1")
        for field in (
            "trace_schema_sha256",
            "error_taxonomy_sha256",
            "security_canaries_sha256",
        ):
            self.assertRegex(extension[field], r"^[0-9a-f]{64}$")

        registry = load_canary_registry(
            SHARED_ROOT / "evaluation" / "contracts" / "security_canaries.yaml"
        )
        canaries = list(registry["canaries"].values())
        rendered = json.dumps(redact_evidence({"text": " | ".join(canaries)}))
        for canary in canaries:
            self.assertNotIn(canary, rendered)

    def test_primary_trace_record_embeds_linked_shared_contract_events(self) -> None:
        result = ReactRunResult(
            status="completed",
            question="Which disk?",
            answer="Observed answer.",
            trace=(
                ReactTraceStep(
                    step_number=1,
                    prompt="answer",
                    raw_model_output="answer",
                    outcome="final",
                    model_latency_ms=2,
                    validation_result="valid_sources",
                    termination_reason="completed",
                ),
            ),
        )
        record = build_trace_record(
            result,
            started_at_utc=self.started,
            finished_at_utc=self.started,
            model_metadata={"file": "fixture.gguf", "backend": "test"},
            cache_status="hit",
            cache_reason="exact_scope_signature_and_citations",
        )
        self.assertEqual(record["sharedContract"]["contract_version"], "phase7-v1")
        self.assertRegex(record["traceId"], r"^[0-9a-f-]{36}$")
        self.assertRegex(record["inputHash"], r"^[0-9a-f]{64}$")
        self.assertEqual(record["sharedTrace"][0]["trace_id"], record["traceId"])
        self.assertEqual(record["sharedTrace"][0]["run_id"], record["runId"])
        self.assertEqual(record["sharedTrace"][0]["cache"]["status"], "hit")
        validate_trace_event(record["sharedTrace"][0])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "react.jsonl"
            append_trace_record(path, record)
            sidecar = path.with_name("react.shared.jsonl")
            shared = [json.loads(line) for line in sidecar.read_text().splitlines()]
        self.assertEqual(shared, record["sharedTrace"])

    def test_cache_probe_uses_shared_machine_contract_without_claiming_measurement(
        self,
    ) -> None:
        probe = build_task2_cache_probe(
            probe_id="task2-contract-fixture",
            baseline_calls=4,
            optimized_calls=2,
            equivalent_response=True,
            hard_negative_mis_hits=0,
            hit_latency_ms=0.25,
            miss_latency_ms=1.5,
            invalidation_verified=True,
            security_domain_isolated=True,
        )
        validate_cache_probe(probe)
        self.assertEqual(probe["cache_version"], "task2-semantic-cache-v2")


if __name__ == "__main__":
    unittest.main()
