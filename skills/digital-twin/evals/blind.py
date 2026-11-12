"""Blind identification: can a judge tell the twin's reply from the owner's real one?

    python evals/blind.py ~/.twin-corpora/<name> <run> [--model opus]

For every style probe in the run (a message the owner really answered, held
out of the twin's memory), the judge sees the message, the owner's real reply
and the twin's first reply, in random order, and picks the one the owner
actually sent. Each pair is asked twice with the order swapped, so position
bias cancels. The "fooled rate" is the share of answers that picked the twin:
50% means indistinguishable, 0% means always caught.

Independent of the rubric judge: no scores, no rubric, no tool output, so it
does not reward polish or punish brevity. Writes runs/<run>/blind.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import judge as J  # noqa: E402

ASK = """Two replies to the same message. One was written by the real person; the other is an imitation.
Using what you know of how this person really talks (the reference samples), decide which reply the real
person wrote. Judge voice, thinking and texture, not which reply is better or more complete.

=== REFERENCE SAMPLES (the person's real words, other occasions) ===
{samples}

=== THE MESSAGE ===
From {who} ({role}): {msg}

=== REPLY A ===
{a}

=== REPLY B ===
{b}

Answer with JSON only: {{"real": "A" or "B", "why": "one short line"}}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("run")
    ap.add_argument("--model", default="opus")
    a = ap.parse_args()
    corpus = Path(a.corpus).expanduser()
    probes = {p["id"]: p for p in json.loads((corpus / "probes.json").read_text(encoding="utf-8"))}
    convos = json.loads((corpus / "runs" / a.run / "convos.json").read_text(encoding="utf-8"))
    samples = (corpus / "samples.md").read_text(encoding="utf-8")
    jobs = []
    for pid, convo in convos.items():
        p = probes.get(pid)
        if not p or not convo or not p.get("gold"):
            continue
        twin = convo[0]["reply"].strip()
        for twin_first in (True, False):
            jobs.append((pid, p, twin, twin_first))

    def one(job):
        pid, p, twin, twin_first = job
        ra, rb = (twin, p["gold"]) if twin_first else (p["gold"], twin)
        prompt = ASK.format(samples=samples, who=p["from"]["name"], role=p["from"]["role"],
                            msg=p["turns"][0], a=ra, b=rb)
        for _ in range(2):
            out = J._ask(prompt, a.model, corpus)
            m = re.search(r'"real"\s*:\s*"([AB])"', out or "")
            if m:
                picked_twin = (m.group(1) == "A") == twin_first
                why = re.search(r'"why"\s*:\s*"(.*?)"', out or "")
                return {"id": pid, "twin_first": twin_first, "picked_twin": picked_twin,
                        "why": why.group(1) if why else ""}
        return {"id": pid, "twin_first": twin_first, "error": True}

    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, jobs))
    ok = [r for r in res if "picked_twin" in r]
    rate = sum(r["picked_twin"] for r in ok) / len(ok) if ok else 0.0
    out = {"run": a.run, "pairs": len(ok) // 2, "answers": len(ok), "fooled_rate": round(rate, 3), "rows": res}
    (corpus / "runs" / a.run / "blind.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{corpus.name} {a.run}: fooled {rate:.0%} of {len(ok)} answers ({len(ok) // 2} probes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
