"""Deterministic persona build: allowed items only, held values restored only where mode is allow."""
import hashlib
import json
from pathlib import Path

from . import gate, graph, ids, policy, raw, search, store, style


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
    every = _clean(allowed_items(persona))
    dic = policy.dictionary()
    examples = [i for i in every if i.get("kind") == "example"]
    items = [i for i in every if i.get("kind") != "example"]
    g = graph.build_graph(items, dic)
    by_id = {i["id"]: i for i in items}
    produced = set()
    stale = stale_ids(items, dic)

    facts = [{"id": i["id"], "about": i["about"], "category": i["category"], "text": i["text"],
              "kind": i.get("kind") or "fact", "since": i.get("since"), "by": i["by"],
              **({"stale": True} if i["id"] in stale else {})} for i in items]
    _write(d / "facts.jsonl", "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in facts))
    from . import foils as _foils
    fo = _foils.load()
    # by: "you" = written by the owner on request (a reply question); else from real material.
    ex = [{"id": i["id"], "about": i["about"], "text": i["text"], "context": i.get("context") or "",
           **({"elicited": True} if i.get("by") == "you" else {}),
           **({"foil": fo[i["id"]]} if i["id"] in fo else {})} for i in examples]
    _write(d / "examples.jsonl", "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in ex))
    _write(d / "style.json", _json({**style.fingerprint(ex), "anchors": [
        {"context": a["context"], "text": a["text"]} for a in style.anchors(ex)]}))
    search.build_index(d / "examples", [{"id": e["id"], "about": e["about"],
                                         "text": (e["context"] + " :: " + e["text"]).strip(" :")}
                                        for e in ex])
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
    _write(d / "card.md", life_card(items, g, dic, cats, stale))
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


CARD_LINES = 45
CARD_PEOPLE = 12
CARD_ABOUT = 40
CARD_ABOUT_EACH = 3


def life_card(items: list[dict], g: dict, dic: dict, cats: dict, stale: set[str]) -> str:
    """The things a person always knows about their own life, for this persona.

    Facts about the owner (newest first, spread across categories so no single
    topic crowds out the rest), then one line per person or organisation linked
    to the owner. Opinions, stories and stale facts are left out: they come from
    search when a conversation needs them."""
    live = [i for i in items if i["id"] not in stale and (i.get("kind") or "fact") == "fact"]
    mine = [i for i in live if ids_about_me(i, dic)]
    by_cat: dict[str, list[dict]] = {}
    for i in sorted(mine, key=lambda i: (str(i.get("since") or ""), i.get("created") or ""), reverse=True):
        by_cat.setdefault(i["category"], []).append(i)
    picked, seen = [], set()
    while len(picked) < CARD_LINES and any(by_cat.values()):
        for c in sorted(by_cat):
            if by_cat[c] and len(picked) < CARD_LINES:
                i = by_cat[c].pop(0)
                if i["text"] not in seen:
                    seen.add(i["text"])
                    picked.append(i)
    lines = [f"- {i['text']}" for i in picked]
    # Everyone and everything linked to me, grouped by how: "child: A, B, C".
    # Small groups first: close people are few, films and awards are many.
    groups: dict[str, list[str]] = {}
    rels = dic.get("relations", {})
    for e in g.get("edges", []):
        if "me" not in (e["s"], e["o"]) or e["s"] == e["o"] or e.get("fact") in stale:
            continue
        rel = str(e["rel"])
        r = rels.get(rel) or {}
        if e["s"] == "me":
            other, words = e["o"], r.get("words") or []
        else:
            other, words = e["s"], r.get("inverse_words") or []
        label = (words[0] if words else rel.replace("_", " "))
        if other not in groups.setdefault(label, []):
            groups[label].append(other)
    people = [f"- {label}: " + ", ".join(names[:CARD_PEOPLE])
              for label, names in sorted(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))]
    # The newest facts about the people and organisations linked to me (my
    # company's numbers, what my partner does now), close links first.
    linked = [n for _, names in sorted(groups.items(), key=lambda kv: (len(kv[1]), kv[0])) for n in names]
    about_lines, seen_n = [], set()
    for name in linked:
        if name in seen_n:
            continue
        seen_n.add(name)
        its = [i for i in live if graph.canonical(i.get("about") or "", dic) == name and i["text"] not in seen]
        its.sort(key=lambda i: (str(i.get("since") or ""), i.get("created") or ""), reverse=True)
        for i in its[:max(CARD_ABOUT_EACH, min(10, len(its) // 4))]:
            seen.add(i["text"])
            about_lines.append(f"- {i['text']}")
        if len(about_lines) >= CARD_ABOUT:
            break
    out = ["# My life (things I always know)"] + (lines or ["- (nothing yet)"])
    if about_lines:
        out += ["", "# My people and my work, now"] + about_lines[:CARD_ABOUT]
    if people:
        out += ["", "# My people, places and things, by how they link to me"] + people[:30]
    return "\n".join(out) + "\n"


def stale_ids(items: list[dict], dic: dict) -> set[str]:
    """Facts overtaken by a newer one: same subject and a single-valued relation
    (lives_in, works_at as current, spouse_of...), older `since`. Kept, flagged."""
    groups: dict[tuple, list[dict]] = {}
    for i in items:
        e = i.get("edge") or {}
        rel = e.get("rel")
        if not rel or not (dic.get("relations", {}).get(rel) or {}).get("single"):
            continue
        s = graph.canonical(e.get("s") or i.get("about") or "me", dic)
        groups.setdefault((s, rel), []).append(i)
    out = set()
    for its in groups.values():
        if len({graph.canonical(x["edge"]["o"], dic) for x in its}) < 2:
            continue
        top = _newest(its)
        out |= {x["id"] for x in its if x["id"] != top["id"]}
    return out


def ids_about_me(item: dict, dic: dict) -> bool:
    return graph.canonical(item.get("about") or "me", dic) == "me"


def rebuild_all() -> dict:
    return {p["slug"]: rebuild(p["slug"]) for p in policy.personas()}
