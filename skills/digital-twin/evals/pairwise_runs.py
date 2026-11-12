"""Round vs round, blind and pairwise: which run's replies sound more like a real person?

    python evals/pairwise_runs.py ~/.twin-corpora/<name> c15o c14o

For every conversation both runs had, the blind human-likeness judge
(judge.pair, blind=True: no owner samples, the question the owner answered
when labelling) compares the two, both orders; a verdict counts only if it
survives the swap. This judge agreed best with the owner's own picks
(owner_labels.py), so it is the main naturalness signal for the hill-climb.

Prints the win rate of the first run (ties count half) and writes
runs/<first>/pairwise-<second>.json.
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


def text(convo: list[dict]) -> tuple[str, str]:
    """(their messages, the replies), turn by turn for multi-turn chats."""
    if len(convo) == 1:
        return convo[0]["msg"].split(":\n", 1)[-1], convo[0]["reply"]
    msgs = "\n".join(f"[turn {i}] {t['msg'].split(':' + chr(10), 1)[-1]}" for i, t in enumerate(convo, 1))
    reps = "\n".join(f"[turn {i}] {t['reply']}" for i, t in enumerate(convo, 1))
    return msgs, reps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    corpus = Path(a.corpus).expanduser()
    A = json.loads((corpus / "runs" / a.a / "convos.json").read_text())
    B = json.loads((corpus / "runs" / a.b / "convos.json").read_text())
    ids = [i for i in A if i in B and len(A[i]) == len(B[i])]

    def one(i):
        msg, ra = text(A[i])
        _, rb = text(B[i])
        r = J.pair(msg, "someone", ra, rb, "", a.model, corpus, blind=True)
        win = {"A": a.a, "B": a.b}.get(r["more_natural"], "tie")
        return {"id": i, "winner": win, "flip": r["more_natural_flip"], "why": r["why"]}

    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, ids))
    (corpus / "runs" / a.a / f"pairwise-{a.b}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    pts = [1.0 if r["winner"] == a.a else 0.5 if r["winner"] == "tie" else 0.0 for r in res]
    w = sum(r["winner"] == a.a for r in res)
    l = sum(r["winner"] == a.b for r in res)
    print(f"{corpus.name} {a.a} vs {a.b}: win rate {sum(pts) / len(pts):.2f} "
          f"({w} wins, {l} losses, {len(res) - w - l} ties, {sum(r['flip'] for r in res)} flips)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
