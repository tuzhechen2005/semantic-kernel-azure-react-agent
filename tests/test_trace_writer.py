import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.react_runner import ReactRunResult, ReactTraceStep
from src.trace_writer import append_trace_record, build_trace_record


class TraceWriterTests(unittest.TestCase):
    def test_build_and_append_trace_record(self) -> None:
        started = datetime(2026, 8, 13, tzinfo=timezone.utc)
        finished = started + timedelta(seconds=1.25)
        result = ReactRunResult(
            status="completed",
            question="Which disk?",
            answer="Standard HDD",
            trace=(
                ReactTraceStep(
                    step_number=1,
                    prompt="prompt",
                    raw_model_output="output",
                    outcome="final",
                    thought="enough evidence",
                ),
            ),
        )
        record = build_trace_record(
            result,
            started_at_utc=started,
            finished_at_utc=finished,
            model_metadata={"backend": "test"},
        )

        self.assertEqual(record["latencySeconds"], 1.25)
        self.assertEqual(record["trace"][0]["raw_model_output"], "output")

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "nested" / "trace.jsonl"
            append_trace_record(output_path, record)
            loaded = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["question"], "Which disk?")
        self.assertEqual(loaded["status"], "completed")

    def test_naive_datetime_is_rejected(self) -> None:
        result = ReactRunResult(
            status="max_steps",
            question="Question",
            answer=None,
            trace=(),
        )

        with self.assertRaisesRegex(ValueError, "时区"):
            build_trace_record(
                result,
                started_at_utc=datetime(2026, 8, 13),
                finished_at_utc=datetime(2026, 8, 13),
                model_metadata={},
            )

    def test_finished_before_started_is_rejected(self) -> None:
        started = datetime(2026, 8, 13, tzinfo=timezone.utc)
        result = ReactRunResult(
            status="completed",
            question="Question",
            answer="Answer",
            trace=(
                ReactTraceStep(
                    step_number=1,
                    prompt="prompt",
                    raw_model_output="answer",
                    outcome="final",
                    termination_reason="completed",
                ),
            ),
        )
        with self.assertRaisesRegex(ValueError, "finished_at"):
            build_trace_record(
                result,
                started_at_utc=started,
                finished_at_utc=started - timedelta(milliseconds=1),
                model_metadata={"backend": "test"},
            )


if __name__ == "__main__":
    unittest.main()
