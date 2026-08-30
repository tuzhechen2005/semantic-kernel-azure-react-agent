import hashlib
import json
from pathlib import Path


REQUIRED_METADATA = {"id", "title", "source", "version", "updated"}


def _read_document(path: Path) -> tuple[dict[str, str], list[str]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"missing front matter: {path.name}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"unterminated front matter: {path.name}") from exc
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"invalid front matter: {path.name}")
        metadata[key.strip()] = value.strip()
    missing = REQUIRED_METADATA - metadata.keys()
    if missing:
        raise ValueError(f"missing metadata {sorted(missing)}: {path.name}")
    sections = [line[3:].strip() for line in lines[end + 1 :] if line.startswith("## ")]
    if not sections:
        raise ValueError(f"document has no sections: {path.name}")
    return metadata, sections


def build_corpus_manifest(corpus_dir: Path) -> dict[str, object]:
    documents: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for path in sorted(corpus_dir.glob("*.md")):
        metadata, sections = _read_document(path)
        document_id = metadata["id"]
        if document_id in seen_ids:
            raise ValueError(f"duplicate document id: {document_id}")
        seen_ids.add(document_id)
        source = metadata["source"]
        if not source.startswith("https://learn.microsoft.com/"):
            raise ValueError(f"non-official source: {source}")
        documents.append(
            {
                "documentId": document_id,
                "title": metadata["title"],
                "source": source,
                "version": metadata["version"],
                "updated": metadata["updated"],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "sections": [f"{document_id}#{index}" for index, _ in enumerate(sections, 1)],
            }
        )
    if not documents:
        raise ValueError("corpus is empty")
    canonical = json.dumps(documents, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schemaVersion": "task2-corpus-manifest-v1",
        "documentCount": len(documents),
        "corpusSha256": hashlib.sha256(canonical).hexdigest(),
        "documents": documents,
    }


def write_corpus_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
