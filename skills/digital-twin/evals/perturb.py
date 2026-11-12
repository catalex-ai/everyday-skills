"""Perturbation controls for grading the grader, independent of the twin.

    python evals/perturb.py ~/.twin-corpora/<name>

Takes the owner's real held-out answers (probes.json gold) and makes AI-style
edits of each one. A judge worth trusting prefers the real one almost always.
Writes <corpus>/perturb.json: [{id, kind, reply}]. judge_check.py grades them
with --perturb.

Kinds:
  opener   a stock opener ("Honestly, ...") prepended            (deterministic)
  moral    a generic closing moral appended                      (deterministic)
  polish   same content, rewritten tidy, complete and balanced   (Haiku)
  expand   same content, about twice as long, more detail        (Haiku)
"""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OPENERS = ["Honestly, ", "Honest answer: ", "Fair question. ", "That's a great question. "]
MORALS = [" At the end of the day, it's about staying true to what matters.",
          " Small steps add up, that's what I've learned.",
          " Keep going, it's always worth it in the end.",
          " Just stay honest with yourself and the rest follows."]
ASK = {
    "polish": ("Rewrite this text message so it reads polished: complete grammatical sentences, proper "
               "capitals and punctuation, a clear answer-then-reason shape. Keep the same meaning and "
               "about the same length. Output only the rewritten message.\n\n"),
    "expand": ("Rewrite this text message to be about twice as long: add a reason, an example and a bit "
               "more detail, keeping the same meaning and voice. Output only the rewritten message.\n\n"),
}


def ask(prompt: str) -> str:
    out = subprocess.run(["claude", "-p", "--model", "haiku", "--strict-mcp-config", "--mcp-config",
                          '{"mcpServers":{}}', "--disallowedTools",
                          "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task"],
                         input=prompt, capture_output=True, text=True, timeout=180)
    return out.stdout.strip()


def lower_first(t: str) -> str:
    return t[:1].lower() + t[1:] if t[:1].isupper() and not t[:2].isupper() and not t.startswith("I ") else t


def main() -> int:
    corpus = Path(sys.argv[1]).expanduser()
    probes = json.loads((corpus / "probes.json").read_text(encoding="utf-8"))
    rows = []
    for i, p in enumerate(probes):
        g = p["gold"].strip()
        rows.append({"id": p["id"], "kind": "opener", "reply": OPENERS[i % len(OPENERS)] + lower_first(g)})
        rows.append({"id": p["id"], "kind": "moral", "reply": g.rstrip() + MORALS[i % len(MORALS)]})
    jobs = [(p, k) for p in probes for k in ASK]
    with ThreadPoolExecutor(6) as ex:
        outs = list(ex.map(lambda pk: ask(ASK[pk[1]] + pk[0]["gold"]), jobs))
    rows += [{"id": p["id"], "kind": k, "reply": o} for (p, k), o in zip(jobs, outs) if o]
    (corpus / "perturb.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(corpus.name, len(rows), "perturbations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
