"""Deterministic persona build: allowed items only, held values restored only where mode is allow."""
import hashlib
import json
from pathlib import Path

from . import gate, graph, ids, policy, raw, search, store


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _json(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False)


def allowed_items(persona: str) -> list[dict]:
    cats = sorted(c for c, d in policy.rules(persona).items() if d == "allow")
    if not cats:
        return []
    return _without_hidden_people(raw.items(categories=cats), set(cats))


def hidden_people(allowed_cats: set[str], dic: dict | None = None) -> set[str]:
    """People with any link to the owner that this persona cannot see.

    A fact about such a person can reveal the hidden relationship (a child who
    is also a co-worker), whatever category it was filed under, so the person's
    own facts are withheld. Facts about the owner that name them still show."""
    dic = dic if dic is not None else policy.dictionary()
    seen: dict[str, bool] = {}
    for it in raw.items():  # active items of every category
        e = it.get("edge") or {}
        if not e.get("rel") or e.get("o") is None:
            continue
        s, o = graph.canonical(e.get("s") or it.get("about") or "me", dic), graph.canonical(e["o"], dic)
        if "me" not in (s, o) or s == o:
            continue
        other = o if s == "me" else s
        if it["category"] not in allowed_cats:
            seen[other] = True
    return {p for p, hidden in seen.items() if hidden}


def _without_hidden_people(items: list[dict], allowed_cats: set[str]) -> list[dict]:
    dic = policy.dictionary()
    hidden = hidden_people(allowed_cats, dic)
    if not hidden:
        return items
    return [i for i in items if graph.canonical(i.get("about") or "me", dic) not in hidden]


def _clean(items: list[dict]) -> list[dict]:
    held, modes = raw.held_map(), gate.settings()
    out = []
    for it in items:
        it = dict(it)
        it["text"] = gate.unhold(it["text"], held, modes)
        if it.get("edge"):
            e = dict(it["edge"])
            if e.get("o") is not None:
                e["o"] = gate.unhold(e["o"], held, modes)
            it["edge"] = e
        out.append(it)
    return out


def _sentence(e: dict) -> str:
    return f"{e['s']} {e['rel'].replace('_', ' ')} {e['o']}."


def _newest(items: list[dict]) -> dict:
    return max(items, key=lambda i: (i.get("since") or "", i.get("created") or "", i["id"]))


def rebuild(persona: str) -> dict:
    d = store.persona_dir(persona)
    d.mkdir(parents=True, exist_ok=True)
    items = _clean(allowed_items(persona))
    dic = policy.dictionary()
    g = graph.build_graph(items, dic)
    by_id = {i["id"]: i for i in items}
    produced = set()

    facts = [{"id": i["id"], "about": i["about"], "category": i["category"], "text": i["text"],
              "since": i.get("since"), "by": i["by"]} for i in items]
    _write(d / "facts.jsonl", "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in facts))
    _write(d / "graph.json", _json(g))

    used = set()
    for i in items:
        if i.get("edge") and i["edge"].get("rel"):
            used.add(i["edge"]["rel"])
    for e in g["edges"]:
        used.add(e["rel"])
    rels = {r: dic["relations"][r] for r in sorted(used) if r in dic["relations"]}
    # include the inverse definitions of used relations so the vocabulary stays consistent
    for r in list(rels):
        inv = rels[r].get("inverse")
        if inv and inv in dic["relations"]:
            rels[inv] = dic["relations"][inv]
    aliases = {a: c for a, c in sorted(dic["aliases"].items()) if c in g["nodes"]}
    _write(d / "dictionary.json", _json({"relations": dict(sorted(rels.items())), "aliases": aliases}))

    # pages
    links: dict[str, set] = {}
    for e in g["edges"]:
        links.setdefault(e["s"], set()).add(e["o"])
        links.setdefault(e["o"], set()).add(e["s"])
    pages, slugs = [], {}
    for name, info in g["nodes"].items():
        its = [by_id[f] for f in info["facts"] if f in by_id]
        if not its and name != "me":
            continue
        its.sort(key=lambda i: (i.get("created") or "", i["id"]))
        s = ids.slug(name) or "entity"
        base, n = s, 2
        while s in slugs:
            s, n = f"{base}-{n}", n + 1
        slugs[s] = name
        lines = [f"# {name}", ""]
        now = _newest(its)["text"] if its else ""
        lines.append(f"Now: {now}" if now else "Now:")
        lines.append("")
        lines += [f"- {i['text']} ^{i['id']}" for i in its]
        rel = sorted(links.get(name, set()) - {name}, key=lambda x: (x.lower(), x))
        if rel:
            lines += ["", "Links:"] + [f"- {x}" for x in rel]
        _write(d / "pages" / f"{s}.md", "\n".join(lines) + "\n")
        produced.add(f"pages/{s}.md")
        pages.append((name, s, now))

    idx = ["# Index", ""] + [f"- [{n}](pages/{s}.md)" + (f": {now}" if now else "") for n, s, now in pages]
    _write(d / "index.md", "\n".join(idx) + "\n")

    cats = policy.categories()
    mine = [i for i in items if ids_about_me(i, dic)]
    prof = ["# Profile", ""]
    for c in sorted({i["category"] for i in mine}):
        prof += [f"## {cats.get(c) or c}", ""]
        prof += [f"- {i['text']}" for i in mine if i["category"] == c]
        prof.append("")
    _write(d / "profile.md", "\n".join(prof).rstrip("\n") + "\n")

    sfacts = [{"id": f["id"], "about": f["about"], "text": f["text"]} for f in facts]
    have = {f["id"] for f in facts}
    for e in g["edges"]:
        if e["fact"] not in have:
            sfacts.append({"id": "e-" + hashlib.sha1(json.dumps(e, sort_keys=True).encode()).hexdigest()[:10],
                           "about": e["s"], "text": _sentence(e)})
    search.build_index(d, sfacts)

    # remove stale generated files
    removed = 0
    pd = d / "pages"
    if pd.exists():
        for p in pd.glob("*.md"):
            if f"pages/{p.name}" not in produced:
                p.unlink()
                removed += 1
    store.log("rebuild", persona=persona, facts=len(facts))
    return {"persona": persona, "facts": len(facts), "pages": len(pages),
            "edges": len(g["edges"]), "removed": removed}


def ids_about_me(item: dict, dic: dict) -> bool:
    return graph.canonical(item.get("about") or "me", dic) == "me"


def rebuild_all() -> dict:
    return {p["slug"]: rebuild(p["slug"]) for p in policy.personas()}
