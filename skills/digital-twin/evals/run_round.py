"""Run one hill-climbing round end to end.

    python evals/run_round.py --corpus ~/.twin-corpora/subject-a --round 0

1. fresh brain in <corpus>/runs/r<N>/brain
2. the twin manager (claude -p, manager-agent/) creates the eval personas
3. sources are fed in batches, with PII probe notes mixed in
4. after each batch the manager's open questions go to the simulated owner,
   and the answers go back to the manager
5. every QA item is asked of the twin (claude -p, twin-agent/) once per persona
6. results.json is written and scored with evals/score.py

The subject's name is read from <corpus>/meta.json at run time only.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
PY = str(PKG / ".venv" / "bin" / "python")
sys.path.insert(0, str(HERE))
import simulate_owner  # noqa: E402


def cli(env, *args) -> dict:
    out = subprocess.run([PY, "-m", "brainkit.cli", *args], cwd=PKG, env=env,
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"error": out.stderr[-500:] or out.stdout[-500:]}


def manager(env, msg: str, model: str, log: Path) -> str:
    t = time.time()
    out = subprocess.run(
        ["claude", "-p", "--model", model, "--strict-mcp-config", "--mcp-config", ".mcp.json",
         "--permission-mode", "bypassPermissions", "--output-format", "json"],
        input=msg, cwd=PKG / "manager-agent", env=env, capture_output=True, text=True, timeout=1800)
    try:
        j = json.loads(out.stdout)
        text, usage = j.get("result", ""), j.get("usage", {})
        cost = j.get("total_cost_usd")
    except json.JSONDecodeError:
        text, usage, cost = out.stdout[-2000:] + out.stderr[-2000:], {}, None
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"to": "manager", "msg": msg, "reply": text, "secs": round(time.time() - t),
                            "usage": usage, "cost": cost}, ensure_ascii=False) + "\n")
    return text


_KEEP = [("Tell me about", "\x01"), ("Remind me of", "\x02"), ("Tell me", "\x03"),
         ("I would like", "\x04"), ("I want", "\x05"), ("I need", "\x06")]
_SECOND = [(r"\bam I\b", "are you"), (r"\bI am\b", "you are"), (r"\bI'm\b", "you're"),
           (r"\bI was\b", "you were"), (r"\bwas I\b", "were you"), (r"\bI\b", "you"),
           (r"\bmyself\b", "yourself"), (r"\bmine\b", "yours"), (r"\bmy\b", "your"),
           (r"\bme\b", "you")]


def second_person(q: str) -> str:
    """Others talk to the twin, so they say "your", not "my"."""
    for k, v in _KEEP:
        q = re.sub(r"\b" + k + r"\b", v, q, flags=re.I)
    for pat, rep in _SECOND:
        q = re.sub(pat, rep, q, flags=0 if pat == r"\bI\b" else re.I)
    for k, v in _KEEP:
        q = q.replace(v, "Tell me" if k == "Remind me of" else k)
    return q[:1].upper() + q[1:]


def twin(env, q: str, model: str) -> tuple[str, str]:
    q = second_person(q)
    out = subprocess.run(
        ["claude", "-p", "--model", model, "--strict-mcp-config", "--mcp-config", ".mcp.json",
         "--output-format", "stream-json", "--verbose", "--allowedTools", "mcp__twin-read__*"],
        input=q, cwd=PKG / "twin-agent", env=env, capture_output=True, text=True, timeout=300)
    reply, tools = "", []
    for line in out.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            reply = ev.get("result", "")
        if ev.get("type") == "user":
            for c in ev.get("message", {}).get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    body = c.get("content")
                    if isinstance(body, list):
                        body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                    tools.append(str(body))
    return reply, "\n".join(tools)


def owner_round(corpus: Path, run: Path, env: dict, a, log: Path, n: int,
                interview: bool = False) -> int:
    """The manager's next n questions go to the simulated owner; answers go back. Returns count."""
    qs = cli(env, "next", str(n))
    qs = qs if isinstance(qs, list) else qs.get("questions", [])
    if not qs:
        if interview:
            manager(env, "I have a few minutes. Ask me more 'how would you reply?' questions: queue "
                         "some with ask_reply for the people in my life you have the fewest real "
                         "messages for.", a.manager_model, log)
        return 0
    answers = []
    for q in qs:
        ans = simulate_owner.answer(q, corpus, a.owner_model, cwd=run,
                                    noise_rate=getattr(a, "owner_noise", 0.0))
        answers.append(f"[{q.get('id')}] {q.get('text')}\nMy answer: {ans}")
    tail = ("\n\nFile each, then queue a follow-up 'how would you reply?' for each reply "
            "question I answered." if interview else "")
    manager(env, "Here are my answers to your questions:\n\n" + "\n\n".join(answers) + tail,
            a.manager_model, log)
    return len(qs)


def ingest(corpus: Path, run: Path, env: dict, a, personas: dict, meta: dict, log: Path) -> None:
    """Fresh brain, personas, sources in batches with PII notes, owner Q&A, tidy."""
    if run.exists():
        shutil.rmtree(run)
    (run / "notes").mkdir(parents=True)
    cli(env, "init")
    pdesc = "\n".join(f"- slug '{k}': audience: {v['audience']} include: {v['include']} "
                      f"exclude: {v['exclude']}" for k, v in personas.items() if k != "approve")
    manager(env, "Set up my twin. Create these two personas exactly with these slugs, "
                 f"and make 'professional' the active one:\n{pdesc}", a.manager_model, log)

    pii = [json.loads(l) for l in Path(a.pii).expanduser().read_text().splitlines() if l.strip()]
    sources = sorted((corpus / "sources").glob("*.txt"))
    asked = 0
    for bi in range(0, len(sources), a.batch):
        files = [str(p) for p in sources[bi:bi + a.batch]]
        for k in range(a.pii_per_batch):
            if pii:
                row = pii.pop(0)
                note = run / "notes" / f"note-{bi:02d}-{k}.txt"
                note.write_text("A note I saved:\n" + row["text"], encoding="utf-8")
                files.append(str(note))
        manager(env,
                f"Add these files to my brain. The documents that describe me call me "
                f"'{meta['label']}'; I am the owner, so file facts about that person as facts "
                f"about me (about='me', first person). Other documents are background on people, "
                f"places and organisations in my life: keep only what relates to me or to people "
                f"and organisations connected to me.\nFiles:\n" + "\n".join(files),
                a.manager_model, log)
        if asked < a.questions:
            asked += owner_round(corpus, run, env, a, log, 3)
    # Interrogation: the owner sits with the manager and answers until done.
    idle = 0
    while asked < getattr(a, "interrogate", 0) and idle < 2:
        n = owner_round(corpus, run, env, a, log, 4, interview=True)
        asked += n
        idle = idle + 1 if n == 0 else 0
    manager(env, "Tidy up and sync everything, then tell me the status in two lines.",
            a.manager_model, log)



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--pii", default="~/.twin-corpora/pii/pii.jsonl")
    ap.add_argument("--manager-model", default="haiku")
    ap.add_argument("--twin-model", default="haiku")
    ap.add_argument("--owner-model", default="haiku")
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--pii-per-batch", type=int, default=2)
    ap.add_argument("--questions", type=int, default=20, help="max owner questions answered")
    ap.add_argument("--interrogate", type=int, default=0,
                    help="after the sources, keep asking the owner until this many answers in all")
    ap.add_argument("--owner-noise", type=float, default=0.0,
                    help="share of owner answers that are lazy, garbage, skipped, rambling or typos")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--qa-only", action="store_true", help="reuse the brain, re-run QA only")
    a = ap.parse_args()

    corpus = Path(a.corpus).expanduser()
    run = corpus / "runs" / f"r{a.round}"
    brain = run / "brain"
    env = {**os.environ, "TWIN_HOME": str(brain)}
    log = run / "transcript.jsonl"
    meta = json.loads((corpus / "meta.json").read_text(encoding="utf-8"))
    personas = json.loads((HERE / "personas.json").read_text(encoding="utf-8"))

    if not a.qa_only:
        ingest(corpus, run, env, a, personas, meta, log)

    qa = json.loads((corpus / "qa.json").read_text(encoding="utf-8"))
    results = []
    for persona in [p for p in personas if p != "approve"]:
        cli(env, "set-active", persona)
        def one(item):
            reply, tools = twin(env, item["q"], a.twin_model)
            return {"qa_id": item["id"], "persona": persona, "q": item["q"], "kind": item["kind"],
                    "cls": item.get("cls"), "must": item["must"], "should_know": item["should_know"],
                    "must_not_know": item["must_not_know"], "reply": reply, "tool_text": tools}
        with ThreadPoolExecutor(a.jobs) as ex:
            results += list(ex.map(one, qa))
    res = run / "results.json"
    res.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    subprocess.run([PY, str(HERE / "score.py"), str(res), "--brain", str(brain),
                    "--pii", str(Path(a.pii).expanduser()), "--questions", str(brain / "questions.json")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
