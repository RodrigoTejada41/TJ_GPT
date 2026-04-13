from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Iterable

from obsidian_loader import ObsidianLoader


@dataclass
class SearchOptions:
    max_results: int = 20
    per_file: int = 3
    context_chars: int = 60
    regex: bool = False


class VaultSearcher:
    def __init__(self, loader: ObsidianLoader) -> None:
        self.loader = loader

    def search(self, vault_path: Path, query: str, options: SearchOptions | None = None) -> str:
        options = options or SearchOptions()
        vault_path = Path(vault_path)
        if not vault_path.exists():
            raise FileNotFoundError(f"Vault path not found: {vault_path}")

        pattern = self._compile_pattern(query, options.regex)
        by_file: dict[str, list[tuple[int, str]]] = {}
        total = 0

        for document in self.loader.iter_documents(vault_path):
            matches = self._search_document(document.content, pattern, options)
            if not matches:
                continue
            by_file[document.path] = matches
            total += len(matches)
            if total >= options.max_results:
                break

        return self._format_results(query, by_file, total, options)

    def _compile_pattern(self, query: str, regex: bool) -> re.Pattern[str]:
        if not query.strip():
            raise ValueError("Query cannot be empty")
        flags = re.IGNORECASE
        pattern = query if regex else re.escape(query)
        return re.compile(pattern, flags)

    def _search_document(
        self,
        content: str,
        pattern: re.Pattern[str],
        options: SearchOptions,
    ) -> list[tuple[int, str]]:
        results: list[tuple[int, str]] = []
        for line_num, line in enumerate(content.splitlines(), start=1):
            if not pattern.search(line):
                continue
            snippet = self._trim_snippet(line, pattern, options.context_chars)
            results.append((line_num, snippet))
            if len(results) >= options.per_file:
                break
        return results

    def _trim_snippet(self, line: str, pattern: re.Pattern[str], context_chars: int) -> str:
        if len(line) <= context_chars:
            return self._highlight(line, pattern)

        match = pattern.search(line)
        if not match:
            return line[: max(0, context_chars - 3)] + "..."

        start = max(0, match.start() - context_chars // 2)
        end = min(len(line), start + context_chars)
        if end < len(line):
            snippet = line[start:end] + "..."
        else:
            snippet = line[start:end]
        if start > 0:
            snippet = "..." + snippet
        return self._highlight(snippet, pattern)

    def _highlight(self, text: str, pattern: re.Pattern[str]) -> str:
        return pattern.sub(lambda m: f"[{m.group(0)}]", text)

    def _format_results(
        self,
        query: str,
        by_file: dict[str, list[tuple[int, str]]],
        total: int,
        options: SearchOptions,
    ) -> str:
        if not by_file:
            return f"0 matches for '{query}'"

        lines = [f"{total} matches in {len(by_file)} files", ""]
        shown = 0
        for path in sorted(by_file):
            matches = by_file[path]
            if shown >= options.max_results:
                break
            lines.append(f"[file] {self._compact_path(path)} ({len(matches)}):")
            for line_num, snippet in matches[: options.per_file]:
                lines.append(f"  {line_num:>4}: {snippet}")
                shown += 1
                if shown >= options.max_results:
                    break
            lines.append("")
        if total > shown:
            lines.append(f"... +{total - shown}")
        return "\n".join(lines).strip()

    def _compact_path(self, path: str) -> str:
        if len(path) <= 60:
            return path
        parts = Path(path).parts
        if len(parts) <= 3:
            return path
        return str(Path(parts[0]) / "..." / Path(*parts[-2:]))

