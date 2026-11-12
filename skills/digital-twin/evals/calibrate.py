"""Judge calibration: score the owner's REAL held-out answers as if the twin wrote them.

    python evals/calibrate.py ~/.twin-corpora/<name>

If real answers do not score near 5 on persona and naturalness, the judge
(or the reference samples) is mis-calibrated, and twin scores against it are
not trustworthy. Knowledge is reported but means little here (no tool output).
"""
from __future__ import annotations

import json
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import judge as J  # noqa: E402
import run_convo as RC  # noqa: E402


def main() -> int:
    corpus = Path(sys.argv[1]).expanduser()
    from_run = sys.argv[2] if len(sys.argv) > 2 else None  # e.g. c0: grade that run's twin replies instead
    personas = json.loads((HERE / "personas.json").read_text(encoding="utf-8"))
    rules = RC.persona_rules(personas)
    probes = json.loads((corpus / "probes.json").read_text(encoding="utf-8"))
    dossier = (corpus / "dossier.md").read_text(encoding="utf-8")
    samples = (corpus / "samples.md").read_text(encoding="utf-8")

    runs = json.loads((corpus / "runs" / from_run / "convos.json").read_text()) if from_run else {}

    def one(p):
        if from_run:
            convo = runs.get(p["id"])
            if not convo:
                return {}
        else:
            convo = [{"msg": f"Message from {p['from']['name']}:\n{p['turns'][0]}", "reply": p["gold"],
                      "tool_text": "(the reply's facts are all in memory)"}]
        scn = {**p, "expect": "Answer as the owner would."}
        return J.judge(scn, convo, dossier, samples, rules[p["persona"]], "opus", corpus, gold=None)

    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, probes))
    for k in ("knowledge_accuracy", "persona_fidelity", "naturalness"):
        v = [r[k] for r in res if isinstance(r.get(k), (int, float))]
        print(f"{k}: {st.mean(v):.2f}  {sorted(v)}")
    for p, r in zip(probes, res):
        if r.get("persona_fidelity", 5) <= 3 or r.get("naturalness", 5) <= 3:
            print(f"- {p['id']} P{r.get('persona_fidelity')} N{r.get('naturalness')}: {r.get('summary', '')[:200]}")
    (corpus / f"calibration{'-' + from_run if from_run else ''}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
