"""Run one scripted multi-turn chat with the twin (claude -p, twin-agent/).

Turn 1 starts a session; later turns resume it, so the twin keeps the thread
the way a real chat does. Returns, per turn, the reply, the tool calls and the
tool output (the judge needs the output to tell grounded claims from guesses).
"""
from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent


def _turn(env: dict, text: str, model: str, session: str, first: bool) -> dict:
    # Isolated like a host would run it: project settings only (not the developer's
    # personal skills and memory), no built-in tools except Skill, twin-read MCP only.
    cmd = ["claude", "-p", "--model", model, "--strict-mcp-config", "--mcp-config", ".mcp.json",
           "--setting-sources", "project", "--tools", "Skill",
           "--output-format", "stream-json", "--verbose", "--allowedTools", "mcp__twin-read__*"]
    cmd += ["--session-id", session] if first else ["--resume", session]
    t = time.time()
    out = subprocess.run(cmd, input=text, cwd=PKG / "twin-agent", env=env,
                         capture_output=True, text=True, timeout=300)
    reply, calls, results, cost = "", [], [], None
    for line in out.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            reply, cost = ev.get("result", ""), ev.get("total_cost_usd")
        for c in (ev.get("message", {}) or {}).get("content", []) or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                calls.append({"id": c.get("id"), "name": c.get("name", "").split("__")[-1],
                              "input": c.get("input")})
            if c.get("type") == "tool_result":
                body = c.get("content")
                if isinstance(body, list):
                    body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                name = next((x["name"] for x in calls if x.get("id") == c.get("tool_use_id")), "?")
                results.append((name, str(body)))
    if not reply and out.returncode:
        reply = "[twin error] " + out.stderr[-300:]
    # Memory first (what grounds claims), then brief, then the rest; skill text dropped.
    order = {"search": 0, "walk": 0, "page": 0, "profile": 0, "brief": 1, "examples": 2}
    keep = sorted((r for r in results if r[0] not in ("Skill", "ToolSearch", "check_reply", "ask_owner")),
                  key=lambda r: order.get(r[0], 3))
    return {"msg": text, "reply": reply.strip(), "calls": calls,
            "tool_text": "\n---\n".join(f"[{n}]\n{b}" for n, b in keep),
            "secs": round(time.time() - t, 1), "cost": cost}


def converse(env: dict, sender: str, turns: list[str], model: str = "haiku") -> list[dict]:
    session = str(uuid.uuid4())
    out = []
    for i, msg in enumerate(turns):
        text = f"Message from {sender}:\n{msg}" if i == 0 else msg
        out.append(_turn(env, text, model, session, first=(i == 0)))
    return out
