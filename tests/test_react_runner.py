import json
import unittest

from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function

from src.react_runner import ReactRunner, ScriptedModel, build_test_prompt


class FakeDocumentPlugin:
    def __init__(self) -> None:
        self.read_count = 0

    @kernel_function(name="search_documents")
    def search_documents(self, query: str, top_k: int = 3) -> str:
        return json.dumps(
            {
                "status": "success",
                "query": query,
                "topK": top_k,
                "documentId": "managed_disk_types",
                "source": "https://learn.microsoft.com/disk-types",
            }
        )

    @kernel_function(name="read_document")
    def read_document(self, document_id: str) -> str:
        self.read_count += 1
        return json.dumps(
            {
                "status": "success",
                "documentId": document_id,
                "content": "Standard HDD is suitable for backups.",
                "source": "https://learn.microsoft.com/disk-types",
            }
        )


class FlakySearchPlugin:
    def __init__(self) -> None:
        self.search_count = 0

    @kernel_function(name="search_documents")
    def search_documents(self, query: str, top_k: int = 3) -> str:
        self.search_count += 1
        if self.search_count == 1:
            return json.dumps(
                {
                    "status": "error",
                    "error": "search_failed",
                    "message": "temporary local search failure",
                    "source": "https://untrusted.example/failed",
                }
            )
        return json.dumps(
            {
                "status": "success",
                "query": query,
                "documentId": "managed_disk_types",
                "source": "https://learn.microsoft.com/disk-types",
            }
        )

def make_kernel() -> Kernel:
    kernel = Kernel()
    kernel.add_plugin(FakeDocumentPlugin(), plugin_name="azure_docs")
    return kernel


class ReactRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_read_and_finish(self) -> None:
        model = ScriptedModel(
            [
                "Thought: I need to search the documentation.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disk backup","top_k":2}',
                "Thought: I should read the matching document.\n"
                "Action: read_document\n"
                'Action Input: {"document_id":"managed_disk_types"}',
                "Thought: The document contains enough evidence.\n"
                "Final Answer: Standard HDD is suitable for backups.\n"
                "Source: https://learn.microsoft.com/disk-types",
            ]
        )
        runner = ReactRunner(
            make_kernel(),
            model,
            build_test_prompt,
            max_steps=4,
        )

        result = await runner.run("Which disk suits backup data?")

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.trace), 3)
        self.assertEqual(result.trace[0].action, "search_documents")
        self.assertEqual(result.trace[1].action, "read_document")
        self.assertIn("Standard HDD", result.answer or "")
        self.assertIn("Observation:", model.prompts[1])
        self.assertIn("managed_disk_types", model.prompts[2])

    async def test_parse_error_stops_after_retry_limit(self) -> None:
        model = ScriptedModel(["This is not a ReAct response."])
        runner = ReactRunner(
            make_kernel(),
            model,
            build_test_prompt,
            max_parse_retries=0,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "parse_error")
        self.assertEqual(len(result.trace), 1)
        self.assertEqual(result.trace[0].outcome, "parse_error")
        self.assertIn(
            "format_error",
            result.trace[0].observation or "",
        )

    async def test_parse_error_is_returned_to_model_and_corrected(self) -> None:
        model = ScriptedModel(
            [
                "I should search Azure documentation.",
                "Thought: I need local evidence.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disks"}',
                "Thought: The evidence is sufficient.\n"
                "Final Answer: Standard HDD.\n"
                "Source: https://learn.microsoft.com/disk-types",
            ]
        )
        runner = ReactRunner(
            make_kernel(),
            model,
            build_test_prompt,
            max_steps=3,
            max_parse_retries=2,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.trace[0].outcome, "parse_error")
        self.assertIn("format_error", model.prompts[1])
        self.assertEqual(result.trace[1].action, "search_documents")

    async def test_consecutive_parse_errors_stop_at_limit(self) -> None:
        model = ScriptedModel(["bad one", "bad two", "unused"])
        runner = ReactRunner(
            make_kernel(),
            model,
            build_test_prompt,
            max_steps=5,
            max_parse_retries=1,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "parse_error")
        self.assertEqual(len(result.trace), 2)
        self.assertEqual(len(model.prompts), 2)

    async def test_max_steps_stops_loop(self) -> None:
        action = (
            "Thought: I need another search.\n"
            "Action: search_documents\n"
            'Action Input: {"query":"Azure disks"}'
        )
        model = ScriptedModel([action, action, action])
        runner = ReactRunner(
            make_kernel(),
            model,
            build_test_prompt,
            max_steps=2,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "max_steps")
        self.assertEqual(len(result.trace), 2)
        self.assertEqual(len(model.prompts), 2)

    async def test_tool_error_is_reported(self) -> None:
        kernel = Kernel()
        model = ScriptedModel(
            [
                "Thought: Search first.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disks"}'
            ]
        )
        runner = ReactRunner(kernel, model, build_test_prompt)

        result = await runner.run("Question")

        self.assertEqual(result.status, "tool_error")
        self.assertEqual(result.trace[0].outcome, "tool_error")

    async def test_unobserved_source_url_is_rejected_then_corrected(self) -> None:
        model = ScriptedModel(
            [
                "Thought: Search first.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disks"}',
                "Thought: Evidence is sufficient.\n"
                "Final Answer: Standard HDD.\n"
                "Source: https://invented.example/disk",
                "Thought: I will use the exact observed source.\n"
                "Final Answer: Standard HDD.\n"
                "Source: https://learn.microsoft.com/disk-types",
            ]
        )
        runner = ReactRunner(
            make_kernel(),
            model,
            build_test_prompt,
            max_steps=3,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.trace[1].outcome, "answer_error")
        self.assertIn(
            "invalid_answer_sources",
            result.trace[1].observation or "",
        )

    async def test_fragment_on_observed_document_url_is_accepted(self) -> None:
        model = ScriptedModel(
            [
                "Thought: Search first.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disks"}',
                "Thought: Evidence is sufficient.\n"
                "Final Answer: Standard HDD.\n"
                "Source: https://learn.microsoft.com/disk-types#standard-hdd",
            ]
        )
        runner = ReactRunner(
            make_kernel(),
            model,
            build_test_prompt,
            max_steps=2,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "completed")

    async def test_duplicate_action_is_not_executed_twice(self) -> None:
        plugin = FakeDocumentPlugin()
        kernel = Kernel()
        kernel.add_plugin(plugin, plugin_name="azure_docs")
        repeated_read = (
            "Thought: Read the document.\n"
            "Action: read_document\n"
            'Action Input: {"document_id":"managed_disk_types"}'
        )
        model = ScriptedModel(
            [
                "Thought: Search first.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disks"}',
                repeated_read,
                repeated_read,
                "Thought: Existing evidence is sufficient.\n"
                "Final Answer: Standard HDD is suitable for backups.\n"
                "Source: https://learn.microsoft.com/disk-types",
            ]
        )
        runner = ReactRunner(
            kernel,
            model,
            build_test_prompt,
            max_steps=4,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "completed")
        self.assertEqual(plugin.read_count, 1)
        self.assertIn(
            "duplicate_action",
            result.trace[2].observation or "",
        )

    async def test_failed_tool_response_can_retry_same_action(self) -> None:
        plugin = FlakySearchPlugin()
        kernel = Kernel()
        kernel.add_plugin(plugin, plugin_name="azure_docs")
        search = (
            "Thought: Search the local documents.\n"
            "Action: search_documents\n"
            'Action Input: {"query":"Azure disks"}'
        )
        model = ScriptedModel(
            [
                search,
                search,
                "Thought: Evidence is now sufficient.\n"
                "Final Answer: Standard HDD.\n"
                "Source: https://learn.microsoft.com/disk-types",
            ]
        )
        runner = ReactRunner(
            kernel,
            model,
            build_test_prompt,
            max_steps=3,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "completed")
        self.assertEqual(plugin.search_count, 2)
        self.assertNotIn(
            "duplicate_action",
            result.trace[1].observation or "",
        )

    async def test_error_observation_does_not_supply_source_evidence(self) -> None:
        plugin = FlakySearchPlugin()
        kernel = Kernel()
        kernel.add_plugin(plugin, plugin_name="azure_docs")
        model = ScriptedModel(
            [
                "Thought: Search the local documents.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disks"}',
                "Thought: I will improperly cite the failed response.\n"
                "Final Answer: Unsupported.\n"
                "Source: https://untrusted.example/failed",
            ]
        )
        runner = ReactRunner(
            kernel,
            model,
            build_test_prompt,
            max_steps=2,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "max_steps")
        self.assertEqual(result.trace[1].outcome, "answer_error")

    async def test_first_action_must_be_search_then_can_recover(self) -> None:
        plugin = FakeDocumentPlugin()
        kernel = Kernel()
        kernel.add_plugin(plugin, plugin_name="azure_docs")
        model = ScriptedModel(
            [
                "Thought: Read immediately.\n"
                "Action: read_document\n"
                'Action Input: {"document_id":"managed_disk_types"}',
                "Thought: I must search first.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disks"}',
                "Thought: Evidence is sufficient.\n"
                "Final Answer: Standard HDD.\n"
                "Source: https://learn.microsoft.com/disk-types",
            ]
        )
        runner = ReactRunner(
            kernel,
            model,
            build_test_prompt,
            max_steps=3,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.trace[0].outcome, "protocol_error")
        self.assertIn("protocol_error", result.trace[0].observation or "")
        self.assertEqual(plugin.read_count, 0)

    async def test_unobserved_document_id_is_not_executed(self) -> None:
        plugin = FakeDocumentPlugin()
        kernel = Kernel()
        kernel.add_plugin(plugin, plugin_name="azure_docs")
        model = ScriptedModel(
            [
                "Thought: Search first.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disks"}',
                "Thought: Read another document.\n"
                "Action: read_document\n"
                'Action Input: {"document_id":"invented_document"}',
                "Thought: Existing evidence is sufficient.\n"
                "Final Answer: Standard HDD.\n"
                "Source: https://learn.microsoft.com/disk-types",
            ]
        )
        runner = ReactRunner(kernel, model, build_test_prompt, max_steps=3)

        result = await runner.run("Question")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.trace[1].outcome, "protocol_error")
        self.assertEqual(plugin.read_count, 0)

    async def test_model_exception_becomes_model_error(self) -> None:
        class BrokenModel:
            async def generate(self, prompt: str) -> str:
                raise RuntimeError("generation failed")

        runner = ReactRunner(
            make_kernel(),
            BrokenModel(),
            build_test_prompt,
        )

        result = await runner.run("Question")

        self.assertEqual(result.status, "model_error")
        self.assertEqual(result.trace[0].outcome, "model_error")


if __name__ == "__main__":
    unittest.main()
