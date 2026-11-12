"""Manager eval: is the brain the manager built good enough for the twin?

    python evals/brain_audit.py --corpus ~/.twin-corpora/<name> --brain <TWIN_HOME> [--out file.json]

Per persona, two kinds of numbers, never blended:
- features (code): items by kind, distinct example contexts, voice/soul/card
  lines, persona-building questions still open.
- brain judge (Opus, 1-5): life_coverage, accuracy, voice_quality,
  soul_quality, privacy; plus "missing": what the twin will lack in chats.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import judge as J  # noqa: E402

RUBRIC = """You audit the memory a "digital twin" will use to chat on WhatsApp as a real person (the owner),
for ONE audience (persona). Compare it with the DOSSIER (ground truth) and the owner's REAL MESSAGES.
Be harsh. Score 1-5 each, separately:

life_coverage: does the twin know the core of the owner's life that this persona may know (identity, current
  work and role, key people and how they relate, where they live/are from if allowed, key past, current numbers)?
  5 = everything a close contact of this kind would expect them to know; 1 = mostly missing.
accuracy: are the stored facts true and current (outdated ones flagged/absent)? 5 = no errors.
voice_quality: would VOICE + EXAMPLES let someone imitate the owner's texting? Concrete, observable habits with
  frequency and setting, real messages across situations (small talk, work, no/deflect, feelings, advice). 1 = generic
  adjectives or nothing; 3 = some habits, thin examples; 5 = rich, accurate, not caricatured.
soul_quality: do SOUL + OPINIONS + STORIES capture how the owner thinks: stances with reasons, values, stories they
  tell? 1 = none/generic; 5 = rich and specific.
privacy: nothing this persona must not know is present (5) ... clear leaks (1).

Also list "missing": up to 10 concrete things the twin will need in everyday chats but cannot find here
(e.g. "how she talks to her cofounder", "her view on remote work", "current team size"), and "leaks".

Reply with JSON only:
{"life_coverage": n, "accuracy": n, "voice_quality": n, "soul_quality": n, "privacy": n,
 "missing": [], "leaks": [], "summary": "one or two lines"}"""


def _read(p: Path) -> str:
    try:
        return re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S).strip()
    except OSError:
        return ""


def _jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def features(brain: Path, persona: str) -> dict:
    d = brain / "personas" / persona
    facts = _jsonl(d / "facts.jsonl")
    ex = _jsonl(d / "examples.jsonl")
    kinds: dict[str, int] = {}
    for f in facts:
        kinds[f.get("kind", "fact")] = kinds.get(f.get("kind", "fact"), 0) + 1
    ctx = {" ".join(re.findall(r"[a-z]+", (e.get("context") or "").lower())[:3]) for e in ex}
    lines = lambda t: len([l for l in t.splitlines() if l.strip().startswith(("-", "*")) or len(l) > 30])  # noqa
    qs = json.loads((brain / "questions.json").read_text()) if (brain / "questions.json").exists() else []
    open_build = sorted({q["field"] for q in qs if q.get("kind") == "info" and q.get("status") == "open"
                         and q.get("field") in ("voice_close", "voice_work", "voice_no", "voice_feelings",
                                                 "opinions", "opinion_changed", "values", "stories")})
    return {"facts": kinds.get("fact", 0), "opinions": kinds.get("opinion", 0), "stories": kinds.get("story", 0),
            "examples": len(ex), "example_contexts": len(ctx - {""}),
            "voice_lines": lines(_read(d / "voice.md")), "soul_lines": lines(_read(d / "soul.md")),
            "card_lines": _read(d / "card.md").count("\n- ") + 1 if _read(d / "card.md") else 0,
            "stale_flagged": sum(1 for f in facts if f.get("stale")),
            "open_persona_questions": open_build}


def judge_brain(corpus: Path, brain: Path, persona: str, rule: str, model: str) -> dict:
    d = brain / "personas" / persona
    facts = _jsonl(d / "facts.jsonl")
    pick = lambda k, n: "\n".join(f"- {f['text']}" for f in facts if f.get("kind", "fact") == k)[:n]  # noqa
    ex = "\n".join(f"- ({e.get('context')}) {e['text']}" for e in _jsonl(d / "examples.jsonl"))[:5000]
    prompt = (f"{RUBRIC}\n\n=== DOSSIER ===\n{_read(corpus / 'dossier.md')[:16000]}\n\n"
              f"=== REAL MESSAGES (owner) ===\n{_read(corpus / 'samples.md')[:5000]}\n\n"
              f"=== WHAT THIS PERSONA MAY KNOW ===\n{rule}\n\n"
              f"=== TWIN MEMORY for persona '{persona}' ===\n"
              f"--- LIFE CARD ---\n{_read(d / 'card.md')[:5000]}\n--- VOICE ---\n{_read(d / 'voice.md')}\n"
              f"--- SOUL ---\n{_read(d / 'soul.md')}\n--- RULES ---\n{_read(d / 'rules.md')}\n"
              f"--- OPINIONS ---\n{pick('opinion', 4000)}\n--- STORIES ---\n{pick('story', 3000)}\n"
              f"--- EXAMPLES (real messages) ---\n{ex}\n--- OTHER FACTS (sample) ---\n{pick('fact', 5000)}\n")
    for _ in range(2):
        j = J.parse(J._ask(prompt, model, brain))
        if j and "life_coverage" in j:
            return j
    return {"error": "brain judge failed"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--brain", required=True)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--out")
    a = ap.parse_args()
    corpus, brain = Path(a.corpus).expanduser(), Path(a.brain).expanduser()
    personas = json.loads((HERE / "personas.json").read_text(encoding="utf-8"))
    out = {}
    for p, v in personas.items():
        if p == "approve" or not (brain / "personas" / p).is_dir():
            continue
        rule = f"audience: {v['audience']}\nmay know: {v['include']}\nmust NOT know: {v['exclude']}"
        out[p] = {"features": features(brain, p), "judge": judge_brain(corpus, brain, p, rule, a.model)}
    dst = Path(a.out) if a.out else brain.parent / "brain_audit.json"
    dst.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    for p, r in out.items():
        j = r["judge"]
        print(f"## {p}\nfeatures: {json.dumps(r['features'])}\n"
              + " ".join(f"{k}={j.get(k)}" for k in ("life_coverage", "accuracy", "voice_quality",
                                                     "soul_quality", "privacy"))
              + f"\nmissing: {j.get('missing')}\nleaks: {j.get('leaks')}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
