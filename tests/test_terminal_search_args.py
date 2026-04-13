from __future__ import annotations

import unittest
from pathlib import Path

from cli import AssistantApp


class DummyVaultSearch:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str, object]] = []

    def search(self, vault_path: Path, query: str, options: object) -> str:
        self.calls.append((vault_path, query, options))
        return "ok"


class TerminalSearchArgsTests(unittest.TestCase):
    def setUp(self) -> None:
        # Avoid full app initialization; these tests only need command parsing behavior.
        self.app = AssistantApp.__new__(AssistantApp)
        self.app.config = {"vault_path": "./obsidian_vault"}
        self.app.vault_search = DummyVaultSearch()

    def test_parse_search_args_query_only(self) -> None:
        query, options = self.app._parse_search_args(["backup", "branch"])
        self.assertEqual(query, "backup branch")
        self.assertFalse(options.regex)
        self.assertEqual(options.max_results, 20)
        self.assertEqual(options.per_file, 3)
        self.assertEqual(options.context_chars, 60)

    def test_parse_search_args_with_all_options(self) -> None:
        query, options = self.app._parse_search_args(
            ["backup branch", "regex", "max", "30", "per_file", "5", "ctx", "80"]
        )
        self.assertEqual(query, "backup branch")
        self.assertTrue(options.regex)
        self.assertEqual(options.max_results, 30)
        self.assertEqual(options.per_file, 5)
        self.assertEqual(options.context_chars, 80)

    def test_parse_search_args_invalid_max_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid max_results"):
            self.app._parse_search_args(["todo", "max", "abc"])

    def test_parse_search_args_non_positive_ctx(self) -> None:
        with self.assertRaisesRegex(ValueError, "context_chars must be > 0"):
            self.app._parse_search_args(["todo", "ctx", "0"])

    def test_parse_search_args_empty_query(self) -> None:
        with self.assertRaisesRegex(ValueError, "Usage: /terminal search"):
            self.app._parse_search_args(["regex"])

    def test_busca_command_uses_advanced_options(self) -> None:
        self.app.handle_command('/buscar "backup branch" regex max 30 per_file 5 ctx 80')
        self.assertEqual(len(self.app.vault_search.calls), 1)
        vault_path, query, options = self.app.vault_search.calls[0]
        self.assertEqual(vault_path, Path("./obsidian_vault").expanduser())
        self.assertEqual(query, "backup branch")
        self.assertTrue(options.regex)
        self.assertEqual(options.max_results, 30)
        self.assertEqual(options.per_file, 5)
        self.assertEqual(options.context_chars, 80)

    def test_grep_command_uses_advanced_options(self) -> None:
        self.app.handle_command('/grep "todo item" max 12 per_file 2 ctx 40')
        self.assertEqual(len(self.app.vault_search.calls), 1)
        _, query, options = self.app.vault_search.calls[0]
        self.assertEqual(query, "todo item")
        self.assertFalse(options.regex)
        self.assertEqual(options.max_results, 12)
        self.assertEqual(options.per_file, 2)
        self.assertEqual(options.context_chars, 40)


if __name__ == "__main__":
    unittest.main()
