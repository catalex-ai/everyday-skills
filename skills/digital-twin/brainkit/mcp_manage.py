"""twin-manage MCP server: thin wrappers for the owner's manager agent."""
from __future__ import annotations

import functools

try:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp 2.x
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from . import gate, policy, raw, store

mcp = FastMCP("twin-manage")


def _safe(fn):
    """Turn ValueError into {"error": ...}; keep the signature for FastMCP."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except ValueError as e:
            return {"error": str(e)}
    return wrapper


def tool(fn):
    wrapped = _safe(fn)
    mcp.tool()(wrapped)
    return wrapped


def _waiting() -> list[str]:
    try:
        from . import questions
        return sorted({q["category"] for q in questions.all(status="open") if q.get("category")})
    except ImportError:
        return []


@tool
def init() -> dict:
    """Create the brain folder and its settings if they do not exist yet."""
    return {"home": str(store.init())}


@tool
def status() -> dict:
    """Overview: brain location, active persona, personas, categories, privacy modes, open questions, item counts."""
    store.init()
    try:
        active = policy.active()
    except policy.NoActivePersona:
        active = None
    out = {
        "brain": str(store.home()),
        "active": active,
        "personas": policy.personas(),
        "categories": policy.categories(),
        "privacy": gate.settings(),
        "open_questions": 0,
        "stats": raw.stats(),
    }
    for p in out["personas"]:
        p["rules"] = policy.rules(p["slug"])
        facts = store.read_jsonl(store.persona_dir(p["slug"]) / "facts.jsonl")
        p["facts"] = len(facts)
    try:
        from . import questions
        out["open_questions"] = len(questions.all(status="open"))
    except ImportError:
        pass
    return out


@tool
def add_source(text: str, origin: str) -> dict:
    """Store a piece of raw source text (after privacy filtering) and return its id."""
    return {"id": raw.add_source(text, origin)}


@tool
def add_items(items: list[dict]) -> dict:
    """Add facts. Each item has text and category, and optionally about, edge {s, rel, o}, src, since, conf, by."""
    ids = raw.add_items(items)
    out = {"ids": ids, "waiting": []}
    from . import lint
    mixed = lint.mixed(ids)
    if mixed:
        out["mixed"] = mixed
        out["fix"] = ("These facts name a relationship of another type. Split each with "
                      "replace_item: keep the name, drop the relationship word, and add the "
                      "relationship as its own fact in its own category.")
    try:
        from . import questions
        questions.sync()
        out["waiting"] = _waiting()
    except ImportError:
        pass
    return out


@tool
def replace_item(old_id: str, items: list[dict]) -> dict:
    """Replace one fact with one or more corrected facts. The old fact is kept as superseded."""
    ids = raw.add_items(items)
    raw.set_status(old_id, "superseded")
    out = {"ids": ids, "superseded": old_id}
    try:
        from . import questions
        questions.sync()
    except ImportError:
        pass
    from . import lint
    still = lint.mixed(ids)
    if still:
        out["mixed"] = still
    return out


@tool
def check_mixed() -> dict:
    """List stored facts that mix a relationship of one type into a fact of another type."""
    from . import lint
    return {"mixed": lint.mixed()}


@tool
def define_category(slug: str, description: str) -> dict:
    """Create or update a category of facts.

    The reply lists personas with no rule for this category yet. Call set_rule
    for each one whose include or exclude clearly decides it; leave the rest to
    become questions for the owner."""
    policy.define_category(slug, description)
    unset = [{"persona": p["slug"], "include": p.get("include"), "exclude": p.get("exclude")}
             for p in policy.personas() if policy.rule(p["slug"], slug) is None]
    return {"ok": True, "category": slug, "personas_without_rule": unset}


@tool
def define_relation(name: str, inverse: str | None = None, symmetric: bool = False,
                    single: bool = False, words: list[str] | None = None,
                    inverse_words: list[str] | None = None) -> dict:
    """Define a relation type and the words used for each end of it."""
    policy.define_relation(name, inverse, symmetric, single, words or (), inverse_words or ())
    return {"ok": True}


@tool
def add_alias(alias: str, canonical: str) -> dict:
    """Make one name an alias of another."""
    policy.add_alias(alias, canonical)
    return {"ok": True}


@tool
def create_persona(slug: str, audience: str, include: str, exclude: str) -> dict:
    """Create or update a persona: who it talks to, what it may include and exclude."""
    d = policy.create_persona(slug, audience, include, exclude)
    return {"ok": True, "dir": str(d)}


@tool
def set_rule(persona: str, category: str, decision: str) -> dict:
    """Allow or deny a category for a persona."""
    policy.set_rule(persona, category, decision)
    return {"ok": True}


@tool
def set_active(slug: str) -> dict:
    """Choose which persona the twin answers as."""
    policy.set_active(slug)
    return {"ok": True, "active": slug}


@tool
def set_privacy(type: str, mode: str) -> dict:
    """Set how a kind of personal data is handled: allow, hold or drop. Applies to existing data."""
    gate.set_mode(type, mode)
    applied = raw.apply_privacy()
    out = {"ok": True, "applied": applied}
    try:
        from . import build
        out["rebuilt"] = build.rebuild_all()
    except ImportError:
        out["rebuilt"] = None
    return out


@tool
def sync() -> dict:
    """Update the list of open questions from the current facts and rules."""
    from . import questions
    return questions.sync()


@tool
def next_questions(n: int = 2) -> list:
    """The next questions to ask the owner."""
    from . import questions
    return questions.next(n)


@tool
def answer(question_id: str, text: str = "", decision: str | None = None,
           status: str | None = None) -> dict:
    """Record the owner's answer, decision, or a decline/snooze for a question."""
    from . import questions
    return questions.answer(question_id, text, decision, status)


@tool
def record_correction(said: str, should: str, target: str, persona: str | None = None,
                      payload: dict | None = None) -> dict:
    """Record a correction. Target is one of voice, rules, item, category, schema, soul, privacy."""
    from . import corrections
    return corrections.record(said, should, target, persona, payload)


@tool
def tidy() -> dict:
    """Clean up duplicates and stale entries."""
    from . import tidy as t
    return t.run()


@tool
def audit() -> dict:
    """Write the audit page showing what each persona can see."""
    from . import audit_html
    return audit_html.run()


@tool
def gate_scan(text: str) -> dict:
    """Check text for personal data. Returns types and positions only, never values."""
    return {"findings": gate.scan(text)}


@tool
def list_items(category: str | None = None, status: str = "active") -> dict:
    """List up to 200 stored facts, optionally for one category."""
    rows = raw.items(status=status, categories=[category] if category else None)
    return {"total": len(rows), "items": rows[:200]}


if __name__ == "__main__":
    mcp.run(transport="stdio")
