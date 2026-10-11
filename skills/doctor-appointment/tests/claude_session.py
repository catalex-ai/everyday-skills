"""Persistent native Claude Code actor for the synthetic clinic evaluation.

The adapter deliberately keeps MCP tool arguments and results in memory only.
Callers should redact them before writing public artifacts.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any


class ClaudeSessionError(RuntimeError):
    """A sanitized Claude session startup/protocol failure."""


class ClaudeSession:
    def __init__(self, root: str | Path, role: str, patient: str | None = None,
                 model: str = "haiku") -> None:
        if role not in {"patient", "doctor"}:
            raise ValueError("role must be patient or doctor")
        if patient is not None and patient not in {"patient-a", "patient-b"}:
            raise ValueError("patient must be patient-a or patient-b")
        self.root = Path(root).resolve()
        self.role = role
        self.model = ""
        self.inventory: dict[str, Any] = {"tools": [], "mcp_servers": [], "skills": []}
        self._lock = threading.Lock()
        self._seen_calls: dict[str, dict[str, Any]] = {}
        self._temp_config: tempfile.NamedTemporaryFile[str] | None = None
        agent_dir = self.root / f"{role}-agent"
        if not (agent_dir / "AGENTS.md").is_file():
            raise ClaudeSessionError("role instructions are missing")
        config_path = agent_dir / ".mcp.json"
        if patient is not None and role == "patient":
            # Identity is bound by trusted MCP startup configuration, never prompt text.
            config = {
                "mcpServers": {"clinic": {
                    "command": "python3",
                    "args": [str((self.root / "tools" / "server.py").resolve()),
                             "--role", "patient", "--patient", patient],
                }}
            }
            self._temp_config = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix="clinic-mcp-", suffix=".json", delete=False
            )
            json.dump(config, self._temp_config)
            self._temp_config.flush()
            self._temp_config.close()
            config_path = Path(self._temp_config.name)
        args = [
            "claude", "--restricted", "--tools", "Skill", "--strict-mcp-config",
            "--mcp-config", str(config_path), "--setting-sources", "",
            "--plugin-dir", ".claude", "--append-system-prompt-file", "AGENTS.md",
            "--settings", ".claude/settings.json", "--permission-mode", "dontAsk",
            "--no-chrome", "--model", model, "--print", "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose",
        ]
        try:
            self._proc = subprocess.Popen(
                args, cwd=agent_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except OSError:
            self._cleanup_config()
            raise ClaudeSessionError("could not start the native Claude CLI") from None

    def _cleanup_config(self) -> None:
        if self._temp_config is not None:
            try:
                os.unlink(self._temp_config.name)
            except FileNotFoundError:
                pass
            self._temp_config = None

    @staticmethod
    def _content_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(str(x.get("text", "")) for x in value if isinstance(x, dict) and x.get("type") == "text")
        return ""

    def send(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        with self._lock:
            if self._proc.poll() is not None:
                raise ClaudeSessionError("Claude session exited before the next turn")
            assert self._proc.stdin is not None and self._proc.stdout is not None
            try:
                self._proc.stdin.write(json.dumps({
                    "type": "user", "message": {"role": "user", "content": text}
                }, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                raise ClaudeSessionError("Claude session input failed") from None

            messages: list[str] = []
            turn_calls: dict[str, dict[str, Any]] = {}
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    raise ClaudeSessionError("Claude session ended before completing the turn")
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "system" and event.get("subtype") == "init":
                    self.model = str(event.get("model", ""))
                    self.inventory = {key: event.get(key, []) for key in ("tools", "mcp_servers", "skills")}
                    if "haiku" not in self.model.lower():
                        self.close()
                        raise ClaudeSessionError("Claude reported a non-Haiku model")
                elif kind == "assistant":
                    message = event.get("message", {})
                    for block in message.get("content", []) if isinstance(message, dict) else []:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text" and block.get("text"):
                            messages.append(block["text"])
                        elif block.get("type") == "tool_use":
                            call_id = str(block.get("id", ""))
                            name = str(block.get("name", ""))
                            short_name = name.removeprefix("mcp__clinic__")
                            turn_calls[call_id] = {
                                "tool": short_name,
                                "arguments": block.get("input", {}),
                                "result": {"content": []},
                            }
                elif kind == "user":
                    message = event.get("message", {})
                    for block in message.get("content", []) if isinstance(message, dict) and isinstance(message.get("content"), list) else []:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            call = turn_calls.get(str(block.get("tool_use_id", "")))
                            if call is not None:
                                val = block.get("content", [])
                                call["result"] = {"content": val if isinstance(val, list) else [{"type": "text", "text": str(val)}]}
                                if block.get("is_error"):
                                    call["status"] = "error"
                                else:
                                    call["status"] = "ok"
                elif kind == "result":
                    actual = str(event.get("model", "") or self.model)
                    if actual:
                        self.model = actual
                    if "haiku" not in self.model.lower():
                        self.close()
                        raise ClaudeSessionError("Claude reported a non-Haiku model")
                    self._seen_calls.update(turn_calls)
                    return {
                        "calls": list(turn_calls.values()), "messages": messages,
                        "status": "error" if event.get("is_error") else "ok",
                    }

    def close(self) -> None:
        proc = getattr(self, "_proc", None)
        if proc is not None and proc.poll() is None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
                proc.wait()
        self._cleanup_config()

    def __enter__(self) -> "ClaudeSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
