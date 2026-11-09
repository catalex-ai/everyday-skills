"""Relation graph over facts. Pure: dicts in, dicts out, no store access.

No relation word is hardcoded: every relation word comes from the dictionary.
Questions are walked hop by hop (chains, sets, counts, paths); anything the
parser cannot read in full returns [] rather than a guess.
"""
from __future__ import annotations

import re
from collections import deque

SELF = "me"
# The twin talks to other people, so "you" and "your" also mean the owner.
PRONOUNS = {"i", "me", "my", "myself", "mine", "you", "your", "yours", "yourself"}
MAX_PATH = 4

# Grammar words only (no relation vocabulary). Anything else left over after
# entities and dictionary words are read makes walk refuse.
STOP = set("""a an the of is are was were be been am do does did doing have has had
i me my myself what who whom whose where which when how many much else other others
than besides except excluding and or to in at on for from with by go goes went about
tell name person people anyone someone one ones company there that this it its s also
still now ever number count list all any same as connected related connection""".split())
_CUT = (("besides",), ("except",), ("excluding",), ("other", "than"), ("apart", "from"))


# ------------------------------------------------------------------ text

def _tokens(text: str) -> list[str]:
    text = re.sub(r"['’]s\b", " ", str(text).lower())
    return re.findall(r"[^\W_]+", text)


IRREGULAR = {"children": "child", "people": "person", "men": "man", "women": "woman",
             "won": "win", "born": "bear", "wives": "wife"}
_DROP_IN_NAMES = {"of", "at", "in", "by"}


def _stem(w: str) -> str:
    w = IRREGULAR.get(w, w)
    if len(w) <= 3:
        return w
    if w.endswith("ies") or w.endswith("ied"):
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    return w


def _stems(text: str) -> tuple:
    return tuple(_stem(t) for t in _tokens(text))


def canonical(name: str, dictionary: dict) -> str:
    n = " ".join(str(name).split())
    low = n.lower()
    if low in PRONOUNS:
        return SELF
    for a, c in (dictionary.get("aliases") or {}).items():
        if a.lower() == low:
            return c
    return n


# ----------------------------------------------------------- relation logic

def _inverse_map(dictionary: dict) -> dict:
    rels = dictionary.get("relations") or {}
    inv = {}
    for r, e in rels.items():
        i = e.get("inverse")
        if i and i != r:
            inv.setdefault(r, i)
            inv.setdefault(i, r)
    return inv


def _stored(rel: str, dictionary: dict) -> tuple[str, bool]:
    """(name edges are stored under, flipped?). Of a pair the alphabetically first wins."""
    inv = _inverse_map(dictionary).get(rel)
    if inv and inv < rel:
        return inv, True
    return rel, False


def build_graph(items: list[dict], dictionary: dict) -> dict:
    rels = dictionary.get("relations") or {}
    aliases: dict[str, set] = {}
    for a, c in (dictionary.get("aliases") or {}).items():
        aliases.setdefault(c, set()).add(a)
    nodes: dict[str, set] = {SELF: set()}
    edges = set()
    for it in items:
        if it.get("status", "active") != "active":
            continue
        fid = it.get("id")
        about = canonical(it.get("about") or SELF, dictionary)
        nodes.setdefault(about, set()).add(fid)
        e = it.get("edge")
        if not e or not e.get("rel"):
            continue
        s, o = canonical(e["s"], dictionary), canonical(e["o"], dictionary)
        rel, flipped = _stored(e["rel"], dictionary)
        if flipped:
            s, o = o, s
        if rels.get(rel, {}).get("symmetric") and (o.lower(), o) < (s.lower(), s):
            s, o = o, s
        nodes.setdefault(s, set()).add(fid)
        nodes.setdefault(o, set()).add(fid)
        edges.add((s, rel, o, fid))
    out_nodes = {}
    for n in sorted(nodes, key=lambda x: (x.lower(), x)):
        out_nodes[n] = {"aliases": sorted(aliases.get(n, ()), key=lambda x: (x.lower(), x)),
                        "facts": sorted(f for f in nodes[n] if f)}
    # one edge per (s, rel, o): keep the smallest fact id
    best = {}
    for s, r, o, f in sorted(edges, key=lambda t: (t[0], t[1], t[2], t[3] or "")):
        best.setdefault((s, r, o), f)
    out_edges = [{"s": s, "rel": r, "o": o, "fact": f}
                 for (s, r, o), f in sorted(best.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1], kv[0][2].lower(), kv[0]))]
    return {"nodes": out_nodes, "edges": out_edges}


# ------------------------------------------------------------------ parsing

def _entity_index(graph: dict, dictionary: dict) -> dict:
    idx = {}
    for n, info in (graph.get("nodes") or {}).items():
        for label in [n] + list(info.get("aliases") or []):
            t = tuple(_tokens(label))
            if t:
                idx.setdefault(t, n)
    for a, c in (dictionary.get("aliases") or {}).items():
        t = tuple(_tokens(a))
        if t:
            idx.setdefault(t, canonical(c, dictionary))
    for p in PRONOUNS:
        idx[(p,)] = SELF
    return idx


def _phrase_index(dictionary: dict) -> dict:
    """stem tuple -> [(rel, dir)]. Words the dictionary states come first, in the
    direction it states; words read off a relation's name (born_in -> "born") come
    after, in both directions, so whichever direction has results wins."""
    idx = {}
    rels = dictionary.get("relations") or {}

    def add(phrase, cand):
        toks = _tokens(phrase)
        if not toks or PRONOUNS & set(toks):
            return
        lst = idx.setdefault(tuple(_stem(t) for t in toks), [])
        if cand not in lst:
            lst.append(cand)

    # Edges live under a pair's stored name. That relation's own words go in
    # first; its partner only adds words the stored one does not already claim,
    # so a pair written with clashing words cannot flip the answer.
    claimed: dict[str, set] = {}
    order = sorted(rels, key=lambda r: (_stored(r, dictionary)[1], r))
    for rel in order:
        stored, flipped = _stored(rel, dictionary)
        for key, d in (("words", "out"), ("inverse_words", "in")):
            for w in rels[rel].get(key) or []:
                st = tuple(_stem(t) for t in _tokens(w))
                if flipped and stored in claimed.get(st, set()):
                    continue
                if not flipped:
                    claimed.setdefault(st, set()).add(rel)
                add(w, (rel, d))
    for rel in sorted(rels):
        name = " ".join(t for t in rel.split("_") if t and t not in _DROP_IN_NAMES and len(t) > 2)
        if name:
            st = tuple(_stem(t) for t in _tokens(name))
            have = {_stored(c[0], dictionary)[0] for c in idx.get(st, [])}
            if rels[rel].get("inverse") in rels and _stored(rel, dictionary)[0] in have:
                continue  # a defined pair already says which way this word points
            # Read off the relation's name, so a guess: tried only after the
            # words the dictionary states.
            add(name, (rel, "out", "guess"))
            add(name, (rel, "in", "guess"))
    return idx


def parse(q: str, graph: dict, dictionary: dict) -> dict:
    """Read q into ordered items. {"items": [...], "tokens", "leftover", "tail_entities"}.
    Item: ("E", name, None) or ("R", [(rel, dir), ...], phrase)."""
    toks = _tokens(q)
    cut = len(toks)
    for pat in _CUT:
        for i in range(len(toks) - len(pat) + 1):
            if tuple(toks[i:i + len(pat)]) == pat:
                cut = min(cut, i)
    head, tail = toks[:cut], toks[cut:]
    ents = _entity_index(graph, dictionary)
    phr = _phrase_index(dictionary)
    maxlen = max([len(k) for k in list(ents) + list(phr)] + [1])

    def scan(ts):
        items, left, i = [], [], 0
        st = [_stem(t) for t in ts]
        while i < len(ts):
            hit = None
            for n in range(min(maxlen, len(ts) - i), 0, -1):
                e = ents.get(tuple(ts[i:i + n]))
                r = phr.get(tuple(st[i:i + n]))
                if e is not None and not (r is not None and e.islower()):
                    hit = (n, ("E", e, None))
                    break
                if r is not None:
                    hit = (n, ("R", list(r), " ".join(ts[i:i + n])))
                    break
            if hit:
                items.append(hit[1])
                i += hit[0]
            else:
                if ts[i] not in STOP:
                    left.append(ts[i])
                i += 1
        return items, left

    items, left = scan(head)
    t_items, _ = scan(tail)
    return {"items": items, "leftover": left, "tokens": toks,
            "tail_entities": [x[1] for x in t_items if x[0] == "E"]}


def mentions(q: str, graph: dict, dictionary: dict) -> dict:
    p = parse(q, graph, dictionary)
    ents, rels = [], []
    for it in p["items"]:
        if it[0] == "E":
            ents.append(it[1])
        else:
            for c in it[1]:
                if c not in rels:
                    rels.append(c)
    return {"entities": ents, "relations": rels}


# ------------------------------------------------------------------ walking

def _step(graph, dictionary, values, cands, prefer):
    """Apply one relation to a list of nodes. First candidate (in preference order)
    that yields anything wins. Returns (nodes, edge triples)."""
    rels = dictionary.get("relations") or {}
    order = sorted(cands, key=lambda c: (len(c) > 2, c[1] != prefer, cands.index(c)))
    for c in order:
        rel, d = c[0], c[1]
        name, flipped = _stored(rel, dictionary)
        if flipped:
            d = "in" if d == "out" else "out"
        sym = rels.get(rel, {}).get("symmetric") or rels.get(name, {}).get("symmetric")
        res, used = [], []
        for v in values:
            for e in graph.get("edges") or []:
                if e["rel"] != name:
                    continue
                hits = []
                if (d == "out" or sym) and e["s"] == v:
                    hits.append(e["o"])
                if (d == "in" or sym) and e["o"] == v:
                    hits.append(e["s"])
                for h in hits:
                    if h not in res:
                        res.append(h)
                    t = [e["s"], e["rel"], e["o"]]
                    if t not in used:
                        used.append(t)
        if res:
            return res, used
    return [], []


def _path(graph, a, b):
    adj = {}
    for e in graph.get("edges") or []:
        t = [e["s"], e["rel"], e["o"]]
        adj.setdefault(e["s"], []).append((e["o"], t))
        adj.setdefault(e["o"], []).append((e["s"], t))
    seen, dq = {a}, deque([(a, [a], [])])
    while dq:
        n, nodes, edges = dq.popleft()
        if n == b:
            return nodes, edges
        if len(edges) >= MAX_PATH:
            continue
        for m, t in sorted(adj.get(n, ()), key=lambda x: (x[0].lower(), x[1])):
            if m not in seen:
                seen.add(m)
                dq.append((m, nodes + [m], edges + [t]))
    return None


def _fold(values: list) -> list:
    """A bare first name folds into the one longer name that starts with it."""
    out = []
    for v in values:
        longer = [w for w in values if w != v and " " in w and " " not in v
                  and w.split()[0].lower() == v.lower()]
        if len(longer) != 1:
            out.append(v)
    return out


def _label(rel: str) -> str:
    return rel.replace("_", " ")


def walk(q: str, graph: dict, dictionary: dict) -> list[dict]:
    p = parse(q, graph, dictionary)
    toks, items = p["tokens"], p["items"]
    joined = " ".join(toks)

    ents = []
    for it in items:
        if it[0] == "E" and it[1] not in ents:
            ents.append(it[1])

    if re.search(r"\b(connected|related to|connection)\b", joined):
        if len(ents) < 2 or ents[0] == ents[1]:
            return []
        found = _path(graph, ents[0], ents[1])
        if not found or not found[1]:
            return []
        nodes, edges = found
        text = "; ".join(f"{s} {_label(r)} {o}" for s, r, o in edges)
        return [{"kind": "path", "answer": nodes, "chain": edges,
                 "restated": f"{ents[0]} to {ents[1]}: {text}"}]

    if not any(i[0] == "R" for i in items) or not ents:
        return []
    anchor, pending, post = None, [], []
    for it in items:
        if it[0] == "E":
            if anchor is None or it[1] == anchor:
                anchor = it[1]
            elif it[1] == SELF:
                continue
            else:  # a named entity replaces a pronoun or earlier name ("my son Ravi")
                anchor, post = it[1], []
        elif anchor is not None:
            post.append(it)
        else:
            pending.append(it)
    if anchor is None or not (pending or post):
        return []

    plan = [(it, "out") for it in post] + [(it, "in") for it in reversed(pending)]
    values, chain, phrases = [anchor], [], []
    ok = True
    for it, prefer in plan:
        values, used = _step(graph, dictionary, values, it[1], prefer)
        if not values:
            ok = False
            break
        chain += [t for t in used if t not in chain]
        phrases.append(it[2])
    if not ok:
        # The composed reading found nothing ("which company do I own": two words
        # naming one thing). Take what each relation word reaches on its own.
        values, chain, phrases = [], [], []
        for it, prefer in plan:
            vs, used = _step(graph, dictionary, [anchor], it[1], prefer)
            for v in vs:
                if v not in values:
                    values.append(v)
            chain += [t for t in used if t not in chain]
            if vs:
                phrases.append(it[2])
        if not values:
            return []
    values = _fold(values)

    kind_count = "how many" in joined
    who_else = "else" in toks
    if who_else:
        drop = {SELF, *p["tail_entities"]}
        values = [v for v in values if v not in drop]
        if not values:
            return []
    start = anchor
    body = "The " + " of the ".join(reversed(phrases)) + f" of {start}"
    if kind_count:
        return [{"kind": "count", "answer": str(len(values)), "chain": chain,
                 "restated": f"{body} (count): {len(values)}"}]
    if len(values) == 1 and not who_else:
        return [{"kind": "chain", "answer": values[0], "chain": chain,
                 "restated": f"{body}: {values[0]}"}]
    values = sorted(values, key=lambda x: (x.lower(), x))
    return [{"kind": "set", "answer": values, "chain": chain,
             "restated": f"{body}: {', '.join(values)}"}]
