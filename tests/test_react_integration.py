import json
import unittest
from pathlib import Path

from semantic_kernel import Kernel

from src.azure_document_plugin import AzureDocumentPlugin
from src.document_store import DocumentStore
from src.react_runner import ReactRunner, ScriptedModel, build_test_prompt


class ReactIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_tolerant_output_runs_real_semantic_kernel_plugin(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        store = DocumentStore(project_root / "docs" / "corpus")
        store.load()
        kernel = Kernel()
        kernel.add_plugin(
            AzureDocumentPlugin(store),
            plugin_name="azure_docs",
        )
        model = ScriptedModel(
            [
                "```text\n"
                "thought： I need local evidence.\n"
                "action： SEARCH_DOCUMENTS\n"
                "action input： {\n"
                '  "query":"disk for backup and infrequently accessed data",\n'
                '  "top_k":1\n'
                "}\n"
                "```",
                "Thought: The observed section directly answers the question.\n"
                "Final Answer: Standard HDD is suitable for backup and "
                "infrequently accessed data.\n"
                "Sources:\n"
                "- https://learn.microsoft.com/en-us/azure/virtual-machines/disks-types",
            ]
        )
        runner = ReactRunner(
            kernel,
            model,
            build_test_prompt,
            max_steps=3,
        )

        result = await runner.run("Which disk suits backup data?")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.trace[0].action, "search_documents")
        observation = json.loads(result.trace[0].observation or "{}")
        self.assertEqual(observation["status"], "success")
        self.assertEqual(
            observation["results"][0]["documentId"],
            "managed_disk_types",
        )
        self.assertIn("Standard HDD", result.answer or "")

    async def test_empty_query_through_kernel_is_an_observation_not_exception(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        store = DocumentStore(project_root / "docs" / "corpus")
        store.load()
        kernel = Kernel()
        kernel.add_plugin(
            AzureDocumentPlugin(store),
            plugin_name="azure_docs",
        )

        result = await kernel.invoke(
            plugin_name="azure_docs",
            function_name="search_documents",
            query="   ",
            top_k=3,
        )

        self.assertIsNotNone(result)
        payload = json.loads(str(result))
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "invalid_query")
