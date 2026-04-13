from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import subprocess
from pathlib import Path


@dataclass
class CommandSummary:
    command: str
    exit_code: int
    lines: int
    summary: str


class CommandSummarizer:
    def run(self, command: str, verbose: bool = False) -> CommandSummary:
        command = command.strip()
        if not command:
            raise ValueError("Command cannot be empty")

        completed = self._execute(command, verbose=verbose)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        raw = f"{stdout}\n{stderr}".strip()
        summary = self._summarize_output(raw, command, completed.returncode == 0)
        line_count = len(raw.splitlines()) if raw else 0
        return CommandSummary(
            command=command,
            exit_code=completed.returncode,
            lines=line_count,
            summary=summary,
        )

    def format_summary(self, command: str, verbose: bool = False) -> str:
        result = self.run(command, verbose=verbose)
        return "\n".join(
            [
                result.summary,
                f"[command: {result.command} | exit: {result.exit_code} | lines: {result.lines}]",
            ]
        )

    def _execute(self, command: str, verbose: bool = False) -> subprocess.CompletedProcess[str]:
        if verbose:
            print(f"Running: {command}")
        if os.name == "nt":
            return subprocess.run(
                ["cmd", "/C", command],
                capture_output=True,
                text=True,
                check=False,
            )
        return subprocess.run(
            ["sh", "-c", command],
            capture_output=True,
            text=True,
            check=False,
        )

    def _summarize_output(self, output: str, command: str, success: bool) -> str:
        lines = output.splitlines()
        result: list[str] = []
        status_icon = "[ok]" if success else "[FAIL]"
        result.append(f"{status_icon} Command: {self._truncate(command, 60)}")
        result.append(f"   {len(lines)} lines of output")
        result.append("")

        output_type = self._detect_output_type(output, command)
        if output_type == "test":
            self._summarize_tests(output, result)
        elif output_type == "build":
            self._summarize_build(output, result)
        elif output_type == "log":
            self._summarize_logs(output, result)
        elif output_type == "json":
            self._summarize_json(output, result)
        elif output_type == "list":
            self._summarize_list(output, result)
        else:
            self._summarize_generic(output, result)
        return "\n".join(result)

    def _detect_output_type(self, output: str, command: str) -> str:
        cmd_lower = command.lower()
        out_lower = output.lower()

        test_patterns = (
            r"\bpytest\b",
            r"\bvitest\b",
            r"\brspec\b",
            r"\bgo\s+test\b",
            r"\bcargo\s+test\b",
            r"\bnpm\s+(run\s+)?test\b",
            r"\bpnpm\s+(run\s+)?test\b",
            r"\byarn\s+test\b",
        )
        is_test_command = any(re.search(pattern, cmd_lower) for pattern in test_patterns)
        if is_test_command or ("passed" in out_lower and "failed" in out_lower):
            return "test"
        if "build" in cmd_lower or "compile" in cmd_lower or "compiling" in out_lower:
            return "build"
        if "error:" in out_lower or "warn:" in out_lower or "[info]" in out_lower:
            return "log"
        if output.strip().startswith("{") or output.strip().startswith("["):
            return "json"
        if output and all(
            len(line) < 200 and ("\t" not in line) and len(line.split()) < 10
            for line in lines_or_empty(output)
        ):
            return "list"
        return "generic"

    def _summarize_tests(self, output: str, result: list[str]) -> None:
        passed = failed = skipped = 0
        failure_lines: list[str] = []
        for line in output.splitlines():
            lower = line.lower()
            if "passed" in lower or " ok" in lower:
                passed += self._extract_number(lower, "passed")
            if "failed" in lower or " fail" in lower:
                failed += max(1, self._extract_number(lower, "failed"))
                if "0 failed" not in lower:
                    failure_lines.append(line)
            if "skipped" in lower or "ignored" in lower:
                skipped += self._extract_number(lower, "skipped") or self._extract_number(lower, "ignored")
        result.append("Test Results:")
        result.append(f"   [ok] {passed} passed")
        if failed:
            result.append(f"   [FAIL] {failed} failed")
        if skipped:
            result.append(f"   skip {skipped} skipped")
        if failure_lines:
            result.append("")
            result.append("   Failures:")
            for line in failure_lines[:5]:
                result.append(f"   - {self._truncate(line, 70)}")

    def _summarize_build(self, output: str, result: list[str]) -> None:
        errors = warnings = compiled = 0
        error_lines: list[str] = []
        for line in output.splitlines():
            lower = line.lower()
            if "error" in lower and "0 error" not in lower:
                errors += 1
                if len(error_lines) < 5:
                    error_lines.append(line)
            if "warning" in lower and "0 warning" not in lower:
                warnings += 1
            if "compiling" in lower or "compiled" in lower:
                compiled += 1
        result.append("Build Summary:")
        if compiled:
            result.append(f"   {compiled} crates/files compiled")
        if errors:
            result.append(f"   [error] {errors} errors")
        if warnings:
            result.append(f"   [warn] {warnings} warnings")
        if not errors and not warnings:
            result.append("   [ok] Build successful")
        if error_lines:
            result.append("")
            result.append("   Errors:")
            for line in error_lines:
                result.append(f"   - {self._truncate(line, 70)}")

    def _summarize_logs(self, output: str, result: list[str]) -> None:
        errors = warnings = info = 0
        for line in output.splitlines():
            lower = line.lower()
            if "error" in lower:
                errors += 1
            if "warn" in lower:
                warnings += 1
            if "info" in lower:
                info += 1
        result.append("Log Summary:")
        result.append(f"   errors={errors} warnings={warnings} info={info}")
        preview = [line for line in output.splitlines() if line.strip()][:5]
        if preview:
            result.append("")
            result.append("   Preview:")
            for line in preview:
                result.append(f"   - {self._truncate(line, 80)}")

    def _summarize_json(self, output: str, result: list[str]) -> None:
        try:
            payload = json.loads(output)
        except Exception:
            result.append("JSON-like output")
            result.append(f"   {self._truncate(output, 120)}")
            return
        if isinstance(payload, dict):
            result.append("JSON Object:")
            result.append(f"   keys={len(payload)}")
            keys = list(payload.keys())[:8]
            if keys:
                result.append(f"   top keys: {', '.join(map(str, keys))}")
        elif isinstance(payload, list):
            result.append("JSON Array:")
            result.append(f"   items={len(payload)}")
            if payload:
                result.append(f"   first item type: {type(payload[0]).__name__}")
        else:
            result.append(f"JSON Value: {type(payload).__name__}")

    def _summarize_list(self, output: str, result: list[str]) -> None:
        lines = [line for line in output.splitlines() if line.strip()]
        result.append("List Output:")
        result.append(f"   items={len(lines)}")
        for line in lines[:6]:
            result.append(f"   - {self._truncate(line, 80)}")

    def _summarize_generic(self, output: str, result: list[str]) -> None:
        lines = [line for line in output.splitlines() if line.strip()]
        result.append("Output Summary:")
        result.append(f"   non-empty lines={len(lines)}")
        for line in lines[:5]:
            result.append(f"   - {self._truncate(line, 90)}")

    def _extract_number(self, text: str, keyword: str) -> int:
        match = re.search(rf"(\d+)\s*{re.escape(keyword)}", text)
        return int(match.group(1)) if match else 0

    def _truncate(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."


def lines_or_empty(output: str) -> list[str]:
    return output.splitlines() if output else []
