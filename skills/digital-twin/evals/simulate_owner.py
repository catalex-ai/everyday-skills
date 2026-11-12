"""Simulated owner: answers the twin manager's questions during an eval round.

The owner knows only:
- the eval-side persona descriptions in evals/personas.json (for approvals)
- the held-back text in <corpus>/heldout/ and the hop-1 facts in truth.json
  (for information questions)

    python evals/simulate_owner.py --corpus DIR --question '<json>'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def owner_knowledge(corpus: Path) -> str:
    parts = []
    for p in sorted((corpus / "heldout").glob("*.txt")):
        parts.append(p.read_text(encoding="utf-8")[:6000])
    dossier = corpus / "dossier.md"
    if dossier.exists() and not (corpus / "truth.json").exists():
        # A synthetic owner knows their whole self; the eval cheat-sheet is cut.
        text = dossier.read_text(encoding="utf-8")
        cut = [i for i in (text.lower().find("cheat"), text.lower().find("per-scenario")) if i > 0]
        parts.append("Who I am, what I think and how I talk:\n" + text[:min(cut)] if cut else text)
        return "\n\n".join(parts)
    said = sorted((corpus / "sources").glob("voice-*.txt"))
    if said:
        parts.append("Things I have said, in my own words:\n" + "\n\n".join(
            p.read_text(encoding="utf-8")[:1500] for p in said[:5]))
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


# A real owner is not a perfect interviewee. With --owner-noise, a fixed share of
# answers (chosen by a hash of the question id, so runs are repeatable) is lazy,
# garbage, skipped, rambling or full of typos. The manager must cope.
NOISES = ("lazy", "garbage", "skip", "ramble", "typos")
NOISE_FIXED = {
    "garbage": ["asdf", "?", "lol what", "hmm", "idk man", "can we do this later"],
    "skip": ["skip", "next", "not now", "pass"],
}
NOISE_STYLE = {
    "lazy": "\n\nYou are tired and busy: answer in as few words as you can (2 to 6).",
    "ramble": ("\n\nYou are chatty right now: answer, then drift into an unrelated thought or "
               "a small story from your week, 4 to 6 sentences in all."),
    "typos": ("\n\nYou are typing fast on your phone: a few typos, no capital letters, "
              "missing punctuation."),
}


def _h(question: dict, salt: str) -> float:
    key = f"{salt}:{question.get('id') or question.get('text')}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _noise(question: dict, rate: float) -> str | None:
    if question.get("kind") == "approval" or rate <= 0 or _h(question, "noise") >= rate:
        return None
    return NOISES[int(_h(question, "kind") * len(NOISES)) % len(NOISES)]


def answer(question: dict, corpus: Path, model: str = "haiku", cwd: Path | None = None,
           noise_rate: float = 0.0) -> str:
    personas = json.loads((HERE / "personas.json").read_text(encoding="utf-8"))
    cwd = cwd or corpus
    if question.get("kind") == "approval":
        prompt = (
            f"{personas['approve']}\n\nPersona descriptions:\n"
            f"{json.dumps({k: v for k, v in personas.items() if k != 'approve'}, indent=1)}\n\n"
            f"Question from my assistant:\n{question.get('text')}\n\n"
            "Reply with one short sentence that starts with 'Yes' or 'No'.")
        return ask_model(prompt, model, cwd)
    noise = _noise(question, noise_rate)
    if noise in ("garbage", "skip"):
        return NOISE_FIXED[noise][int(_h(question, "pick") * len(NOISE_FIXED[noise]))]
    if question.get("reply_to"):
        prompt = (
            "You are role-playing the owner. Your assistant asks how you would reply to a message. "
            f"The message is from your {question.get('audience') or 'contact'}:\n\n"
            f"{question['reply_to']}\n\n"
            "Write ONLY your reply, exactly as you would type it to that person on your phone: "
            "your real habits with that kind of person (length, capitals, punctuation, emoji, "
            "language mix, sign-off), nothing else, no quotes, no explanation. Use the knowledge "
            "below for who you are, how you talk and what is true in your life; write a fresh "
            "reply, never copy a line from it. If a personal fact you would need is not in the "
            "knowledge, reply the way you would when you can't get into it right now."
            + NOISE_STYLE.get(noise, "") + f"\n\nKnowledge:\n{owner_knowledge(corpus)}")
        return ask_model(prompt, model, cwd)
    prompt = (
        "You are role-playing the owner answering a question from their own assistant. "
        "Answer in the first person, briefly, using ONLY the knowledge below for facts. "
        "If it asks how you talk or for real messages, write 2 or 3 short messages exactly as "
        "you would text them (your habits, your words), one per line, each with who it was to; "
        "write fresh ones, do not copy lines from the knowledge. If it asks what you think or "
        "for a story, answer in your voice from what the knowledge says you believe and did. "
        "If a FACT is not in the knowledge, reply exactly: I don't know.\n\n"
        + NOISE_STYLE.get(noise, "")
        + f"\n\nKnowledge:\n{owner_knowledge(corpus)}\n\nQuestion:\n{question.get('text')}")
    return ask_model(prompt, model, cwd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--owner-noise", type=float, default=0.0)
    a = ap.parse_args()
    print(answer(json.loads(a.question), Path(a.corpus).expanduser(), a.model, noise_rate=a.owner_noise))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
