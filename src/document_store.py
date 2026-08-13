import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "how",
    "i",
    "in",
    "is",
    "of",
    "on",
    "the",
    "to",
    "what",
    "which",
    "with",
}

@dataclass(frozen=True)
class Document:
    document_id: str
    title: str
    source: str
    content: str
    path: Path

@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    document_id: str
    document_title: str
    section_title: str
    source: str
    content: str

@dataclass(frozen=True)
class SearchResult:
    chunk: DocumentChunk
    score: float
    matched_terms: tuple[str, ...]

class DocumentStore:

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens: list[str] = []

        for token in TOKEN_PATTERN.findall(text.lower()):
            if token in STOP_WORDS:
                continue

            if len(token) > 3 and token.endswith("s"):
                token = token[:-1]

            tokens.append(token)

        return tokens

    def __init__(self, corpus_dir: Path) -> None:
        self.corpus_dir = corpus_dir.resolve()
        self.documents: dict[str, Document] = {}
        self.chunks: list[DocumentChunk] = []

    def load(self) -> None:
        if not self.corpus_dir.exists():
            raise FileNotFoundError(
                f"文档目录不存在：{self.corpus_dir}"
            )

        if not self.corpus_dir.is_dir():
            raise NotADirectoryError(
                f"文档路径不是目录：{self.corpus_dir}"
            )

        loaded_documents: dict[str, Document] = {}

        for path in sorted(self.corpus_dir.glob("*.md")):
            document = self._load_document(path)

            if document.document_id in loaded_documents:
                raise ValueError(
                    f"发现重复文档 ID：{document.document_id}"
                )

            loaded_documents[document.document_id] = document

        if not loaded_documents:
            raise ValueError(
                f"文档目录中没有 Markdown 文件：{self.corpus_dir}"
            )

        self.documents = loaded_documents
        self.chunks = [
            chunk
            for document in self.documents.values()
            for chunk in self._split_document(document)
        ]

    def get_document(self, document_id: str) -> Document | None:
        normalized_id = document_id.strip()

        if not normalized_id:
            return None

        return self.documents.get(normalized_id)

    def _load_document(self, path: Path) -> Document:
        text = path.read_text(encoding="utf-8")
        metadata, content = self._parse_front_matter(text, path)

        return Document(
            document_id=metadata["id"],
            title=metadata["title"],
            source=metadata["source"],
            content=content,
            path=path.resolve(),
        )

    def search(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[SearchResult]:
        if not self.chunks:
            raise RuntimeError("文档仓库尚未加载，请先调用 load()")

        if not query.strip():
            raise ValueError("检索查询不能为空")

        if top_k < 1:
            raise ValueError("top_k 必须大于或等于 1")

        query_tokens = set(self._tokenize(query))

        if not query_tokens:
            return []

        document_frequencies: Counter[str] = Counter()

        tokenized_chunks: list[
            tuple[DocumentChunk, Counter[str], Counter[str], Counter[str]]
        ] = []

        for chunk in self.chunks:
            title_tokens = Counter(
                self._tokenize(chunk.document_title)
            )
            section_tokens = Counter(
                self._tokenize(chunk.section_title)
            )
            content_tokens = Counter(
                self._tokenize(chunk.content)
            )

            all_terms = (
                set(title_tokens)
                | set(section_tokens)
                | set(content_tokens)
            )

            for term in all_terms:
                document_frequencies[term] += 1

            tokenized_chunks.append(
                (
                    chunk,
                    title_tokens,
                    section_tokens,
                    content_tokens,
                )
            )

        results: list[SearchResult] = []
        chunk_count = len(self.chunks)

        for (
            chunk,
            title_tokens,
            section_tokens,
            content_tokens,
        ) in tokenized_chunks:
            matched_terms = sorted(
                term
                for term in query_tokens
                if (
                    term in title_tokens
                    or term in section_tokens
                    or term in content_tokens
                )
            )

            if not matched_terms:
                continue

            score = 0.0

            for term in matched_terms:
                inverse_document_frequency = math.log(
                    (chunk_count + 1)
                    / (document_frequencies[term] + 1)
                ) + 1.0

                weighted_frequency = (
                    2 * title_tokens[term]
                    + 4 * section_tokens[term]
                    + content_tokens[term]
                )

                score += (
                    inverse_document_frequency
                    * min(weighted_frequency, 6)
                )

            results.append(
                SearchResult(
                    chunk=chunk,
                    score=round(score, 4),
                    matched_terms=tuple(matched_terms),
                )
            )

        results.sort(
            key=lambda result: (
                -result.score,
                result.chunk.chunk_id,
            )
        )

        return results[:top_k]

    @staticmethod
    def _split_document(document: Document) -> list[DocumentChunk]:
        sections: list[tuple[str, list[str]]] = []
        current_title = "Overview"
        current_lines: list[str] = []

        for line in document.content.splitlines():
            if line.startswith("# "):
                continue

            if line.startswith("## "):
                if any(existing_line.strip() for existing_line in current_lines):
                    sections.append((current_title, current_lines))

                current_title = line.removeprefix("## ").strip()
                current_lines = []
                continue

            current_lines.append(line)

        if any(existing_line.strip() for existing_line in current_lines):
            sections.append((current_title, current_lines))

        chunks: list[DocumentChunk] = []

        for index, (section_title, section_lines) in enumerate(
            sections,
            start=1,
        ):
            content = "\n".join(section_lines).strip()

            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document.document_id}#{index}",
                    document_id=document.document_id,
                    document_title=document.title,
                    section_title=section_title,
                    source=document.source,
                    content=content,
                )
            )

        return chunks

    @staticmethod
    def _parse_front_matter(
        text: str,
        path: Path,
    ) -> tuple[dict[str, str], str]:
        lines = text.splitlines()

        if not lines or lines[0].strip() != "---":
            raise ValueError(
                f"文档缺少 front matter 起始标记：{path}"
            )

        try:
            closing_index = next(
                index
                for index, line in enumerate(lines[1:], start=1)
                if line.strip() == "---"
            )
        except StopIteration as exc:
            raise ValueError(
                f"文档缺少 front matter 结束标记：{path}"
            ) from exc

        metadata: dict[str, str] = {}

        for line in lines[1:closing_index]:
            if not line.strip():
                continue

            if ":" not in line:
                raise ValueError(
                    f"无效的 front matter 行：{path}: {line}"
                )

            key, value = line.split(":", maxsplit=1)
            metadata[key.strip()] = value.strip()

        required_fields = {"id", "title", "source"}
        missing_fields = required_fields - metadata.keys()

        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(
                f"文档缺少元数据字段：{path}: {missing}"
            )

        content = "\n".join(lines[closing_index + 1:]).strip()

        if not content:
            raise ValueError(f"文档正文为空：{path}")

        return metadata, content
