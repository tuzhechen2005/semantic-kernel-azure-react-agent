from pathlib import Path

from src.document_store import DocumentStore


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    corpus_dir = project_root / "docs" / "corpus"

    store = DocumentStore(corpus_dir)
    store.load()

    queries = [
        "fault domains and update domains",
        "protect virtual machines from datacenter failure",
        "disk for backup and infrequently accessed data",
    ]

    for query in queries:
        print(f"\n查询：{query}")

        results = store.search(query, top_k=3)

        for rank, result in enumerate(results, start=1):
            print(
                f"{rank}. {result.chunk.chunk_id} | "
                f"{result.chunk.section_title} | "
                f"score={result.score} | "
                f"matched={result.matched_terms}"
            )


if __name__ == "__main__":
    main()
