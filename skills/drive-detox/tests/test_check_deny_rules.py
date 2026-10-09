import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_deny_rules import (  # noqa: E402
    WRITE_TOOLS,
    case_only_mismatches,
    load_deny_rules,
    missing_rules,
    normalize_server_name,
)


class NameDerivationTests(unittest.TestCase):
    """Live MCP tool names keep case and dashes; spaces and dots become underscores."""

    def test_claude_ai_connector_name(self):
        self.assertEqual(normalize_server_name("claude.ai Google Drive"),
                         "claude_ai_Google_Drive")

    def test_case_is_preserved(self):
        self.assertEqual(normalize_server_name("Claude Docs"), "Claude_Docs")

    def test_dashes_are_preserved(self):
        self.assertEqual(normalize_server_name("claude-mem:mcp-search"),
                         "claude-mem_mcp-search")

    def test_plain_name_is_unchanged(self):
        self.assertEqual(normalize_server_name("drive"), "drive")

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(normalize_server_name("  drive  "), "drive")


class SettingsReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_collects_rules_across_several_files(self):
        first = self.write("a.json", {"permissions": {"deny": ["mcp__drive__create_file"]}})
        second = self.write("b.json", {"permissions": {"deny": ["mcp__drive__copy_file"]}})
        rules, read, problems = load_deny_rules([first, second])
        self.assertEqual(rules, {"mcp__drive__create_file", "mcp__drive__copy_file"})
        self.assertEqual(read, [first, second])
        self.assertEqual(problems, [])

    def test_missing_files_are_skipped_silently(self):
        rules, read, problems = load_deny_rules([self.root / "nope.json"])
        self.assertEqual((rules, read, problems), (set(), [], []))

    def test_malformed_json_is_reported_not_raised(self):
        path = self.root / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        rules, read, problems = load_deny_rules([path])
        self.assertEqual(rules, set())
        self.assertEqual(read, [])
        self.assertEqual(len(problems), 1)

    def test_settings_without_a_deny_list_yields_no_rules(self):
        path = self.write("c.json", {"theme": "dark"})
        rules, read, _ = load_deny_rules([path])
        self.assertEqual(rules, set())
        self.assertEqual(read, [path])


class CoverageTests(unittest.TestCase):
    def test_passes_only_when_every_write_tool_is_denied(self):
        rules = {f"mcp__drive__{tool}" for tool in WRITE_TOOLS}
        self.assertEqual(missing_rules("drive", rules), [])

    def test_names_the_tool_that_is_not_denied(self):
        self.assertEqual(missing_rules("drive", {"mcp__drive__create_file"}),
                         ["mcp__drive__copy_file"])

    def test_empty_rules_means_both_tools_missing(self):
        self.assertEqual(len(missing_rules("drive", set())), len(WRITE_TOOLS))

    def test_denying_the_whole_server_covers_every_tool(self):
        self.assertEqual(missing_rules("drive", {"mcp__drive"}), [])
        self.assertEqual(missing_rules("drive", {"mcp__drive__*"}), [])

    def test_a_different_server_does_not_count(self):
        rules = {f"mcp__other__{tool}" for tool in WRITE_TOOLS}
        self.assertEqual(len(missing_rules("drive", rules)), len(WRITE_TOOLS))

    def test_case_only_mismatch_is_surfaced_rather_than_silently_failing(self):
        needed = ["mcp__claude_ai_Google_Drive__create_file"]
        rules = {"mcp__claude_ai_google_drive__create_file"}
        found = case_only_mismatches(needed, rules)
        self.assertEqual(found, {needed[0]: "mcp__claude_ai_google_drive__create_file"})

    def test_no_mismatch_reported_when_nothing_is_close(self):
        self.assertEqual(case_only_mismatches(["mcp__drive__create_file"], {"Bash(rm:*)"}), {})


if __name__ == "__main__":
    unittest.main()
