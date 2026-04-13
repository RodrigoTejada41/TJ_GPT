from __future__ import annotations

import re
import time
from pathlib import Path


def normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    print(f"[assistant] {message}")


class AppTimer:
    def __init__(self) -> None:
        self.start = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self.start


def approximate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def split_with_overlap(text: str, min_chars: int, max_chars: int, overlap: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + max_chars)
        if end < length:
            slice_text = text[start:end]
            split_point = max(
                slice_text.rfind("\n\n"),
                slice_text.rfind(". "),
                slice_text.rfind("; "),
            )
            if split_point > min_chars:
                end = start + split_point + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(0, end - overlap)
    if len(chunks) >= 2 and len(chunks[-1]) < min_chars // 2:
        chunks[-2] = (chunks[-2] + "\n\n" + chunks[-1]).strip()
        chunks.pop()
    return chunks
