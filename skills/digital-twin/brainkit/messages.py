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
            turns.append([m.group("who").strip(), t])
        elif turns:
            turns[-1][1] += "\n" + line.strip()
    return [(w, t) for w, t in turns]


def _is_me(who: str, me: set[str]) -> bool:
    w = who.lower().strip()
    return w in me or w in QA_ME or any(w == m.split()[0] for m in me if m)


def pairs(text: str, me: str, max_context: int = 160) -> list[dict]:
    """The owner's messages with what was said just before (by whom).

    me: the owner's name as it appears in the export (first name is enough).
    """
    names = {me.lower().strip()} if me else set()
    out, burst, before, before_who = [], [], "", ""
    for who, t in parse(text) + [("\x00end", "")]:
        if who != "\x00end" and _is_me(who, names):
            burst.append(t)
            continue
        if burst:
            out.append({"text": "\n".join(burst).strip(), "they": before[:max_context].strip(),
                        "they_who": before_who})
            burst = []
        if who != "\x00end":
            before, before_who = t, ("interviewer" if who.lower() in QA_THEM else who)
    return [o for o in out if o["text"]]


def context(audience: str, they_who: str, they: str) -> str:
    who = audience.strip() or "someone"
    if they_who and they_who.lower() not in who.lower() and they_who != "interviewer":
        who = f"{who} ({they_who})"
    return f"{who} says: {they}" if they else f"{who}, starting the chat"
