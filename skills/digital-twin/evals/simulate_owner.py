"""Simulated owner: answers the twin manager's questions during an eval round.

The owner knows only:
- the eval-side persona descriptions in evals/personas.json (for approvals)
- the held-back text in <corpus>/heldout/ and the hop-1 facts in truth.json
  (for information questions)

    python evals/simulate_owner.py --corpus DIR --question '<json>'
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def owner_knowledge(corpus: Path) -> str:
    parts = []
    for p in sorted((corpus / "heldout").glob("*.txt")):
        parts.append(p.read_text(encoding="utf-8")[:6000])
    truth = json.loads((corpus / "truth.json").read_text(encoding="utf-8"))
    lines = [f"- my {t['p_label']}: {t['o']}" if not t.get("inverse")
             else f"- {t['o']} has me as {t['p_label']}"
             for t in truth if t.get("hop") == 1]
    parts.append("Facts I know about myself:\n" + "\n".join(lines))
    return "\n\n".join(parts)


def ask_model(prompt: str, model: str, cwd: Path) -> str:
    out = subprocess.run(
        ["claude", "-p", "--model", model, "--strict-mcp-config",
         "--mcp-config", '{"mcpServers":{}}', "--disallowedTools",
         "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task"],
        input=prompt, cwd=cwd, capture_output=True, text=True, timeout=180)
    return out.stdout.strip()


def answer(question: dict, corpus: Path, model: str = "haiku", cwd: Path | None = None) -> str:
    personas = json.loads((HERE / "personas.json").read_text(encoding="utf-8"))
    cwd = cwd or corpus
    if question.get("kind") == "approval":
        prompt = (
            f"{personas['approve']}\n\nPersona descriptions:\n"
            f"{json.dumps({k: v for k, v in personas.items() if k != 'approve'}, indent=1)}\n\n"
            f"Question from my assistant:\n{question.get('text')}\n\n"
            "Reply with one short sentence that starts with 'Yes' or 'No'.")
        return ask_model(prompt, model, cwd)
    prompt = (
        "You are role-playing the owner answering a question from their own assistant. "
        "Answer in the first person, briefly, using ONLY the knowledge below. If the "
        "knowledge does not contain the answer, reply exactly: I don't know.\n\n"
        f"Knowledge:\n{owner_knowledge(corpus)}\n\nQuestion:\n{question.get('text')}")
    return ask_model(prompt, model, cwd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--model", default="haiku")
    a = ap.parse_args()
    print(answer(json.loads(a.question), Path(a.corpus).expanduser(), a.model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
