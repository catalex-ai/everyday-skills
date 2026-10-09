import json
import subprocess
import sys
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "hooks" / "readonly_guard.py"


def run_guard(payload):
    """Returns (exit_code, stderr). 0 allows the call, 2 blocks it."""
    completed = subprocess.run(
        [sys.executable, "-I", str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stderr


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class BlockedToolTests(unittest.TestCase):
    def test_file_editing_tools_are_blocked(self):
        for tool in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
            code, err = run_guard({"tool_name": tool, "tool_input": {"file_path": "/tmp/x"}})
            self.assertEqual(code, 2, tool)
            self.assertIn("read-only", err)

    def test_reading_tools_are_allowed(self):
        for tool in ("Read", "Glob", "Grep", "Skill"):
            code, _ = run_guard({"tool_name": tool, "tool_input": {}})
            self.assertEqual(code, 0, tool)

    def test_unreadable_input_is_refused_rather_than_allowed(self):
        completed = subprocess.run([sys.executable, "-I", str(GUARD)], input="not json",
                                   capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2)


class ShellSmugglingTests(unittest.TestCase):
    """A deny-list of command names cannot catch these, which is why there is an allow-list."""

    def test_redirection_is_blocked(self):
        for command in ("echo hi > f.txt", "echo hi >> f.txt", "cat a > b",
                        "printf x > /tmp/f", "ls | tee f.txt"):
            code, err = run_guard(bash(command))
            self.assertEqual(code, 2, command)
            self.assertIn("redirection", err)

    def test_command_chaining_is_blocked(self):
        for command in ("ls; rm -rf demo", "ls && rm x", "ls `rm x`", "ls $(rm x)"):
            code, _ = run_guard(bash(command))
            self.assertEqual(code, 2, command)

    def test_destructive_commands_are_not_on_the_allow_list(self):
        for command in ("rm -rf demo", "mv a b", "cp a b", "trash x", "mkdir new",
                        "touch new", "chmod 777 x", "ditto a b", "rsync a b",
                        "osascript -e 'tell app'"):
            code, err = run_guard(bash(command))
            self.assertEqual(code, 2, command)
            self.assertIn("allow-list", err)

    def test_find_may_list_but_not_delete_or_exec(self):
        code, _ = run_guard(bash("find . -name '*.mov'"))
        self.assertEqual(code, 0)
        # A command containing ';' is stopped earlier, by the shell-trick rule.
        for command in ("find . -delete", "find . -exec rm {} +",
                        "find . -execdir rm {} +", "find . -ok rm {} +"):
            code, err = run_guard(bash(command))
            self.assertEqual(code, 2, command)
            self.assertIn("not -delete", err)


class PythonTests(unittest.TestCase):
    def test_only_the_skills_own_scripts_may_run(self):
        code, _ = run_guard(bash("python3 scripts/detox.py --target ~/Downloads"))
        self.assertEqual(code, 0)
        code, _ = run_guard(bash(
            "python3 .claude/skills/drive-detox/scripts/scan_local.py ~/Downloads"))
        self.assertEqual(code, 0)

    def test_inline_python_is_blocked(self):
        for command in ("python3 -c 'import shutil'", "python3 -m http.server"):
            code, err = run_guard(bash(command))
            self.assertEqual(code, 2, command)
            self.assertIn("own scripts", err)

    def test_inline_python_with_a_semicolon_is_also_blocked(self):
        # Caught by the shell-trick rule rather than the python rule; either is a block.
        code, _ = run_guard(bash("python3 -c 'import os; os.remove(\"x\")'"))
        self.assertEqual(code, 2)

    def test_someone_elses_script_is_blocked(self):
        code, err = run_guard(bash("python3 /tmp/evil.py"))
        self.assertEqual(code, 2)
        self.assertIn("read-only scripts", err)

    def test_output_must_land_in_tmp(self):
        code, err = run_guard(bash("python3 scripts/detox.py --save demo/report.txt"))
        self.assertEqual(code, 2)
        self.assertIn("/tmp", err)
        code, _ = run_guard(bash("python3 scripts/detox.py --save /tmp/report.txt"))
        self.assertEqual(code, 0)

    def test_output_flag_with_equals_is_checked_too(self):
        code, _ = run_guard(bash("python3 scripts/scan_local.py ~/x --output=demo/i.json"))
        self.assertEqual(code, 2)

    def test_every_write_flag_is_checked(self):
        for flag in ("--output", "--save", "--skip-report"):
            code, _ = run_guard(bash(f"python3 scripts/detox.py {flag} ~/Desktop/out.json"))
            self.assertEqual(code, 2, flag)


class SafeCommandTests(unittest.TestCase):
    def test_looking_around_is_allowed(self):
        for command in ("ls -la demo", "pwd", "cat README.md", "head -5 x", "du -sh .",
                        "stat demo", "wc -l x", "md5 -q x", "claude mcp list"):
            code, err = run_guard(bash(command))
            self.assertEqual(code, 0, f"{command}: {err}")

    def test_empty_command_is_refused(self):
        for command in ("", "   "):
            code, _ = run_guard(bash(command))
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
