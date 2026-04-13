from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Summary:
    line1: str
    line2: str


class CodeSummarizer:
    def summarize_path(self, path: Path) -> Summary:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise IsADirectoryError(f"Expected a file, got a directory: {path}")

        content = path.read_text(encoding="utf-8", errors="ignore")
        ext = path.suffix.lower().lstrip(".")
        lang = self._language_name(ext)
        lines = content.splitlines()

        imports = self._extract_imports(content, ext)
        functions = self._extract_functions(content, ext)
        classes = self._extract_classes(content, ext)
        traits = self._extract_traits(content, ext)
        patterns = self._detect_patterns(content, ext)

        primary_type = self._primary_type(lang, functions, classes)
        components = []
        if functions:
            components.append(f"{len(functions)} fn")
        if classes:
            components.append(f"{len(classes)} class")
        if traits:
            components.append(f"{len(traits)} trait")

        line1 = primary_type
        if components:
            line1 += f" ({', '.join(components)})"
        line1 += f" - {len(lines)} lines"

        details = []
        if imports:
            details.append(f"uses: {', '.join(imports[:3])}")
        if patterns:
            details.append(f"patterns: {', '.join(patterns[:3])}")
        if not details and functions:
            details.append(f"defines: {', '.join(functions[:3])}")
        if not details and classes:
            details.append(f"defines: {', '.join(classes[:3])}")

        line2 = " | ".join(details) if details else "General purpose code file"
        return Summary(line1=line1, line2=line2)

    def format_summary(self, path: Path) -> str:
        summary = self.summarize_path(path)
        fingerprint = hashlib.sha1(Path(path).read_bytes()).hexdigest()
        return "\n".join(
            [
                summary.line1,
                summary.line2,
                f"[smart: {Path(path).name} | sha1:{fingerprint[:8]}]",
            ]
        )

    def _language_name(self, ext: str) -> str:
        return {
            "rs": "Rust",
            "py": "Python",
            "js": "JavaScript",
            "mjs": "JavaScript",
            "cjs": "JavaScript",
            "ts": "TypeScript",
            "tsx": "TypeScript",
            "go": "Go",
            "c": "C",
            "h": "C",
            "cpp": "C++",
            "cc": "C++",
            "cxx": "C++",
            "hpp": "C++",
            "hh": "C++",
            "java": "Java",
            "rb": "Ruby",
            "sh": "Shell",
            "bash": "Shell",
            "zsh": "Shell",
        }.get(ext, "Code")

    def _primary_type(self, lang: str, functions: list[str], classes: list[str]) -> str:
        if classes and functions:
            return f"{lang} module"
        if classes:
            return f"{lang} classes"
        if functions:
            return f"{lang} functions"
        return f"{lang} code"

    def _extract_imports(self, content: str, ext: str) -> list[str]:
        patterns = {
            "rs": r"^use\s+([a-zA-Z_][a-zA-Z0-9_]*(?:::[a-zA-Z_][a-zA-Z0-9_]*)?)",
            "py": r"^(?:from\s+(\S+)|import\s+(\S+))",
            "js": r"(?:import.*from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
            "mjs": r"(?:import.*from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
            "cjs": r"(?:import.*from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
            "ts": r"(?:import.*from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
            "tsx": r"(?:import.*from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
            "go": r'^\s*"([^"]+)"$',
        }
        pattern = patterns.get(ext)
        if not pattern:
            return []

        re_import = re.compile(pattern)
        seen = set()
        imports: list[str] = []
        for line in content.splitlines():
            match = re_import.search(line)
            if not match:
                continue
            value = next((group for group in match.groups() if group), None)
            if not value:
                continue
            base = value.split("::")[0].split("/")[0]
            if base in seen or self._is_std_import(base, ext):
                continue
            seen.add(base)
            imports.append(base)
        return imports[:5]

    def _is_std_import(self, name: str, ext: str) -> bool:
        if ext == "rs":
            return name in {"std", "core", "alloc"}
        if ext == "py":
            return name in {"os", "sys", "re", "json", "typing", "pathlib"}
        return False

    def _extract_functions(self, content: str, ext: str) -> list[str]:
        patterns = {
            "rs": r"(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "py": r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "js": r"(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)|(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:async\s+)?\(",
            "mjs": r"(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)|(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:async\s+)?\(",
            "cjs": r"(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)|(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:async\s+)?\(",
            "ts": r"(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)|(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:async\s+)?\(",
            "tsx": r"(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)|(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:async\s+)?\(",
            "go": r"func\s+(?:\([^)]+\)\s+)?([a-zA-Z_][a-zA-Z0-9_]*)",
        }
        pattern = patterns.get(ext)
        if not pattern:
            return []
        return [name for name in self._collect_matches(content, re.compile(pattern)) if name not in {"main", "new"}][:10]

    def _extract_classes(self, content: str, ext: str) -> list[str]:
        patterns = {
            "rs": r"(?:pub\s+)?(?:struct|enum)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "py": r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "ts": r"(?:interface|class|type)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "tsx": r"(?:interface|class|type)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "go": r"type\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+struct",
            "java": r"(?:public\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "rb": r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        }
        pattern = patterns.get(ext)
        if not pattern:
            return []
        return self._collect_matches(content, re.compile(pattern))[:10]

    def _extract_traits(self, content: str, ext: str) -> list[str]:
        patterns = {
            "rs": r"(?:pub\s+)?trait\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "ts": r"interface\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "tsx": r"interface\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        }
        pattern = patterns.get(ext)
        if not pattern:
            return []
        return self._collect_matches(content, re.compile(pattern))[:5]

    def _detect_patterns(self, content: str, ext: str) -> list[str]:
        patterns = []
        lower = content.lower()
        if "async" in lower and "await" in lower:
            patterns.append("async")
        if ext == "rs":
            if "impl" in content and "for" in content:
                patterns.append("trait impl")
            if "#[derive" in content:
                patterns.append("derive")
            if "result<" in lower or "anyhow::" in lower:
                patterns.append("error handling")
            if "#[test]" in content:
                patterns.append("tests")
        elif ext == "py":
            if "@dataclass" in content:
                patterns.append("dataclass")
            if "def __init__" in content:
                patterns.append("oop")
        elif ext in {"js", "mjs", "cjs", "ts", "tsx"}:
            if "usestate" in lower or "useeffect" in lower:
                patterns.append("react hooks")
            if "export default" in lower:
                patterns.append("es modules")
        return patterns[:3]

    def _collect_matches(self, content: str, regex: re.Pattern[str]) -> list[str]:
        seen = set()
        result: list[str] = []
        for match in regex.finditer(content):
            name = next((group for group in match.groups() if group), None)
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(name)
        return result
