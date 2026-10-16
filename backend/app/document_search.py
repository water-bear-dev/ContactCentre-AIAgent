import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PAGE_MARKER = re.compile(r"<!--\s*Page:\s*(\d+)\s*-->")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
NUMBERED_SECTION = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+[A-Z].{2,100}$")
PLAIN_SECTION = re.compile(r"^[A-Z][A-Za-z0-9'’&()/,\-–— ]{2,99}$")
TOKEN = re.compile(r"[a-z0-9]{2,}")
STOP_WORDS = {
    "a", "about", "an", "and", "are", "be", "can", "does", "do", "for",
    "from", "have", "how", "i", "into", "is", "it", "its", "me", "more",
    "my", "not", "of", "our", "the", "their", "them", "this", "to", "under",
    "was", "we", "what", "when", "where", "which", "with", "would", "you", "your",
}
MAX_CHUNK_CHARS = 1600


@dataclass(frozen=True)
class DocumentExcerpt:
    source: str
    section: str
    page: int | None
    text: str


class LocalDocumentSearch:
    def __init__(self, knowledge_root: Path, document_files: Iterable[str]):
        self._knowledge_root = knowledge_root.resolve()
        self._chunks_by_file: dict[str, list[DocumentExcerpt]] = {}
        for relative_path in sorted(set(document_files)):
            path = (self._knowledge_root / relative_path).resolve()
            if self._knowledge_root not in path.parents:
                raise ValueError(f"Document path escapes the knowledge directory: {relative_path}")
            if not path.is_file():
                raise FileNotFoundError(f"Converted policy document is missing: {path}")
            chunks = self._chunk_document(relative_path, path.read_text(encoding="utf-8"))
            if not chunks:
                raise ValueError(f"Converted policy document contains no searchable text: {path}")
            self._chunks_by_file[relative_path] = chunks
        if not self._chunks_by_file:
            raise ValueError("No policy Markdown files were configured for local document search.")

    def search(
        self,
        query: str,
        document_files: Iterable[str],
        limit: int = 6,
        required_files: Iterable[str] = (),
    ) -> list[DocumentExcerpt]:
        query_terms = self._tokens(query)
        if not query_terms or limit <= 0:
            return []
        allowed = set(document_files)
        chunks = [
            chunk
            for relative_path in allowed
            for chunk in self._chunks_by_file.get(relative_path, [])
        ]
        if not chunks:
            return []
        document_frequency = Counter(
            term
            for chunk in chunks
            for term in set(self._tokens(f"{chunk.section} {chunk.text}"))
        )
        scores: list[tuple[float, DocumentExcerpt]] = []
        query_text = " ".join(query_terms)
        for chunk in chunks:
            terms = self._tokens(f"{chunk.section} {chunk.text}")
            frequencies = Counter(terms)
            unique_query_terms = set(query_terms)
            matched_terms = sum(1 for term in unique_query_terms if frequencies[term])
            minimum_matches = 1 if len(unique_query_terms) < 3 else min(3, math.ceil(len(unique_query_terms) * 0.6))
            if matched_terms < minimum_matches:
                continue
            length_norm = math.sqrt(max(len(terms), 1))
            score = 0.0
            for term in query_terms:
                frequency = frequencies[term]
                if not frequency:
                    continue
                idf = math.log(1 + (len(chunks) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                score += idf * (1 + math.log(frequency)) / length_norm
            searchable = f"{chunk.section} {chunk.text}".lower()
            if query_text and query_text in searchable:
                score += 2.0
            if score:
                scores.append((score, chunk))
        scores.sort(key=lambda result: result[0], reverse=True)
        selected: list[DocumentExcerpt] = []
        for relative_path in required_files:
            source = str(Path(relative_path).with_suffix(".pdf"))
            match = next((chunk for score, chunk in scores if score and chunk.source == source), None)
            if match is not None and match not in selected:
                selected.append(match)
        selected.extend(chunk for _, chunk in scores if chunk not in selected)
        return selected[:limit]

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [token for token in TOKEN.findall(text.lower()) if token not in STOP_WORDS]

    @classmethod
    def _chunk_document(cls, relative_path: str, markdown: str) -> list[DocumentExcerpt]:
        source = str(Path(relative_path).with_suffix(".pdf"))
        section = "Document body"
        page: int | None = None
        blocks: list[tuple[str, str, int | None]] = []
        current_lines: list[str] = []

        def flush() -> None:
            content = "\n".join(current_lines).strip()
            if content:
                blocks.append((section, content, page))
            current_lines.clear()

        for line in markdown.splitlines():
            page_match = PAGE_MARKER.fullmatch(line.strip())
            if page_match:
                flush()
                page = int(page_match.group(1))
                if section == "Document body":
                    section = f"Page {page}"
                continue
            heading_match = HEADING.match(line)
            if heading_match:
                flush()
                section = heading_match.group(1).strip()
            elif not current_lines and (
                NUMBERED_SECTION.match(line)
                or (
                    PLAIN_SECTION.fullmatch(line.strip())
                    and 2 <= len(line.split()) <= 14
                )
                or (line.strip().isupper() and 2 <= len(line.split()) <= 14)
            ):
                flush()
                section = line.strip()
            if not line.strip():
                flush()
            else:
                current_lines.append(line)
        flush()

        excerpts: list[DocumentExcerpt] = []
        current_text = ""
        current_section = ""
        current_page: int | None = None
        for block_section, content, block_page in blocks:
            parts = cls._split_large_block(content)
            for part in parts:
                same_group = block_section == current_section and block_page == current_page
                separator = "\n\n" if current_text else ""
                if current_text and (not same_group or len(current_text) + len(separator) + len(part) > MAX_CHUNK_CHARS):
                    excerpts.append(DocumentExcerpt(source, current_section, current_page, current_text))
                    current_text = ""
                    separator = ""
                current_text = f"{current_text}{separator}{part}"
                current_section = block_section
                current_page = block_page
        if current_text:
            excerpts.append(DocumentExcerpt(source, current_section, current_page, current_text))
        return excerpts

    @staticmethod
    def _split_large_block(text: str) -> list[str]:
        if len(text) <= MAX_CHUNK_CHARS:
            return [text]
        words = text.split()
        parts: list[str] = []
        current: list[str] = []
        current_length = 0
        for word in words:
            if current and current_length + len(word) + 1 > MAX_CHUNK_CHARS:
                parts.append(" ".join(current))
                current = []
                current_length = 0
            current.append(word)
            current_length += len(word) + 1
        if current:
            parts.append(" ".join(current))
        return parts
