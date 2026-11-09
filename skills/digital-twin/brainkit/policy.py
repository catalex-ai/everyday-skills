"""Categories, personas, rules, active persona, relation dictionary."""
import json
import shutil

from . import store
from .ids import slug as _slug


class NoActivePersona(Exception):
    pass


def _text(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def define_category(slug, description):
    con = store.db()
    with con:
        con.execute("INSERT INTO categories(slug,description) VALUES(?,?) "
                    "ON CONFLICT(slug) DO UPDATE SET description=excluded.description",
                    (slug, description))
    con.close()


def categories() -> dict:
    con = store.db()
    try:
        return {r["slug"]: r["description"] for r in con.execute("SELECT * FROM categories ORDER BY slug")}
    finally:
        con.close()


def create_persona(slug, audience, include, exclude):
    if _slug(slug) != slug or not slug:
        raise ValueError(f"invalid persona slug: {slug!r}")
    con = store.db()
    with con:
        con.execute("INSERT INTO personas(slug,audience,include,exclude,created) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(slug) DO UPDATE SET audience=excluded.audience, "
                    "include=excluded.include, exclude=excluded.exclude",
                    (slug, _text(audience), _text(include), _text(exclude), store.now()))
    con.close()
    d = store.persona_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / "contract.md").write_text(
        f"# Contract: {slug}\n\n## Audience\n{_text(audience)}\n\n"
        f"## Include\n{_text(include)}\n\n## Exclude\n{_text(exclude)}\n", encoding="utf-8")
    for name in ("soul.md", "voice.md", "rules.md"):
        if not (d / name).exists():
            shutil.copyfile(store.TEMPLATES / name, d / name)
    return d


def personas() -> list[dict]:
    con = store.db()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM personas ORDER BY slug")]
    finally:
        con.close()


def persona(slug) -> dict | None:
    con = store.db()
    try:
        r = con.execute("SELECT * FROM personas WHERE slug=?", (slug,)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def set_rule(persona, category, decision):
    if decision not in ("allow", "deny"):
        raise ValueError(f"decision must be allow or deny, got {decision!r}")
    con = store.db()
    with con:
        con.execute("INSERT INTO rules(persona,category,decision) VALUES(?,?,?) "
                    "ON CONFLICT(persona,category) DO UPDATE SET decision=excluded.decision",
                    (persona, category, decision))
    con.close()


def rule(persona, category) -> str | None:
    con = store.db()
    try:
        r = con.execute("SELECT decision FROM rules WHERE persona=? AND category=?",
                        (persona, category)).fetchone()
        return r["decision"] if r else None
    finally:
        con.close()


def rules(persona) -> dict:
    con = store.db()
    try:
        return {r["category"]: r["decision"] for r in con.execute(
            "SELECT category,decision FROM rules WHERE persona=? ORDER BY category", (persona,))}
    finally:
        con.close()


def set_active(slug):
    if persona(slug) is None:
        raise ValueError(f"unknown persona: {slug}")
    p = store.active_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(slug + "\n", encoding="utf-8")


def active() -> str:
    p = store.active_path()
    slug = p.read_text(encoding="utf-8").strip() if p.exists() else ""
    if not slug or persona(slug) is None:
        raise NoActivePersona(slug or "no active persona set")
    return slug


def dictionary() -> dict:
    store.init()
    d = store.read_json(store.dictionary_path(), {})
    d.setdefault("relations", {})
    d.setdefault("aliases", {})
    return d


def define_relation(name, inverse=None, symmetric=False, single=False, words=(), inverse_words=()):
    d = dictionary()
    d["relations"][name] = {"inverse": inverse, "symmetric": bool(symmetric), "single": bool(single),
                            "words": list(words), "inverse_words": list(inverse_words)}
    store.write_json(store.dictionary_path(), d)


def add_alias(alias, canonical):
    d = dictionary()
    d["aliases"][alias] = canonical
    store.write_json(store.dictionary_path(), d)
