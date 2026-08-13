import argparse
import asyncio
import io
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from src import cli
from src.react_runner import ReactRunResult, ReactTraceStep


class CliTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_question_exception_is_contained(self) -> None:
        args = argparse.Namespace(
            model=Path("model.gguf"),
            question="Question",
            max_steps=5,
            max_parse_retries=2,
            trace_output=Path("trace.jsonl"),
            verbose_model=False,
            cpu=True,
        )
        runner = Mock()
        model = Mock()

        with (
            patch.object(cli, "parse_args", return_value=args),
            patch.object(cli, "build_runner", return_value=(runner, model)),
            patch.object(
                cli,
                "run_and_record",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            exit_code = await cli.main()

        self.assertEqual(exit_code, 1)
        self.assertIn("本轮执行失败", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    async def test_interactive_loop_continues_after_one_failed_round(self) -> None:
        args = argparse.Namespace(
            model=Path("model.gguf"),
            question=None,
            max_steps=5,
            max_parse_retries=2,
            trace_output=Path("trace.jsonl"),
            verbose_model=False,
            cpu=True,
        )
        completed = ReactRunResult(
            status="completed",
            question="second question",
            answer="answer",
            trace=(),
        )

        with (
            patch.object(cli, "parse_args", return_value=args),
            patch.object(cli, "build_runner", return_value=(Mock(), Mock())),
            patch.object(
                cli,
                "run_and_record",
                AsyncMock(
                    side_effect=[RuntimeError("first failed"), completed]
                ),
            ) as run_mock,
            patch(
                "builtins.input",
                side_effect=["first question", "second question", "exit"],
            ),
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            exit_code = await cli.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_mock.await_count, 2)
        self.assertIn("可以继续输入下一个问题", output.getvalue())
        self.assertIn("answer", output.getvalue())

    def test_print_result_exposes_recovery_events(self) -> None:
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
                    error="bad format",
                ),
                ReactTraceStep(
                    step_number=2,
                    prompt="prompt",
                    raw_model_output="read first",
                    outcome="protocol_error",
                    action="read_document",
                    arguments={"document_id": "x"},
                ),
            ),
        )

        with patch("sys.stdout", new_callable=io.StringIO) as output:
            cli.print_result(result, Path("trace.jsonl"))

        rendered = output.getvalue()
        self.assertIn("格式不符合协议", rendered)
        self.assertIn("动作违反 ReAct", rendered)


if __name__ == "__main__":
    unittest.main()
