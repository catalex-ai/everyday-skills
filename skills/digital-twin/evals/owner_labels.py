"""Grade the grader against the owner's own picks.

    python evals/owner_labels.py ~/.twin-corpora/owner-labels.json [--absolute]

The labels file holds pairs the owner judged blind: [{n, corpus, id, msg,
x: [source, reply], y: [source, reply], owner_pick: source | "neither"}].
For each pair the pairwise judge (judge.pair, both orders) picks the more
natural reply; with --absolute the 1-5 judge also scores each reply alone.
Prints agreement on the pairs where the owner chose a side (ties count half),
and the swap-flip rate. A judge is fit for hill-climbing only if it agrees with
the owner clearly above chance (aim: 0.75+).
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import judge as J  # noqa: E402
import run_convo as RC  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("labels")
    ap.add_argument("--absolute", action="store_true")
    ap.add_argument("--blind", action="store_true", help="plain human-likeness question, no owner samples")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    path = Path(a.labels).expanduser()
    labels = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent
    samples = {c: (root / c / "samples.md").read_text(encoding="utf-8") for c in {q["corpus"] for q in labels}}

    def one(q):
        r = J.pair(q["msg"], "someone", q["x"][1], q["y"][1], samples[q["corpus"]], a.model, root / q["corpus"],
                   blind=a.blind)
        pick = {"A": q["x"][0], "B": q["y"][0]}.get(r["more_natural"], "tie")
        out = {"n": q["n"], "owner": q["owner_pick"], "judge": pick, "flip": r["more_natural_flip"], "why": r["why"]}
        if a.absolute:
            personas = json.loads((HERE / "personas.json").read_text(encoding="utf-8"))
            rule = RC.persona_rules(personas)["professional"]
            scn = {"from": {"name": "someone", "role": "contact"}, "type": ["casual"],
                   "expect": "Answer as the owner would."}
            n = {}
            for src, text in (q["x"], q["y"]):
                j = J.judge(scn, [{"msg": q["msg"], "reply": text, "tool_text": "(not shown)"}],
                            "(not used for this check)", samples[q["corpus"]], rule, "opus", root / q["corpus"])
                n[src] = j.get("naturalness")
            (s1, v1), (s2, v2) = list(n.items())
            out["absolute"] = s1 if (v1 or 0) > (v2 or 0) else s2 if (v2 or 0) > (v1 or 0) else "tie"
        return out

    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, labels))
    (root / f"owner-labels-check-v{J.JUDGE_VERSION}{'-blind' if a.blind else ''}-{a.model}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

    def agree(key):
        pts = [1.0 if r[key] == r["owner"] else 0.5 if r[key] == "tie" else 0.0
               for r in res if r["owner"] != "neither" and key in r]
        return sum(pts) / len(pts) if pts else float("nan"), len(pts)
    for key in ("judge", "absolute"):
        if any(key in r for r in res):
            v, n = agree(key)
            print(f"{key:8} agreement with owner: {v:.2f} on {n} pairs")
    print(f"pairwise swap flips: {sum(r['flip'] for r in res)}/{len(res)}")
    for r in res:
        if r["owner"] != "neither" and r["judge"] not in (r["owner"], "tie"):
            print(f"- pair {r['n']}: owner {r['owner']}, judge {r['judge']}: {r['why'][0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
