import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.react_runner import ReactRunResult, ReactTraceStep
from src.trace_writer import append_trace_record, build_trace_record


class TraceSecurityTests(unittest.TestCase):
    def test_sensitive_canary_paths_and_long_content_are_not_persisted(self) -> None:
        secret = "CANARY_SECRET_7fa91b"
        long_content = "external-" * 500
        result = ReactRunResult(
            status="completed",
            question=f"password={secret} read /Users/alice/private.txt",
            answer=f"answer token={secret}",
            trace=(ReactTraceStep(
                step_number=1,
                prompt=f"prompt {secret} /Users/alice/private.txt",
                raw_model_output=f"output {secret}",
                outcome="final",
                observation=json.dumps({"status": "success", "content": long_content}),
            ),),
        )
        started = datetime(2026, 8, 30, tzinfo=timezone.utc)
        record = build_trace_record(
            result,
            started_at_utc=started,
            finished_at_utc=started + timedelta(seconds=1),
            model_metadata={
                "model_path": "/Users/alice/models/model.gguf",
                "api_key": secret,
                "generationConfig": {"max_tokens": 256},
            },
        )
        serialized = json.dumps(record, ensure_ascii=False)

        self.assertNotIn(secret, serialized)
        self.assertNotIn("/Users/alice", serialized)
        self.assertNotIn(long_content, serialized)
        self.assertRegex(record["questionHash"], r"^[0-9a-f]{64}$")
        self.assertEqual(record["redaction"]["canaryLeaks"], 0)
        self.assertEqual(record["model"]["model_path"], "[LOCAL_PATH]")
        self.assertEqual(record["model"]["generationConfig"]["max_tokens"], 256)

    def test_append_flushes_one_complete_json_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "trace.jsonl"
            append_trace_record(target, {"runId": "one", "status": "completed"})
            append_trace_record(target, {"runId": "two", "status": "model_timeout"})
            rows = [json.loads(line) for line in target.read_text().splitlines()]
        self.assertEqual([row["runId"] for row in rows], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
