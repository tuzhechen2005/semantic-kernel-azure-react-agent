import json
from typing import Annotated

from semantic_kernel.functions import kernel_function

from src.document_store import DocumentStore


class AzureDocumentPlugin:
    MAX_QUERY_LENGTH = 500
    MAX_DOCUMENT_ID_LENGTH = 128

    def __init__(self, document_store: DocumentStore) -> None:
        self.document_store = document_store

    @kernel_function(
        name="search_documents",
        description=(
            "Search local Azure technical documents and return "
            "the most relevant sections with source information."
        ),
    )
    def search_documents(
        self,
        query: Annotated[
            str,
            "A concise English search query for Azure technical information.",
        ],
        top_k: Annotated[
            int,
            "Number of document sections to return, from 1 to 5.",
        ] = 3,
    ) -> str:
        if not isinstance(query, str) or not query.strip():
            return self._error_response(
                "invalid_query",
                "query must be a non-empty string",
            )
        normalized_query = query.strip()
        if len(normalized_query) > self.MAX_QUERY_LENGTH:
            return self._error_response(
                "query_too_long",
                f"query must not exceed {self.MAX_QUERY_LENGTH} characters",
            )

        if isinstance(top_k, bool) or not isinstance(top_k, int):
            return self._error_response(
                "invalid_top_k",
                "top_k must be an integer from 1 to 5",
            )
        if top_k < 1 or top_k > 5:
            return self._error_response(
                "invalid_top_k",
                "top_k must be between 1 and 5",
            )

        try:
            results = self.document_store.search(
                query=normalized_query,
                top_k=top_k,
            )
        except Exception:
            return self._error_response(
                "search_failed",
                "The local document search could not be completed",
            )

        response = {
            "status": "success",
            "query": normalized_query,
            "resultCount": len(results),
            "results": [
                {
                    "documentId": result.chunk.document_id,
                    "title": result.chunk.document_title,
                    "section": result.chunk.section_title,
                    "source": result.chunk.source,
                    "content": result.chunk.content,
                }
                for result in results
            ],
        }

        return json.dumps(
            response,
            ensure_ascii=False,
        )

    @kernel_function(
        name="read_document",
        description=(
            "Read one complete local Azure document by document ID. "
            "Use a documentId returned by search_documents."
        ),
    )
    def read_document(
        self,
        document_id: Annotated[
            str,
            "Exact documentId returned by search_documents.",
        ],
    ) -> str:
        if not isinstance(document_id, str) or not document_id.strip():
            return self._error_response(
                "invalid_document_id",
                "document_id must be a non-empty string",
            )
        normalized_id = document_id.strip()
        if len(normalized_id) > self.MAX_DOCUMENT_ID_LENGTH:
            return self._error_response(
                "document_id_too_long",
                "document_id exceeds the allowed length",
            )

        try:
            document = self.document_store.get_document(normalized_id)
        except Exception:
            return self._error_response(
                "read_failed",
                "The local document could not be read",
            )

        if document is None:
            return self._error_response(
                "document_not_found",
                "No local document exists for the supplied document_id",
                documentId=normalized_id,
                availableDocumentIds=sorted(self.document_store.documents),
            )

        response = {
            "status": "success",
            "documentId": document.document_id,
            "title": document.title,
            "source": document.source,
            "content": document.content,
        }

        return json.dumps(
            response,
            ensure_ascii=False,
        )

    @staticmethod
    def _error_response(
        error: str,
        message: str,
        **details: object,
    ) -> str:
        return json.dumps(
            {
                "status": "error",
                "error": error,
                "message": message,
                **details,
            },
            ensure_ascii=False,
        )
