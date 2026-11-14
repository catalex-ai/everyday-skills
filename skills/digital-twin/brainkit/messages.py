"""Turn a chat export or an interview transcript into the owner's real messages,
each paired with what the other person said just before.

Deterministic, so a small manager model does not have to file messages by hand
(and lose the pairs). Formats, one speaker line each, continuation lines allowed:

    [03/10/2026, 22:41] Dev: oi founder. alive?        (WhatsApp, bracketed)
    03/10/2026, 22:41 - Dev: oi founder. alive?        (WhatsApp, dashed)
    Dev: oi founder. alive?                            (plain transcript)
    Asked: why did you start?  /  Me: ...              (interview notes)
    Q: ... / A: ...                                    (Q&A)

Consecutive lines from the owner become one message (a burst, newline-joined).
"""
from __future__ import annotations

import re

LINE = re.compile(
    r"^\s*(?:\[(?P<ts1>[^\]]{6,40})\]\s*|(?P<ts2>\d{1,4}[/.-]\d{1,2}[/.-]\d{2,4},?\s+\d{1,2}:\d{2}"
    r"(?::\d{2})?\s*(?:[ap]\.?m\.?)?)\s*[-–]\s*)?(?P<who>[^:\n]{1,40}?):\s(?P<text>.*)$", re.I)
QA_THEM = {"asked", "q", "question", "interviewer", "host"}
QA_ME = {"me", "a", "answer"}
SKIP = re.compile(r"^(<media omitted>|this message was deleted|missed (voice|video) call|"
                  r"messages and calls are end-to-end encrypted)", re.I)


def parse(text: str) -> list[tuple[str, str]]:
    """[(speaker, text)] in order; continuation lines join the previous turn."""
    return [(w, t) for w, t, _ in parse_dated(text)]


def parse_dated(text: str) -> list[tuple[str, str, str]]:
    """[(speaker, text, day)]: day is the date part of the timestamp, "" when there is none."""
    turns: list[list[str]] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = LINE.match(line)
        if m and len(m.group("who").split()) <= 5:
            t = m.group("text").strip()
            if SKIP.match(t):
                continue
            ts = (m.group("ts1") or m.group("ts2") or "").strip()
            turns.append([m.group("who").strip(), t, re.split(r"[,\s]", ts, maxsplit=1)[0] if ts else ""])
        elif turns:
            turns[-1][1] += "\n" + line.strip()
    return [(w, t, d) for w, t, d in turns]


def _is_me(who: str, me: set[str]) -> bool:
    w = who.lower().strip()
    return w in me or w in QA_ME or any(w == m.split()[0] for m in me if m)


def pairs(text: str, me: str, max_context: int = 160, thread: int = 2) -> list[dict]:
    """The owner's messages with what was said just before (by whom), and the `thread`
    turns before that on the same day ("earlier"), so a message keeps the flow it came in:
    banter that turned sincere, a callback, a closing "gn".

    me: the owner's name as it appears in the export (first name is enough).
    """
    names = {me.lower().strip()} if me else set()
    out, burst, before, before_who = [], [], "", ""
    hist: list[tuple[str, str, str]] = []  # (who, text, day), the owner as "me"
    for who, t, day in parse_dated(text) + [("\x00end", "", "")]:
        if who != "\x00end" and _is_me(who, names):
            burst.append(t)
            continue
        if burst:
            last_day = hist[-1][2] if hist else ""
            prior = hist[:-1] if before else hist
            earlier = [h for h in prior[-thread:] if h[2] == last_day] if thread else []
            out.append({"text": "\n".join(burst).strip(), "they": before[:max_context].strip(),
                        "they_who": before_who,
                        "earlier": [f"{w}: {x[:100].strip()}" for w, x, _ in earlier]})
            hist.append(("me", "\n".join(burst).strip().replace("\n", " / "), last_day))
            burst = []
        if who != "\x00end":
            before, before_who = t, ("interviewer" if who.lower() in QA_THEM else who)
            hist.append((before_who, t.replace("\n", " / "), day))
    for o in out:
        if not o["earlier"]:
            o.pop("earlier")
    return [o for o in out if o["text"]]


def context(audience: str, they_who: str, they: str, earlier: list[str] | None = None) -> str:
    who = audience.strip() or "someone"
    if they_who and they_who.lower() not in who.lower() and they_who != "interviewer":
        who = f"{who} ({they_who})"
    if not they:
        return f"{who}, starting the chat"
    head = f"(just before: {' | '.join(earlier)})\n" if earlier else ""
    return f"{who} says: {head}{they}"
