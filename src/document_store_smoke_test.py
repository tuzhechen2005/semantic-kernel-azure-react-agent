from pathlib import Path

from src.document_store import DocumentStore


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    corpus_dir = project_root / "docs" / "corpus"

    store = DocumentStore(corpus_dir)
    store.load()

    print(f"成功加载 {len(store.documents)} 篇文档：")

    for document in store.documents.values():
        print(
            f"- {document.document_id}: "
            f"{document.title} "
            f"({len(document.content)} characters)"
        )
    print(f"\n成功生成 {len(store.chunks)} 个文档块：")

    for chunk in store.chunks:
        print(
            f"- {chunk.chunk_id}: "
            f"{chunk.document_title} / {chunk.section_title} "
            f"({len(chunk.content)} characters)"
        )


if __name__ == "__main__":
    main()
