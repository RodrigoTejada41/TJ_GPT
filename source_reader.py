from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path


@dataclass
class ReadOptions:
    level: str = "minimal"
    max_lines: int | None = None
    tail_lines: int | None = None
    line_numbers: bool = False


class SourceReader:
    def read_path(self, path: Path, options: ReadOptions | None = None) -> str:
        options = options or ReadOptions()
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise IsADirectoryError(f"Expected a file, got a directory: {path}")

        content = path.read_text(encoding="utf-8", errors="ignore")
        lang = self._language_from_suffix(path.suffix.lower())
        filtered = self._apply_filter(content, lang, options.level)
        filtered = self._apply_window(filtered, options.max_lines, options.tail_lines)

        if options.line_numbers:
            filtered = self._add_line_numbers(filtered)
        return filtered

    def _language_from_suffix(self, suffix: str) -> str:
        return {
            ".rs": "rust",
            ".py": "python",
            ".js": "js",
            ".mjs": "js",
            ".cjs": "js",
            ".ts": "js",
            ".tsx": "js",
            ".go": "go",
            ".c": "c",
            ".h": "c",
            ".cpp": "c",
            ".cc": "c",
            ".cxx": "c",
            ".hpp": "c",
            ".hh": "c",
            ".java": "c",
            ".rb": "ruby",
            ".sh": "sh",
            ".bash": "sh",
            ".zsh": "sh",
        }.get(suffix, "text")

    def _apply_filter(self, content: str, lang: str, level: str) -> str:
        if level in {"raw", "none"} or lang == "text":
            return content.strip()
        if level == "aggressive":
            return self._strip_comments(content, lang, keep_imports=False)
        return self._strip_comments(content, lang, keep_imports=True)

    def _strip_comments(self, content: str, lang: str, keep_imports: bool) -> str:
        lines = content.splitlines()
        output: list[str] = []
        in_block = False
        in_docstring = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                output.append("")
                continue

            if lang == "python" and stripped.startswith(('"""', "'''")):
                in_docstring = not in_docstring
                if not keep_imports:
                    continue
                output.append(line.rstrip())
                continue

            if in_docstring:
                if keep_imports:
                    output.append(line.rstrip())
                continue

            if self._is_block_comment_start(stripped, lang):
                in_block = True
                if self._is_block_comment_end(stripped, lang):
                    in_block = False
                continue

            if in_block:
                if self._is_block_comment_end(stripped, lang):
                    in_block = False
                continue

            if self._is_line_comment(stripped, lang):
                continue

            if not keep_imports and self._looks_like_import(stripped, lang):
                continue

            output.append(line.rstrip())

        return self._normalize_blank_lines("\n".join(output)).strip()

    def _is_line_comment(self, line: str, lang: str) -> bool:
        prefixes = {
            "python": ("#",),
            "rust": ("//",),
            "js": ("//",),
            "go": ("//",),
            "c": ("//",),
            "ruby": ("#",),
            "sh": ("#",),
        }
        return any(line.startswith(prefix) for prefix in prefixes.get(lang, ()))

    def _is_block_comment_start(self, line: str, lang: str) -> bool:
        prefixes = {
            "rust": ("/*", "/**"),
            "js": ("/*", "/**"),
            "go": ("/*", "/**"),
            "c": ("/*", "/**"),
            "ruby": ("=begin",),
        }
        return any(line.startswith(prefix) for prefix in prefixes.get(lang, ()))

    def _is_block_comment_end(self, line: str, lang: str) -> bool:
        endings = {
            "rust": ("*/",),
            "js": ("*/",),
            "go": ("*/",),
            "c": ("*/",),
            "ruby": ("=end",),
        }
        return any(line.endswith(end) or line.startswith(end) for end in endings.get(lang, ()))

    def _looks_like_import(self, line: str, lang: str) -> bool:
        if lang == "python":
            return line.startswith("import ") or line.startswith("from ")
        if lang == "rust":
            return line.startswith("use ")
        if lang == "js":
            return line.startswith("import ") or "require(" in line
        if lang == "go":
            return line.startswith('"') and line.endswith('"')
        return False

    def _normalize_blank_lines(self, text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _apply_window(self, content: str, max_lines: int | None, tail_lines: int | None) -> str:
        lines = content.splitlines()
        if tail_lines is not None:
            if tail_lines <= 0:
                return ""
            lines = lines[-tail_lines:]
        elif max_lines is not None and max_lines > 0 and len(lines) > max_lines:
            remainder = len(lines) - max_lines
            lines = lines[:max_lines] + [f"... {remainder} more lines ..."]
        return "\n".join(lines).strip()

    def _add_line_numbers(self, content: str) -> str:
        lines = content.splitlines()
        width = len(str(len(lines)))
        return "\n".join(f"{i + 1:>{width}} | {line}" for i, line in enumerate(lines))

