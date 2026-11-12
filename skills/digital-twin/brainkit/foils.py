"""Foils: for each real message of the owner, the reply a generic AI assistant
would have sent instead. The twin sees the pair side by side (contrastive
examples, after TICL, Cho et al. 2025): the foil shows the polished, complete,
balanced default it must not write; the real message shows what the owner sent.

Stored in raw/foils.json as {item_id: foil}, outside the items table, and
copied into each persona's examples.jsonl by build. Generated in batches by a
small model through the `claude` CLI; any other runner can be passed in.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Callable

from . import raw, store

PROMPT = """Below are real WhatsApp-style messages a person sent, each with the message they were replying to.
For each one, write the reply a typical polite AI assistant would produce if asked to reply AS this person:
same content and stance, but in the assistant's default way (complete sentences, tidy and balanced, a bit
longer, friendly filler, maybe a closing line). Do not copy the real wording. This shows what NOT to sound like.

Reply with JSON only: {"<id>": "<assistant-style reply>", ...}

"""


def _path():
    return store.home() / "raw" / "foils.json"


def load() -> dict[str, str]:
    p = _path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save(foils: dict[str, str]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(foils, indent=1, ensure_ascii=False), encoding="utf-8")


def missing(limit: int = 1000) -> list[dict]:
    have = load()
    rows = [i for i in raw.items() if i.get("kind") == "example" and i["id"] not in have]
    return [{"id": i["id"], "context": i.get("context") or "", "text": i["text"]} for i in rows[:limit]]


def claude_runner(prompt: str, model: str = "haiku") -> str:
    out = subprocess.run(["claude", "-p", "--model", model, "--strict-mcp-config", "--mcp-config",
                          '{"mcpServers":{}}', "--disallowedTools",
                          "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task"],
                         input=prompt, capture_output=True, text=True, timeout=300)
    return out.stdout


def generate(batch: int = 15, runner: Callable[[str], str] | None = None, limit: int = 1000) -> dict:
    runner = runner or claude_runner
    todo = missing(limit)
    foils = load()
    made = 0
    for k in range(0, len(todo), batch):
        chunk = todo[k:k + batch]
        body = "\n\n".join(f"id: {x['id']}\nthey: {x['context'] or '(they started the chat)'}\nreal reply: {x['text']}"
                           for x in chunk)
        m = re.search(r"\{.*\}", runner(PROMPT + body) or "", re.S)
        try:
            got = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            got = {}
        for x in chunk:
            f = got.get(x["id"])
            if isinstance(f, str) and f.strip() and f.strip() != x["text"].strip():
                foils[x["id"]] = f.strip()
                made += 1
        save(foils)
    return {"made": made, "total": len(foils), "missing": len(missing(limit))}
