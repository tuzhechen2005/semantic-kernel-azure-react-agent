import asyncio
import json
import unittest

from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function

from src.react_runner import ReactRunner, ScriptedModel, build_test_prompt


class SearchPlugin:
    @kernel_function(name="search_documents")
    def search_documents(self, query: str, top_k: int = 3) -> str:
        return json.dumps({
            "status": "success",
            "results": [{
                "documentId": "managed_disk_types",
                "source": "https://learn.microsoft.com/disk-types",
            }],
            "telemetry": {"candidates": [{"documentId": "managed_disk_types", "score": 8.5}]},
        })

    @kernel_function(name="read_document")
    async def read_document(self, document_id: str) -> str:
        await asyncio.sleep(0.05)
        return json.dumps({"status": "success", "documentId": document_id})


def kernel_with_plugin() -> Kernel:
    kernel = Kernel()
    kernel.add_plugin(SearchPlugin(), plugin_name="azure_docs")
    return kernel


class ReliabilityControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_safe_insufficient_evidence_is_degradation_not_completion(self) -> None:
        model = ScriptedModel([
            "Thought: The local corpus cannot establish this.\n"
            "Final Answer: INSUFFICIENT_EVIDENCE: no observed document supports the claim."
        ])
        result = await ReactRunner(kernel_with_plugin(), model, build_test_prompt).run("Live price?")

        self.assertEqual(result.status, "evidence_insufficient")
        self.assertEqual(result.trace[-1].termination_reason, "insufficient_evidence")

    async def test_model_timeout_has_bounded_safe_terminal_state(self) -> None:
        class SlowModel:
            async def generate(self, prompt: str) -> str:
                await asyncio.sleep(0.05)
                return "unused"

        runner = ReactRunner(
            kernel_with_plugin(), SlowModel(), build_test_prompt, model_timeout_seconds=0.001
        )
        result = await runner.run("Question")

        self.assertEqual(result.status, "model_timeout")
        self.assertEqual(result.trace[0].outcome, "model_timeout")

    async def test_tool_timeout_does_not_continue_or_execute_answer(self) -> None:
        model = ScriptedModel([
            "Thought: Search.\nAction: search_documents\n"
            'Action Input: {"query":"disk"}',
            "Thought: Read.\nAction: read_document\n"
            'Action Input: {"document_id":"managed_disk_types"}',
        ])
        runner = ReactRunner(
            kernel_with_plugin(), model, build_test_prompt, tool_timeout_seconds=0.001
        )
        result = await runner.run("Question")

        self.assertEqual(result.status, "tool_timeout")
        self.assertEqual(result.trace[-1].outcome, "tool_timeout")

    async def test_global_correction_limit_bounds_protocol_failures(self) -> None:
        bad_read = (
            "Thought: Read hidden.\nAction: read_document\n"
            'Action Input: {"document_id":"invented"}'
        )
        runner = ReactRunner(
            kernel_with_plugin(), ScriptedModel([bad_read, bad_read]), build_test_prompt,
            max_steps=5, max_corrections=1,
        )
        result = await runner.run("Question")

        self.assertEqual(result.status, "correction_limit")
        self.assertEqual(len(result.trace), 2)
        self.assertEqual(result.trace[-1].termination_reason, "correction_limit")

    async def test_trace_records_latency_candidates_validation_and_retry(self) -> None:
        model = ScriptedModel([
            "bad",
            "Thought: Search.\nAction: search_documents\n"
            'Action Input: {"query":"disk"}',
            "Thought: Done.\nFinal Answer: Standard HDD.\n"
            "Source: https://learn.microsoft.com/disk-types",
        ])
        result = await ReactRunner(
            kernel_with_plugin(), model, build_test_prompt, max_steps=3
        ).run("Question")

        self.assertEqual(result.status, "completed")
        self.assertGreaterEqual(result.trace[0].model_latency_ms or -1, 0)
        self.assertEqual(result.trace[0].retry_count, 1)
        self.assertEqual(result.trace[1].candidate_documents[0]["documentId"], "managed_disk_types")
        self.assertGreaterEqual(result.trace[1].tool_latency_ms or -1, 0)
        self.assertEqual(result.trace[-1].validation_result, "valid_sources")


if __name__ == "__main__":
    unittest.main()
