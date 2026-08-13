import json
import unittest
from pathlib import Path

from src.azure_document_plugin import AzureDocumentPlugin
from src.document_store import DocumentStore


class AzureDocumentPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        project_root = Path(__file__).resolve().parent.parent
        store = DocumentStore(project_root / "docs" / "corpus")
        store.load()
        cls.plugin = AzureDocumentPlugin(store)

    def test_search_contract_exposes_unambiguous_document_id(self) -> None:
        payload = json.loads(
            self.plugin.search_documents(
                "disk for backup and infrequently accessed data",
                top_k=1,
            )
        )
        result = payload["results"][0]

        self.assertEqual(result["documentId"], "managed_disk_types")
        self.assertIn("Standard HDD", result["content"])
        self.assertNotIn("chunkId", result)
        self.assertNotIn("score", result)
        self.assertNotIn("matchedTerms", result)

    def test_read_document_accepts_search_document_id(self) -> None:
        payload = json.loads(
            self.plugin.read_document("managed_disk_types")
        )

        self.assertEqual(payload["status"], "success")
        self.assertIn("Standard HDD", payload["content"])

    def test_empty_search_query_returns_structured_error(self) -> None:
        for query in ("", "   ", None, 123):
            with self.subTest(query=query):
                payload = json.loads(
                    self.plugin.search_documents(query, top_k=3)  # type: ignore[arg-type]
                )
                self.assertEqual(payload["status"], "error")
                self.assertEqual(payload["error"], "invalid_query")

    def test_invalid_top_k_returns_structured_error(self) -> None:
        for top_k in (0, 6, True, "3"):
            with self.subTest(top_k=top_k):
                payload = json.loads(
                    self.plugin.search_documents(
                        "Azure disks",
                        top_k=top_k,  # type: ignore[arg-type]
                    )
                )
                self.assertEqual(payload["status"], "error")
                self.assertEqual(payload["error"], "invalid_top_k")

    def test_empty_document_id_returns_structured_error(self) -> None:
        for document_id in ("", "   ", None, 123):
            with self.subTest(document_id=document_id):
                payload = json.loads(
                    self.plugin.read_document(document_id)  # type: ignore[arg-type]
                )
                self.assertEqual(payload["status"], "error")
                self.assertEqual(
                    payload["error"],
                    "invalid_document_id",
                )

    def test_internal_search_exception_is_contained(self) -> None:
        class BrokenStore:
            documents: dict[str, object] = {}

            def search(self, query: str, top_k: int) -> list[object]:
                raise RuntimeError("sensitive internal failure")

        plugin = AzureDocumentPlugin(BrokenStore())  # type: ignore[arg-type]
        payload = json.loads(plugin.search_documents("Azure", 1))

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "search_failed")
        self.assertNotIn("sensitive", payload["message"])

    def test_internal_read_exception_is_contained(self) -> None:
        class BrokenStore:
            documents: dict[str, object] = {}

            def get_document(self, document_id: str) -> object:
                raise RuntimeError("sensitive internal failure")

        plugin = AzureDocumentPlugin(BrokenStore())  # type: ignore[arg-type]
        payload = json.loads(plugin.read_document("managed_disk_types"))

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "read_failed")
        self.assertNotIn("sensitive", payload["message"])

    def test_overlong_inputs_return_structured_errors(self) -> None:
        query_payload = json.loads(
            self.plugin.search_documents(
                "x" * (self.plugin.MAX_QUERY_LENGTH + 1)
            )
        )
        id_payload = json.loads(
            self.plugin.read_document(
                "x" * (self.plugin.MAX_DOCUMENT_ID_LENGTH + 1)
            )
        )

        self.assertEqual(query_payload["error"], "query_too_long")
        self.assertEqual(id_payload["error"], "document_id_too_long")


if __name__ == "__main__":
    unittest.main()
