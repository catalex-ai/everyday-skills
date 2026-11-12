"""Data ledger: what the manager collected into a brain, by type, audience and provenance.

    python evals/ledger.py --corpus ~/.twin-corpora/<name> --run c12h

Writes runs/<run>/ledger.json and ledger.md, and prints a one-line summary.
Tracked across rounds next to the chat scores, so a manager change can be
judged by the data it brings in, not only by the twin's replies.

- kinds: fact / opinion / story / example, split by where they came from
  (a document the owner shared, or the owner's answer to a question).
- examples (the owner's real messages): which kind of person they were to
  (from the stored context), whether the context records what the other
  person said (a conversation pair), median length, and whether the text is
  verbatim real: found word for word in the corpus (sources, held-out
  material, the owner's recorded words). The rest were written during the
  manager's questions, i.e. imitations, which teach the twin less.
- questions: which facets were asked and their status.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics as st
from collections import Counter
from pathlib import Path

AUDIENCES = [
    ("family", r"mother|mum|mom|dad|father|aai|baba|sister|brother|parent|wife|husband|partner|son|daughter|"
               r"cousin|family|kid|child|uncle|aunt|grand"),
    ("close friend", r"friend|buddy|mate|school|college|roommate"),
    ("press", r"journalist|reporter|podcast|interview|host|press|magazine|newspaper|radio|tv\b|television"),
    ("investor/boss", r"investor|boss|board|vc\b|angel|funder|manager\b|ceo|chair"),
    ("customer", r"customer|client|prospect|user\b|buyer"),
    ("work peer", r"colleague|teammate|team|co-?founder|engineer|ex-teammate|staff|coworker|peer|founder"),
    ("candidate/recruiter", r"candidate|recruit|hire|hiring|applicant|job"),
    ("public/fan", r"fan|follower|audience|stranger|public|linkedin|post|viewer|crowd|student|town hall|"
                   r"supporter|reader|subscriber"),
]
PAIR = re.compile(r"\b(says|said|asks|asked|asking|writes|wrote|texts|texted|messages|replies to|tells|told)\b|[\"“]")


def norm(t: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", t.lower()))


def corpus_text(corpus: Path) -> str:
    parts = []
    for d in ("sources", "heldout", "sources-extra"):
        for p in sorted((corpus / d).glob("*.txt")):
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    for f in ("voice/records.jsonl",):
        p = corpus / f
        if p.exists():
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return norm("\n".join(parts))


def audience(ctx: str) -> str:
    low = (ctx or "").lower()
    for name, pat in AUDIENCES:
        if re.search(pat, low):
            return name
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    corpus = Path(a.corpus).expanduser()
    run = corpus / "runs" / a.run
    brain = run / "brain"
    db = sqlite3.connect(brain / "raw" / "brain.sqlite")
    rows = db.execute("select id, text, kind, context, by, category from items where status='active'").fetchall()
    ctext = corpus_text(corpus)

    kinds = Counter((k or "fact", by or "doc") for _, _, k, _, by, _ in rows)
    ex = [r for r in rows if r[2] == "example"]
    aud = Counter(audience(r[3]) for r in ex)
    pairs = sum(1 for r in ex if PAIR.search(r[3] or ""))
    real = [r for r in ex if len(norm(r[1])) >= 12 and norm(r[1]) in ctext]
    lens = [len(r[1].split()) for r in ex]
    samples = {}
    for k in ("fact", "opinion", "story", "example"):
        samples[k] = [{"text": r[1][:200], "context": r[3], "by": r[4]} for r in rows if (r[2] or "fact") == k][:3]
    fake = [{"text": r[1][:160], "context": r[3]} for r in ex if r not in real][:4]

    qs = json.loads((brain / "questions.json").read_text()) if (brain / "questions.json").exists() else []
    asked = Counter((q.get("field") or q.get("kind"), q.get("status")) for q in qs)

    out = {
        "run": a.run,
        "kinds": {f"{k}/{by}": n for (k, by), n in sorted(kinds.items())},
        "examples": len(ex),
        "examples_real_verbatim": len(real),
        "examples_pairs": pairs,
        "examples_words_median": st.median(lens) if lens else 0,
        "examples_by_audience": dict(aud.most_common()),
        "questions": {f"{f}:{s}": n for (f, s), n in sorted(asked.items(), key=str)},
        "samples": samples,
        "imitation_samples": fake,
    }
    (run / "ledger.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    md = [f"# Data ledger: {corpus.name} {a.run}", "",
          "| kind / from | items |", "|---|---|"] + [f"| {k} | {n} |" for k, n in out["kinds"].items()]
    md += ["", f"Real messages: {len(ex)} (verbatim real {len(real)}, conversation pairs {pairs}, "
               f"median {out['examples_words_median']} words)", "",
           "| audience | messages |", "|---|---|"] + [f"| {k} | {n} |" for k, n in aud.most_common()]
    md += ["", "Questions (facet:status):", ""] + [f"- {k}: {n}" for k, n in out["questions"].items()]
    md += ["", "Samples:"] + [f"- [{k}] ({s['by']}) {s['text']}" + (f"  — {s['context']}" if s.get("context") else "")
                              for k, v in samples.items() for s in v]
    md += ["", "Messages that are not verbatim real (imitations):"] + [f"- {x['text']} — {x['context']}" for x in fake]
    (run / "ledger.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{corpus.name} {a.run}: examples {len(ex)} real {len(real)} pairs {pairs} "
          f"aud {dict(aud.most_common(4))} kinds {out['kinds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
