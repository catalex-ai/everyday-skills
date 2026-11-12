"""Prepare a corpus for conversation evals (run once per corpus, model calls are Opus).

    python evals/prepare_corpus.py ~/.twin-corpora/<name> [--probes 12]

- dossier.md: ground truth for the judge. Kept if it exists (hand-written for
  synthetic owners); otherwise built from truth.json and the lead/personal
  source sections of a fetched corpus.
- samples.md: reference samples of the owner's real words for the judge,
  from voice_gold.jsonl (never from the training sources).
- probes.json: style-probe scenarios from held-out real answers. When the
  source did not state the question, Opus infers the most likely one and the
  probe is marked "inferred".
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import judge as J


def build_dossier(corpus: Path) -> str:
    truth = json.loads((corpus / "truth.json").read_text(encoding="utf-8"))
    lines = ["# Facts (structured)"]
    for t in truth:
        if t.get("hop") == 1:
            lines.append(f"- my {t['p_label']}: {t['o']}" if not t.get("inverse")
                         else f"- {t['o']} has me as {t['p_label']}")
        elif t.get("hop") == 2:
            lines.append(f"- {t.get('s')} {t['p_label']}: {t['o']}")
    lines.append("\n# Background text (encyclopedic)")
    for p in sorted((corpus / "sources").glob("0[0-6]-*.txt")):
        lines.append(f"## {p.stem}\n" + p.read_text(encoding="utf-8")[:3500])
    qa = [p for p in sorted((corpus / "sources").glob("voice-*.txt"))
          if "Source: qa" in p.read_text(encoding="utf-8")[:300]]
    if qa:
        lines.append("\n# What I have said in interviews (my own words; facts in them are true)")
        for p in qa:
            lines.append(p.read_text(encoding="utf-8")[:6000])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--probes", type=int, default=12)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    corpus = Path(a.corpus).expanduser()

    if not (corpus / "dossier.md").exists():
        (corpus / "dossier.md").write_text(build_dossier(corpus), encoding="utf-8")

    gold = [json.loads(l) for l in (corpus / "voice_gold.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    rng = random.Random(a.seed)
    rng.shuffle(gold)
    rich = [r for r in gold if len(r["text"].split()) >= 15]
    probe_src = rich[:a.probes]
    sample_src = [r for r in gold if r not in probe_src]
    (corpus / "samples.md").write_text("\n\n".join(
        f"[{r.get('setting') or r['section']}]" + (f"\nAsked: {r['question']}" if r.get("question") else "")
        + f"\nOwner: {r['text']}" for r in sample_src[:25]), encoding="utf-8")

    probes = []
    for r in probe_src:
        q, how = r.get("question"), "stated"
        if not q:
            ans = J._ask(
                "Here is something a person said, verbatim, in a public setting "
                f"({r.get('setting') or r['section']}):\n\n\"{r['text']}\"\n\n"
                "Write the single short message (one or two sentences) that most plausibly prompted it, "
                "as someone would type it to them in a chat. It must be a question to THIS person about "
                "their own life, work, views or feelings, fitting the setting above; do not assume events "
                "the quote does not mention. Do not quote or hint at the answer's wording. "
                "Reply with the message only.", a.model, corpus)
            q, how = ans.strip().strip('"'), "inferred"
        sec = (r.get("section") or "").lower()
        close = any(w in sec for w in ("friend", "family", "mother", "father", "brother", "sister",
                                       "partner", "parent", "cousin", "sibling", "spouse"))
        role = r["section"] if r["source"] == "whatsapp" and r.get("section") else "an interviewer chatting informally"
        probes.append({"id": f"probe-{r['id']}", "type": ["style-probe"],
                       "persona": "personal" if close else "professional",
                       "from": {"name": "Neha", "role": role},
                       "turns": [q], "question_source": how, "gold": r["text"],
                       "expect": "Answer as the owner would. Graded on whether the thinking and the way of "
                                 "saying it match the owner's real answer, not on repeating it."})
    (corpus / "probes.json").write_text(json.dumps(probes, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"dossier_chars": len((corpus / "dossier.md").read_text()), "probes": len(probes),
                      "samples": min(25, len(sample_src))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
