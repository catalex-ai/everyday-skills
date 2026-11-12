"""Does the judge tell the owner from the twin? Run before trusting a judge change.

    python evals/judge_check.py ~/.twin-corpora/<name> c7o c12o [--tag v5]

For each held-out probe, the judge grades the owner's REAL answer and each
run's twin reply to the same message (same rubric, same samples). A judge we
can hill-climb on must:

- score real answers high on persona and naturalness;
- score the twin below the real answer most of the time (pair accuracy: the
  share of probes where real > twin, ties count half);
- agree with the blind pairwise test (runs.../blind.json) on which runs are
  closer to the owner.

Writes <corpus>/judge-check-<tag>.json and prints a table.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import judge as J  # noqa: E402
import run_convo as RC  # noqa: E402

KEYS = ("persona_fidelity", "naturalness")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("runs", nargs="*")
    ap.add_argument("--tag", default=f"v{J.JUDGE_VERSION}")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--perturb", action="store_true",
                    help="also grade perturb.json (AI-style edits of the real answers); twin-independent")
    ap.add_argument("--out", default="", help="output name suffix (default: the tag)")
    a = ap.parse_args()
    corpus = Path(a.corpus).expanduser()
    personas = json.loads((HERE / "personas.json").read_text(encoding="utf-8"))
    rules = RC.persona_rules(personas)
    probes = json.loads((corpus / "probes.json").read_text(encoding="utf-8"))
    dossier = (corpus / "dossier.md").read_text(encoding="utf-8")
    samples = (corpus / "samples.md").read_text(encoding="utf-8")
    convos = {r: json.loads((corpus / "runs" / r / "convos.json").read_text()) for r in a.runs}
    names = list(a.runs)
    if a.perturb:
        for x in json.loads((corpus / "perturb.json").read_text(encoding="utf-8")):
            p = next(q for q in probes if q["id"] == x["id"])
            convos.setdefault("p:" + x["kind"], {})[x["id"]] = [
                {"msg": f"Message from {p['from']['name']}:\n{p['turns'][0]}", "reply": x["reply"],
                 "tool_text": "(the reply's facts are all in memory)"}]
        names += sorted(k for k in convos if k.startswith("p:"))
    out = corpus / f"judge-check-{a.out or a.tag}.json"
    done = {}
    if out.exists():  # resume: keep grades already made with this tag
        for r in json.loads(out.read_text()):
            if "error" not in r:
                done[(r["who"], r["id"])] = r

    jobs = []
    for p in probes:
        jobs.append(("real", p, [{"msg": f"Message from {p['from']['name']}:\n{p['turns'][0]}",
                                  "reply": p["gold"], "tool_text": "(the reply's facts are all in memory)"}]))
        for r in names:
            c = convos[r].get(p["id"])
            if c:
                jobs.append((r, p, c))
    jobs = [j for j in jobs if (j[0], j[1]["id"]) not in done]

    def one(job):
        who, p, convo = job
        scn = {**p, "expect": "Answer as the owner would."}
        j = J.judge(scn, convo, dossier, samples, rules[p["persona"]], "opus", corpus, gold=None)
        return {"who": who, "id": p["id"], "reply": convo[0]["reply"], **j}

    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(done.values()) + list(ex.map(one, jobs))
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")

    by = {}
    for r in res:
        by.setdefault(r["who"], {})[r["id"]] = r
    print(f"{corpus.name} judge {a.tag}")
    print("who      | persona | natural | words | pair acc P | pair acc N")
    for who in ["real", *names]:
        rows = by.get(who, {})
        m = {k: st.mean([x[k] for x in rows.values() if isinstance(x.get(k), (int, float))] or [0]) for k in KEYS}
        w = st.median([len(x["reply"].split()) for x in rows.values()] or [0])
        acc = {}
        if who != "real":
            for k in KEYS:
                pts = []
                for i, x in rows.items():
                    g = by["real"].get(i, {}).get(k)
                    t = x.get(k)
                    if isinstance(g, (int, float)) and isinstance(t, (int, float)):
                        pts.append(1.0 if g > t else 0.5 if g == t else 0.0)
                acc[k] = f"{st.mean(pts):.2f}" if pts else "-"
        print(f"{who:8} | {m['persona_fidelity']:.2f}    | {m['naturalness']:.2f}    | {w:5.0f} | "
              f"{acc.get('persona_fidelity', '-'):10} | {acc.get('naturalness', '-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
