"""twin-read MCP server: the twin's only interface. Read only, active persona only."""
from __future__ import annotations

try:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp 2.x
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from . import graph as G
from . import policy, router, search as S, store

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
    if hit and hit.get("index"):
        try:
            hit["index"].close()
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
    entry = {"key": key, "dir": d, "facts": facts, "graph": graph,
             "dictionary": dictionary, "index": index}
    _cache["entry"] = entry
    return entry


REPLY_HINT = ("(Use only the lines above that answer the question. Reply as the owner, "
              "in one or two plain sentences. If none answer it, reply only: "
              "I don't have anything on that to share.)")
NOTHING_HINT = "(Reply only: I don't have anything on that to share.)"


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
        if body:
            parts.append(f"# {title}\n{body}")
    return "\n\n".join(parts) or "Answer briefly, in the first person."


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
            parts.append(f"- {h['text']} [{h['id']}]")
    if not parts:
        return "Nothing found. " + NOTHING_HINT
    out, total = [], 0
    for p in parts:
        if total + len(p) > MAX_CHARS and out:
            break
        out.append(p[:MAX_CHARS])
        total += len(p) + 1
    return "\n".join(out) + "\n\n" + REPLY_HINT


@mcp.tool()
def walk(q: str) -> str:
    """Answer a question about relationships, chains, counts or connections between people and things."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    return _walk(e, q) or ("No connection found. Answer from the search results instead; "
                           "if they do not answer it either, reply only: "
                           "I don't have anything on that to share.")


@mcp.tool()
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


@mcp.tool()
def profile() -> str:
    """A short overview of who you are."""
    try:
        e = _load()
    except _Unavailable:
        return NO_PERSONA
    return _read_text(e["dir"], "profile.md") or "No profile yet."


if __name__ == "__main__":
    mcp.run(transport="stdio")
