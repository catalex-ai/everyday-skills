"""Checks on stored facts that the model is asked to fix.

mixed(): a fact that names a relationship of one type of information while it is
filed under another type, where some persona may know the second but not the
first. Example: "I co-founded Northwind Ltd with my wife Asha" filed as work, for
a persona that may know work but not family. The relationship words come from
the owner's own dictionary and edges, never from a list in code.
"""
from __future__ import annotations

import re

from . import policy, raw

POSSESSIVE = r"(?:my|our|his|her|their)"


def _rel_categories(items: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for it in items:
        e = it.get("edge") or {}
        if e.get("rel"):
            out.setdefault(e["rel"], set()).add(it["category"])
    return out


def _risky(item_cat: str, rel_cats: set[str], rules: dict[str, dict]) -> bool:
    """True when some persona may know item_cat but none of rel_cats."""
    for r in rules.values():
        if r.get(item_cat) == "allow" and not any(r.get(c) == "allow" for c in rel_cats):
            return True
    return False


def mixed(ids: list[str] | None = None) -> list[dict]:
    items = raw.items()
    rel_cats = _rel_categories(items)
    rels = policy.dictionary().get("relations", {})
    rules = {p["slug"]: policy.rules(p["slug"]) for p in policy.personas()}
    want = set(ids) if ids else None
    out = []
    for it in items:
        if want is not None and it["id"] not in want:
            continue
        text = it["text"].lower()
        for rel, cats in sorted(rel_cats.items()):
            if it["category"] in cats or not _risky(it["category"], cats, rules):
                continue
            r = rels.get(rel, {})
            words = [w for w in list(r.get("words", [])) + list(r.get("inverse_words", [])) if w]
            hit = next((w for w in words if re.search(
                rf"\b{POSSESSIVE}\s+{re.escape(w.lower())}(?:s|es)?\b", text)), None)
            if hit:
                out.append({"id": it["id"], "text": it["text"], "category": it["category"],
                            "word": hit, "belongs_to": sorted(cats)})
                break
    return out
