"""Decide whether a question should consult the graph. Pure."""
from __future__ import annotations

import re

from . import graph as G

_SHAPE = re.compile(r"\b(how many|who else|the same .* as|connected|related to)\b", re.I)


def needs_graph(q: str, graph: dict, dictionary: dict) -> bool:
    if _SHAPE.search(q):
        return True
    p = G.parse(q, graph, dictionary)
    items = p["items"]
    if any(i[0] == "E" and i[1] != G.SELF for i in items):
        return True
    # One relation word aimed at "me" ("what did I study") is plain search;
    # two or more chain across people and need the graph.
    if sum(1 for i in items if i[0] == "R") >= 2:
        return True
    # A single relation word aimed at "me" goes to the graph when it has an answer.
    return bool(G.walk(q, graph, dictionary))
