import asyncio
import json
from pathlib import Path

from semantic_kernel import Kernel

from src.azure_document_plugin import AzureDocumentPlugin
from src.document_store import DocumentStore


async def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    corpus_dir = project_root / "docs" / "corpus"

    store = DocumentStore(corpus_dir)
    store.load()

    kernel = Kernel()
    kernel.add_plugin(
        AzureDocumentPlugin(store),
        plugin_name="azure_docs",
    )

    result = await kernel.invoke(
        plugin_name="azure_docs",
        function_name="search_documents",
        query="disk for backup and infrequently accessed data",
        top_k=2,
    )

    if result is None:
        raise RuntimeError("插件没有返回结果")

    parsed_result = json.loads(str(result))

    print(
        json.dumps(
            parsed_result,
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n读取完整文档：")

    read_result = await kernel.invoke(
        plugin_name="azure_docs",
        function_name="read_document",
        document_id="managed_disk_types",
    )

    if read_result is None:
        raise RuntimeError("read_document 没有返回结果")

    parsed_document = json.loads(str(read_result))

    print(
        json.dumps(
            {
                "status": parsed_document["status"],
                "documentId": parsed_document["documentId"],
                "title": parsed_document["title"],
                "source": parsed_document["source"],
                "contentLength": len(parsed_document["content"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n非法文档 ID 安全检查：")

    invalid_result = await kernel.invoke(
        plugin_name="azure_docs",
        function_name="read_document",
        document_id="../../task2",
    )

    if invalid_result is None:
        raise RuntimeError("非法文档 ID 测试没有返回结果")

    print(
        json.dumps(
            json.loads(str(invalid_result)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
