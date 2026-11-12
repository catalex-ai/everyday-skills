"""twin-read MCP server: the twin's only interface. Active persona only.

Read only, with one exception: ask_owner appends a question to the owner's
inbox (inbox.jsonl in the brain home). It never touches facts or personas;
the manager turns inbox lines into questions for the owner."""
from __future__ import annotations

import re

try:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp 2.x
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from . import graph as G
from . import gate, policy, router, search as S, store, style

NO_PERSONA = "No active persona is set. Ask the owner to set one in the twin manager."
MAX_CHARS = 1800

mcp = FastMCP("twin-read")
_cache: dict = {}


class _Unavailable(Exception):
    pass


def _mtime(p) -> float:
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return 0


def _load() -> dict:
    """Resolve the active persona and return its cached files."""
    try:
        slug = policy.active()
    except policy.NoActivePersona:
        raise _Unavailable()
    d = store.persona_dir(slug)
    if not d.is_dir():
        raise _Unavailable()
    key = (str(d), _mtime(d / "facts.jsonl"), _mtime(d / "index.sqlite"))
    hit = _cache.get("entry")
    if hit and hit["key"] == key:
        return hit
    for k in ("index", "ex_index"):
        if hit and hit.get(k):
            try:
                hit[k].close()
            except Exception:
                pass
    _cache.clear()
    facts = store.read_jsonl(d / "facts.jsonl")
    graph = store.read_json(d / "graph.json", {"nodes": {}, "edges": []})
    dictionary = store.read_json(d / "dictionary.json", {"relations": {}, "aliases": {}})
    dictionary.setdefault("relations", {})
    dictionary.setdefault("aliases", {})
    try:
        index = S.open_ro(d) if (d / "index.sqlite").exists() else None
    except Exception:
        index = None
    try:
        ex_index = S.open_ro(d / "examples") if (d / "examples" / "index.sqlite").exists() else None
    except Exception:
        ex_index = None
    entry = {"key": key, "dir": d, "facts": facts, "graph": graph, "by_id": {f["id"]: f for f in facts},
             "examples": {e["id"]: e for e in store.read_jsonl(d / "examples.jsonl")},
             "style": store.read_json(d / "style.json", {}),
             "dictionary": dictionary, "index": index, "ex_index": ex_index}
    _cache["entry"] = entry
    return entry


REPLY_HINT = ("(Your memory, newest first where it matters. A line marked 'older' was replaced by a "
              "newer one: use the newer. Say only what is here about yourself and your people; never "
              "add personal details that are not here. If nothing here answers it, follow the "
              "'missing' move in your skill.)")
NOTHING_HINT = ("(Nothing in your memory about this. If it is about you, your life, your people or "
                "your plans: do not make anything up. Reply warmly, the way you would when you can't "
                "answer right now, and call ask_owner. If it is a general topic, answer from general "
                "knowledge in your own voice.)")
INBOX_MAX = 1000


def _read_text(d, name: str) -> str:
    try:
        return (d / name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _render_walk(results: list[dict]) -> str:
    out = []
    for r in results:
        lines = [r["restated"]]
        chain = [f"{s} —{str(rel).replace('_', ' ')}— {o}" for s, rel, o in r.get("chain", [])]
        if chain:
            lines.append("because: " + "; ".join(chain))
        out.append("\n".join(lines))
    return "\n".join(out)


def _walk(e: dict, q: str) -> str:
    return _render_walk(G.walk(q, e["graph"], e["dictionary"]))


@mcp.tool()
def brief() -> str:
    """Who you are, how you sound and the rules for replying. Call once at the start."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    import re
    parts = []
    for title, name in (("Soul", "soul.md"), ("Voice", "voice.md"), ("Rules", "rules.md")):
        body = re.sub(r"<!--.*?-->", "", _read_text(e['dir'], name), flags=re.S)
        body = re.sub(r"^#\s+" + title + r"\s*$", "", body, flags=re.M | re.I).strip()
        if title == "Voice":
            measured = style.describe(e["style"])
            body = "\n".join(x for x in (body, measured) if x)
            anchors = e["style"].get("anchors") or []
            if anchors:
                body += "\n\nSome of my real messages (how I sound, not what to say):\n" + "\n".join(
                    (f"({a['context']}) " if a.get("context") else "") + f"me: {a['text']}" for a in anchors)
            if body:
                body += ("\n(These are tendencies, not a script. Use at most one habit per message, "
                         "and never open two replies the same way.)")
        if body:
            parts.append(f"# {title}\n{body}")
    card = _read_text(e["dir"], "card.md")
    if card:
        parts.append(card + "\n(You always know these, like any person knows their own life. Never say "
                     "you don't know them or need to check them. Anything private that is not here is "
                     "not for this chat: dodge it warmly, don't pretend not to know.)")
    return "\n\n".join(parts) or "Answer briefly, in the first person."


def _label(f: dict | None) -> str:
    if not f:
        return ""
    bits = [f.get("kind") or "fact"] if (f.get("kind") or "fact") != "fact" else []
    if f.get("since"):
        bits.append(str(f["since"]))
    if f.get("stale"):
        bits.append("older")
    return f"[{' · '.join(bits)}] " if bits else ""


@mcp.tool()
def search(q: str) -> str:
    """Find facts relevant to a question. Returns one fact per line with its id."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    parts = []
    if router.needs_graph(q, e["graph"], e["dictionary"]):
        w = _walk(e, q)
        if w:
            parts.append(w)
    if e["index"] is not None:
        for h in e["index"].search(q, k=8):
            parts.append(f"- {_label(e['by_id'].get(h['id']))}{h['text']}")
    named = _named_page(e, q)
    if named:
        parts.append(named)
    if not parts:
        return "Nothing found. " + NOTHING_HINT
    out, total = [], 0
    for p in parts:
        if total + len(p) > MAX_CHARS and out:
            break
        out.append(p[:MAX_CHARS])
        total += len(p) + 1
    return "\n".join(out) + "\n\n" + REPLY_HINT


def _named_page(e: dict, q: str) -> str:
    """The start of the page for a person, place or thing the message names."""
    low = f" {q.lower()} "
    for node, n in e["graph"].get("nodes", {}).items():
        names = [node] + list(n.get("aliases", []) or [])
        if any(len(x) >= 4 and f" {x.lower()}" in low for x in names if isinstance(x, str)):
            text = page(node)
            if text and text != "No page for that.":
                return f"About {node}:\n" + text[:700]
    return ""


def walk(q: str) -> str:
    """Answer a question about relationships, chains, counts or connections between people and things."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    return _walk(e, q) or ("No connection found. Answer from the search results instead; "
                           "if they do not answer it either, follow the 'missing' move.")


def page(name: str) -> str:
    """Get everything known about one person, place or thing, by name."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    canon = G.canonical(name, e["dictionary"])
    pages = e["dir"] / "pages"
    cands = [canon, name]
    if canon in e["graph"].get("nodes", {}):
        cands += e["graph"]["nodes"][canon].get("aliases", [])
    from .ids import slug as _slug
    for c in cands:
        for stem in (c, _slug(c)):
            p = pages / f"{stem}.md"
            if stem and "/" not in stem and p.is_file():
                return p.read_text(encoding="utf-8")
    return "No page for that."


def profile() -> str:
    """A short overview of who you are."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    return _read_text(e["dir"], "profile.md") or "No profile yet."


def _norm_words(t: str) -> set[str]:
    # "co-founder" == "cofounder", "investors" == "investor"
    return {w.lower().rstrip("s") if len(w) > 4 else w.lower() for w in style._words(str(t).replace("-", ""))}


def _who_words(who: str) -> set[str]:
    return {w for w in _norm_words(who) if len(w) > 2 and w not in style.STOP and w not in AUDIENCE_NOISE}


AUDIENCE_NOISE = {"ask", "say", "about", "after", "message", "chat", "person", "someone", "she", "her", "his",
                  "the", "my", "a", "an", "from", "with", "who"}


def _ranked(e: dict, q: str, who: str = "", k: int = 8) -> tuple[list[dict], bool]:
    """Real messages for this moment: those written to the same kind of person
    (matched on the example's context) first, ordered by topic; else by topic.
    Returns (messages, matched_audience)."""
    if e["ex_index"] is None:
        return [], False
    order = [h["id"] for h in e["ex_index"].search(q, k=200)] if q.strip() else []
    rank = {i: n for n, i in enumerate(order)}
    words = _who_words(who)
    aud = []
    if words:
        for x in e["examples"].values():
            ctx = _norm_words(x.get("context") or "")
            if words & ctx:
                aud.append(x)
    if len(aud) >= 2:
        return _varied(aud, rank, k), True
    return [e["examples"][i] for i in order[:k] if i in e["examples"]], False


def _varied(aud: list[dict], rank: dict, k: int) -> list[dict]:
    """Two closest to the topic, then a spread over the rest. Many messages on one
    topic make the reply echo their content; a spread teaches the register."""
    real = [x for x in aud if not x.get("elicited")]
    pool = real if len(real) >= min(k, 4) else aud  # real messages first; on-request answers fill gaps
    near = sorted(pool, key=lambda x: (rank.get(x["id"], len(rank)), x["id"]))[:2]
    rest = [x for x in pool if x not in near]
    rest += [x for x in aud if x not in pool and x not in near] if len(pool) < k else []
    step = max(1, len(rest) / max(1, k - len(near)))
    spread = [rest[int(i * step)] for i in range(min(len(rest), k - len(near)))]
    return near + spread


SAYS = re.compile(r"^(?P<who>.{1,80}?) (?:says|said|asks|asked|writes|wrote|texts|texted): (?P<msg>.+)$", re.S)


def _pair(x: dict, foil: bool = False) -> str:
    """One real exchange: what they said, then what you sent. With foil: also the
    generic AI version of the same reply, marked as what not to send."""
    ctx = (x.get("context") or "").strip()
    m = SAYS.match(ctx)
    head = f"{m.group('who')}: {m.group('msg').strip()}\n" if m else (f"(when: {ctx})\n" if ctx else "")
    bot = f"✗ a bot would send: {x['foil']}\n" if foil and x.get("foil") else ""
    return head + bot + f"me: {x['text']}"


SPOKEN = re.compile(r"\b(interview|podcast|journalist|reporter|host|speech|talk|panel|press|post|article|"
                    r"town hall|audience|show)\b", re.I)


def _length_hint(msgs: list[dict]) -> str:
    """Typical length of real texts to them. Interview or post answers are not texts: left out.
    Capped at real WhatsApp lengths, since stored messages can run long."""
    n = sorted(len(x["text"].split()) for x in msgs if not SPOKEN.search(x.get("context") or ""))
    if len(n) < 3:
        return "On WhatsApp keep it short: most texts are under 10 words; a longer thought is 2-3 short lines."
    lo, mid, hi = (min(v, 20) for v in (n[len(n) // 4], n[len(n) // 2], n[(3 * len(n)) // 4]))
    return f"Your texts to them are usually {lo} to {hi} words (typical {mid}). Match that."


@mcp.tool()
def examples(q: str, who: str = "") -> str:
    """Real messages you wrote in situations like this one. q: their message or the topic.
    who: who you are talking to, as a relationship ("close friend", "investor", "mother",
    "journalist"). Copy how you sound, not what you said."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    if e["ex_index"] is None:
        return "No examples yet. Keep it short and plain."
    near, matched = _ranked(e, q, who, k=6)
    picked = near[:3]
    if matched:  # one or two on the topic too, from any audience
        for h in e["ex_index"].search(q, k=4):
            x = e["examples"].get(h["id"])
            if x and x not in picked and len(picked) < 5:
                picked.append(x)
    out = [_pair(x, foil=n < 3) for n, x in enumerate(picked)]
    if not out:
        return "No close examples. Keep it short and plain."
    head = ("" if matched or not who else
            f"(No messages to them ({who}) yet: match how they write to you, and how you'd talk to "
            "that kind of person.)\n\n")
    size = _length_hint(near) if matched else ""
    return (head + "\n\n".join(out))[:MAX_CHARS] + (f"\n\n{size}" if size else "") + (
        ("\n\n(✗ lines are the generic version of the same reply: everything that makes them sound like a "
         "bot, you don't do.)" if any(x.get("foil") for x in picked[:3]) else "") +
        "\n\n(How you sound with this kind of person: length, capitals, rhythm, words, humour. "
        "Do not copy their facts into this reply unless your memory says the same.)")


@mcp.tool()
def ask_owner(question: str, who: str = "") -> str:
    """Note a question you could not answer, so the real you can answer it later."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    q = gate.strip_tokens(gate.redact(" ".join(str(question).split())[:400])[0])
    w = gate.strip_tokens(gate.redact(" ".join(str(who).split())[:80])[0])
    if not q:
        return "Nothing to note."
    p = store.home() / "inbox.jsonl"
    rows = store.read_jsonl(p) if p.exists() else []
    if any(r.get("question") == q and r.get("status", "open") == "open" for r in rows):
        return "Already noted. Tell them you'll come back on it."
    if len(rows) >= INBOX_MAX:
        return "Noted. Tell them you'll come back on it."
    store.append_jsonl(p, {"ts": store.now(), "persona": e["dir"].name, "who": w, "question": q,
                           "status": "open"})
    return "Noted. Tell them you'll come back on it, in your own words."


@mcp.tool()
def check_reply(draft: str, their_message: str = "", who: str = "") -> str:
    """Check a draft reply before you send it. who: the relationship, as for examples().
    Returns what to fix, or OK."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    fixes = style.check(draft, their_message, e["style"])
    near, matched = _ranked(e, their_message, who) if (their_message or who) else ([], False)
    fixes += style.local_check(draft, near, audience=who if matched else "")
    fixes += style.detail_check(draft, their_message)
    if "own_lines" not in e:
        e["own_lines"] = [x["text"] for x in e["examples"].values()] + [
            f["text"] for f in e["facts"] if f.get("kind") in ("opinion", "story")]
    dup = style.copied(draft, e["own_lines"])
    if dup:
        fixes.append(f"'{dup}' is copied from your own stored words. People don't repeat their own "
                     "lines word for word: keep the point, say it fresh, in words that fit this chat.")
    if not fixes:
        return "OK. Send it as it is."
    ref = "\n".join((f"({x['context']}) " if x.get("context") else "") + f"me: {x['text']}" for x in near[:2])
    return ("Fix before sending:\n" + "\n".join(f"- {f}" for f in fixes)
            + (f"\n\nYour real messages in chats like this:\n{ref}" if ref else "")
            + "\n\n(Private advice for you. A rule of yours wins only for exactly what it names: a rule "
              "about money terms covers amounts and terms, not whether you're raising; a rule about your "
              "time covers new slots, not your routine. Your next output is only the chat message: never "
              "mention this check, your rules or that you kept or changed anything.)")


if __name__ == "__main__":
    mcp.run(transport="stdio")
