"""Conversation-fidelity round: ingest (or reuse a brain), chat, judge, report.

    python evals/run_convo.py --corpus ~/.twin-corpora/<name> --suite public_figure --round 0
        [--reuse-brain <TWIN_HOME>] [--only id,id] [--jobs 4] [--no-probes]

Scenarios: evals/scenarios/<suite>.json plus <corpus>/probes.json (style probes)
and <corpus>/scenarios.json if present (corpus-specific additions).
Writes <corpus>/runs/c<round>/{convos.json, judged.json, report.md}.

Scores are reported separately and never blended:
knowledge_accuracy, persona_fidelity, naturalness (Opus judge, 1-5), plus
deterministic tells (dont_know, assistant_phrasing, meta_leak, markdown) and
whether the twin used ask_owner when it deferred.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import converse as C  # noqa: E402
import judge as J  # noqa: E402
import run_round as R  # noqa: E402
import tells as T  # noqa: E402

SCORES = ("knowledge_accuracy", "persona_fidelity", "naturalness", "tone_read")


def load_scenarios(corpus: Path, suite: str, probes: bool) -> list[dict]:
    """suite: one name or several, comma-separated ("human,tone")."""
    out = []
    for name in suite.split(","):
        out += json.loads((HERE / "scenarios" / f"{name}.json").read_text(encoding="utf-8"))["scenarios"]
        extra = corpus / f"scenarios-{name}.json"
        if extra.exists():
            out += json.loads(extra.read_text(encoding="utf-8"))["scenarios"]
    if (corpus / "scenarios.json").exists():
        out += json.loads((corpus / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    if probes and (corpus / "probes.json").exists():
        out += json.loads((corpus / "probes.json").read_text(encoding="utf-8"))
    return out


def persona_rules(personas: dict) -> dict:
    return {k: f"audience: {v['audience']}\nmay know: {v['include']}\nmust NOT know: {v['exclude']}"
            for k, v in personas.items() if k != "approve"}


LAUGH = T.re.compile(r"\b(ha(ha)+|lol|lmao|hehe)\b|[\U0001F602\U0001F923\U0001F606\U0001F604\U0001F605]", T.re.I)
CLOSE = {"casual": {"casual", "warm", "brief", "playful"}, "brief": {"brief", "casual", "warm"},
         "warm": {"warm", "casual", "brief", "excited"}, "excited": {"excited", "warm", "playful"},
         "serious": {"serious", "warm"}, "thoughtful": {"thoughtful", "casual", "professional"},
         "professional": {"professional"}, "playful": {"playful", "casual"}}


def mood_report(judged: list[dict]) -> str:
    """Does the twin's mood move with the chat? Expected per-turn modes (scenario 'modes') against the
    judge's label of each reply; the mix of moods; how often it laughs."""
    exp_n = hit = 0
    mix: dict[str, int] = {}
    miss = []
    for r in judged:
        got = [str(m).lower().strip() for m in (r.get("judge", {}).get("modes") or [])]
        for m in got:
            mix[m] = mix.get(m, 0) + 1
        for i, want in enumerate(r.get("modes") or []):
            if i < len(got):
                exp_n += 1
                ok = got[i] in CLOSE.get(want, {want})
                hit += ok
                if not ok:
                    miss.append(f"{r['id']} t{i + 1}: wanted {want}, got {got[i]}")
    reps = [t["reply"] for r in judged for t in r["convo"]]
    laugh = sum(bool(LAUGH.search(x)) for x in reps)
    out = [f"Mood match: {hit}/{exp_n}" if exp_n else "Mood match: -",
           "Mood mix: " + ", ".join(f"{k} {v}" for k, v in sorted(mix.items(), key=lambda x: -x[1])),
           f"Laughs (haha/lol/😂 in a reply): {laugh}/{len(reps)}"]
    return "\n".join(out + ([f"- {m}" for m in miss] if miss else []))


def report(judged: list[dict]) -> str:
    def avg(rows, k):
        v = [r["judge"][k] for r in rows if isinstance(r.get("judge", {}).get(k), (int, float))]
        return f"{st.mean(v):.2f}" if v else "-"

    def tell_rate(rows, k):
        reps = [t for r in rows for t in r["tells"]]
        return f"{sum(t[k] for t in reps)}/{len(reps)}" if reps else "-"

    lines = ["| group | n | knowledge | persona | natural | tone | dont_know | assistant | meta | markdown | words |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    groups: dict[str, list] = {"ALL": judged}
    for r in judged:
        for t in r["type"]:
            groups.setdefault(t, []).append(r)
    for g, rows in groups.items():
        w = [n for r in rows for n in r["words"]]
        lines.append(f"| {g} | {len(rows)} | " + " | ".join(avg(rows, k) for k in SCORES) + " | "
                     + " | ".join(tell_rate(rows, k) for k in ("dont_know", "assistant_phrasing",
                                                              "meta_leak", "markdown"))
                     + f" | {st.median(w) if w else '-'} |")
    lines += ["", mood_report(judged)]
    fab = [(r["id"], f) for r in judged for f in r.get("judge", {}).get("fabrications", []) or []]
    leaks = [(r["id"], f) for r in judged for f in r.get("judge", {}).get("leaks", []) or []]
    lines += ["", f"Fabrications: {len(fab)}"] + [f"- {i}: {f}" for i, f in fab]
    lines += ["", f"Leaks: {len(leaks)}"] + [f"- {i}: {f}" for i, f in leaks]
    lines += ["", "## Per scenario", ""]
    for r in judged:
        j = r.get("judge", {})
        lines.append(f"### {r['id']} K{j.get('knowledge_accuracy')} P{j.get('persona_fidelity')} "
                     f"N{j.get('naturalness')} T{j.get('tone_read')}  ({', '.join(r['type'])}; {r['persona']})")
        for t in r["convo"]:
            lines.append(f"> {t['msg']}\n\n{t['reply']}\n\n`tools: {', '.join(c['name'] for c in t['calls'])}`")
        lines.append(f"\n*Judge:* {j.get('summary', j.get('error'))}\n")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--suite", required=True)
    ap.add_argument("--round", required=True, help="round tag, e.g. 3 or 3o")
    ap.add_argument("--reuse-brain")
    ap.add_argument("--only")
    ap.add_argument("--no-probes", action="store_true")
    ap.add_argument("--rejudge", action="store_true", help="re-judge an existing round's convos.json")
    ap.add_argument("--missing", action="store_true",
                    help="with --rejudge: only judge chats with no current-version score (saves calls)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--revoice", action="store_true",
                    help="with --reuse-brain: have the manager rewrite every persona's voice and soul "
                         "from the stored real messages first (tests voice extraction)")
    ap.add_argument("--twin-model", default="haiku")
    ap.add_argument("--judge-model", default="opus")
    ap.add_argument("--judge-batch", type=int, default=5,
                    help="conversations per judge call; shared context is sent once per batch (1 = old way)")
    # ingest options (same as run_round)
    ap.add_argument("--pii", default="~/.twin-corpora/pii/pii.jsonl")
    ap.add_argument("--manager-model", default="haiku")
    ap.add_argument("--owner-model", default="haiku")
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--pii-per-batch", type=int, default=2)
    ap.add_argument("--questions", type=int, default=20)
    ap.add_argument("--interrogate", type=int, default=0,
                    help="after the sources, keep asking the owner until this many answers in all")
    ap.add_argument("--owner-noise", type=float, default=0.0,
                    help="share of owner answers that are lazy, garbage, skipped, rambling or typos")
    a = ap.parse_args()

    corpus = Path(a.corpus).expanduser()
    run = corpus / "runs" / f"c{a.round}"
    personas = json.loads((HERE / "personas.json").read_text(encoding="utf-8"))
    meta = json.loads((corpus / "meta.json").read_text(encoding="utf-8"))
    if a.rejudge:
        brain = run / "brain"
        env = None
    elif a.reuse_brain:
        src = Path(a.reuse_brain).expanduser()
        if run.exists() and src.resolve() != (run / "brain").resolve():
            shutil.rmtree(run)
        if src.resolve() != (run / "brain").resolve():
            run.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, run / "brain", dirs_exist_ok=True)
        brain = run / "brain"
        env = {**os.environ, "TWIN_HOME": str(brain)}
        R.cli(env, "rebuild")  # persona files from the current build code
        if a.revoice:
            R.manager(env, "Rewrite the voice and soul of every persona from my real messages, "
                           "following your skill, then sync.", a.manager_model, run / "revoice.jsonl")
    else:
        brain = run / "brain"
        env = {**os.environ, "TWIN_HOME": str(brain)}
        R.ingest(corpus, run, env, a, personas, meta, run / "transcript.jsonl")

    scns = load_scenarios(corpus, a.suite, not a.no_probes)
    if a.only:
        keep = set(a.only.split(","))
        scns = [s for s in scns if s["id"] in keep]
    dossier = (corpus / "dossier.md").read_text(encoding="utf-8")
    samples = (corpus / "samples.md").read_text(encoding="utf-8") if (corpus / "samples.md").exists() else ""
    rules = persona_rules(personas)

    convos: dict[str, list] = {}
    if a.rejudge:
        convos = json.loads((run / "convos.json").read_text(encoding="utf-8"))
        scns = [s for s in scns if s["id"] in convos]
        old = run / "judged.json"
        kept = {}
        if old.exists() and a.missing:
            kept = {r["id"]: r for r in json.loads(old.read_text())
                    if r["judge"].get("judge_version") == J.JUDGE_VERSION and "error" not in r["judge"]}
        elif old.exists():
            old.replace(run / f"judged.v{json.loads(old.read_text())[0]['judge'].get('judge_version', 1)}.json")
    for persona in ([] if a.rejudge else sorted({s["persona"] for s in scns})):
        R.cli(env, "set-active", persona)
        group = [s for s in scns if s["persona"] == persona]
        with ThreadPoolExecutor(a.jobs) as ex:
            for s, c in zip(group, ex.map(lambda s: C.converse(env, s["from"]["name"], s["turns"],
                                                                  a.twin_model), group)):
                convos[s["id"]] = c
    if not a.rejudge:
        (run / "convos.json").write_text(json.dumps(convos, indent=1, ensure_ascii=False), encoding="utf-8")

    if not a.rejudge:
        kept = {}

    todo = [s for s in scns if s["id"] not in kept]
    batches = [todo[i:i + max(1, a.judge_batch)] for i in range(0, len(todo), max(1, a.judge_batch))]
    verdicts: dict[str, dict] = {}

    def one_batch(group):
        if a.judge_batch <= 1:
            s = group[0]
            return {s["id"]: J.judge(s, convos[s["id"]], dossier, samples, rules[s["persona"]],
                                     a.judge_model, run, s.get("gold"))}
        return J.judge_batch([(s, convos[s["id"]]) for s in group], dossier, samples, rules,
                             a.judge_model, run)
    with ThreadPoolExecutor(a.jobs) as ex:
        for v in ex.map(one_batch, batches):
            verdicts.update(v)

    def row(s):
        if s["id"] in kept:
            return kept[s["id"]]
        c = convos[s["id"]]
        return {"id": s["id"], "type": s["type"], "persona": s["persona"], "modes": s.get("modes"),
                "convo": c, "judge": verdicts[s["id"]],
                "tells": [T.tells(t["reply"]) for t in c], "words": [T.words(t["reply"]) for t in c],
                "asked_owner": any(x["name"] == "ask_owner" for t in c for x in t["calls"])}
    judged = [row(s) for s in scns]
    (run / "judged.json").write_text(json.dumps(judged, indent=1, ensure_ascii=False), encoding="utf-8")
    md = report(judged)
    (run / "report.md").write_text(md, encoding="utf-8")
    print(md.split("## Per scenario")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
