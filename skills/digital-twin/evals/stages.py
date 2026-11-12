"""The hill-climbing loop, in three stages, for one corpus and one round.

    python evals/stages.py --corpus ~/.twin-corpora/<name> --suite founder --round 3 [--stages twin,manager,e2e]

1. twin    The twin (Haiku) on the RIGHT data: a brain built by a strong
           manager and a strong simulated owner (Opus). If replies are weak
           here, the twin, its tools or its skill are the problem.
2. manager The brain built by the Haiku manager, audited (brain_audit.py)
           against the strong brain and the dossier: what the twin needs but
           the manager did not collect or ask for.
3. e2e     Haiku manager + Haiku twin from scratch, the real setup.

Stage 1 writes runs/c<round>o, stage 3 writes runs/c<round>h. Stage 2 audits
both brains. A summary is printed and written to runs/stages-<round>.md.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = str(HERE.parent / ".venv" / "bin" / "python")
SCORES = ("knowledge_accuracy", "persona_fidelity", "naturalness")
BRAIN = ("life_coverage", "accuracy", "voice_quality", "soul_quality", "privacy")


def run(args: list[str], log: Path) -> None:
    with log.open("w") as f:
        subprocess.run([PY, *args], cwd=HERE, stdout=f, stderr=subprocess.STDOUT)


def chat_scores(run_dir: Path) -> dict:
    p = run_dir / "judged.json"
    if not p.exists():
        return {}
    rows = json.loads(p.read_text())
    out = {}
    for k in SCORES:
        v = [r["judge"][k] for r in rows if isinstance(r.get("judge", {}).get(k), (int, float))]
        out[k] = round(sum(v) / len(v), 2) if v else None
    out["fabrications"] = sum(len(r["judge"].get("fabrications") or []) for r in rows)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--suite", required=True)
    ap.add_argument("--round", required=True)
    ap.add_argument("--stages", default="twin,manager,e2e")
    ap.add_argument("--questions", type=int, default=40)
    ap.add_argument("--interrogate", type=int, default=0)
    ap.add_argument("--owner-noise", type=float, default=0.0)
    a = ap.parse_args()
    corpus = Path(a.corpus).expanduser()
    stages = set(a.stages.split(","))
    base = ["run_convo.py", "--corpus", str(corpus), "--suite", a.suite, "--questions", str(a.questions),
            "--interrogate", str(a.interrogate), "--owner-noise", str(a.owner_noise)]
    jobs = []
    if "twin" in stages:
        jobs.append((base + ["--round", f"{a.round}o", "--manager-model", "opus", "--owner-model", "opus"],
                     corpus / f"c{a.round}o.log"))
    if "e2e" in stages:
        jobs.append((base + ["--round", f"{a.round}h", "--owner-model", "opus"], corpus / f"c{a.round}h.log"))
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(lambda j: run(*j), jobs))

    lines = [f"# Round {a.round}: {corpus.name}", "",
             "| stage | brain by | knowledge | persona | natural | fabrications |", "|---|---|---|---|---|---|"]
    for tag, who in (("o", "Opus manager (right data)"), ("h", "Haiku manager (e2e)")):
        s = chat_scores(corpus / "runs" / f"c{a.round}{tag}")
        if s:
            lines.append(f"| {'twin' if tag == 'o' else 'e2e'} | {who} | " + " | ".join(
                str(s[k]) for k in SCORES) + f" | {s['fabrications']} |")
    led = []
    for tag in ("o", "h"):
        if (corpus / "runs" / f"c{a.round}{tag}" / "brain").exists():
            r = subprocess.run([PY, "ledger.py", "--corpus", str(corpus), "--run", f"c{a.round}{tag}"],
                               cwd=HERE, capture_output=True, text=True)
            led.append(f"- {r.stdout.strip() or r.stderr.strip()[-200:]}")
    if led:
        lines += ["", "Data ledger:", *led]
    if "manager" in stages:
        lines += ["", "| brain | persona | " + " | ".join(BRAIN) + " | examples | opinions | stories |",
                  "|---|---|" + "---|" * (len(BRAIN) + 3)]
        for tag, who in (("o", "Opus"), ("h", "Haiku")):
            b = corpus / "runs" / f"c{a.round}{tag}" / "brain"
            if not b.exists():
                continue
            outp = b.parent / "brain_audit.json"
            run(["brain_audit.py", "--corpus", str(corpus), "--brain", str(b), "--out", str(outp)],
                b.parent / "brain_audit.log")
            if outp.exists():
                for p, r in json.loads(outp.read_text()).items():
                    j, f = r["judge"], r["features"]
                    lines.append(f"| {who} | {p} | " + " | ".join(str(j.get(k)) for k in BRAIN)
                                 + f" | {f['examples']} | {f['opinions']} | {f['stories']} |")
    md = "\n".join(lines)
    (corpus / "runs" / f"stages-{a.round}.md").write_text(md + "\n", encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
