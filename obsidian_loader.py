from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from utils import approximate_tokens, split_with_overlap


@dataclass
class ObsidianDocument:
    file_name: str
    path: str
    content: str
    metadata: dict[str, Any]


@dataclass
class TextChunk:
    chunk_id: str
    file_name: str
    path: str
    text: str
    chunk_index: int
    metadata: dict[str, Any]


class ObsidianLoader:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.min_chars = 400
        self.max_chars = 900
        self.overlap = 120

    def load_vault(self, vault_path: Path) -> tuple[list[ObsidianDocument], list[TextChunk]]:
        documents: list[ObsidianDocument] = []
        chunks: list[TextChunk] = []
        for document in self.iter_documents(vault_path):
            documents.append(document)
            chunks.extend(self._chunk_document(document))
        return documents, chunks

    def count_markdown_files(self, vault_path: Path) -> int:
        return sum(1 for md_file in vault_path.rglob("*.md") if md_file.is_file())

    def iter_documents(self, vault_path: Path, start_index: int = 0):
        files = sorted(md_file for md_file in vault_path.rglob("*.md") if md_file.is_file())
        for md_file in files[start_index:]:
            if not md_file.is_file():
                continue
            try:
                content = md_file.read_text(encoding="utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not content:
                continue
            stat = md_file.stat()
            metadata = {
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "tokens_approx": approximate_tokens(content),
            }
            yield ObsidianDocument(
                file_name=md_file.name,
                path=str(md_file),
                content=content,
                metadata=metadata,
            )

    def _chunk_document(self, document: ObsidianDocument) -> list[TextChunk]:
        raw_chunks = split_with_overlap(document.content, self.min_chars, self.max_chars, self.overlap)
        result: list[TextChunk] = []
        for index, text in enumerate(raw_chunks):
            result.append(
                TextChunk(
                    chunk_id=f"{document.path}:{index}",
                    file_name=document.file_name,
                    path=document.path,
                    text=text,
                    chunk_index=index,
                    metadata={
                        "source_file": document.file_name,
                        "source_path": document.path,
                        "source_hash": document.metadata.get("sha256", ""),
                        "chunk_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "tokens_approx": approximate_tokens(text),
                    },
                )
            )
        return result
