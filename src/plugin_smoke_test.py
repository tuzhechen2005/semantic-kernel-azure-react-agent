import asyncio

from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function


class AzureDocumentPlugin:
    @kernel_function(
        name="search_documents",
        description="Search local Azure technical documents."
    )
    def search_documents(self, query: str) -> str:
        return f"模拟检索结果：找到了与 '{query}' 相关的 Azure 文档。"


async def main() -> None:
    kernel = Kernel()

    kernel.add_plugin(
        AzureDocumentPlugin(),
        plugin_name="azure_docs",
    )

    result = await kernel.invoke(
        plugin_name="azure_docs",
        function_name="search_documents",
        query="Azure virtual machine availability zones",
    )

    print("插件调用结果：")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())