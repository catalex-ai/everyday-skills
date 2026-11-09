"""Housekeeping: duplicates, single-relation contradictions, thin categories."""
from . import graph, ids, policy, questions, raw


def _newest(its):
    return max(its, key=lambda i: (i.get("updated") or "", i.get("created") or "", i["id"]))


def run() -> dict:
    merged = 0
    groups: dict[str, list] = {}
    for it in raw.items():
        groups.setdefault(ids.norm(it["text"]), []).append(it)
    for its in groups.values():
        if len(its) < 2:
            continue
        mine = [i for i in its if i["by"] == "you"]
        keep = _newest(mine or its)
        for i in its:
            if i["id"] != keep["id"]:
                raw.set_status(i["id"], "superseded")
                merged += 1

    dic = policy.dictionary()
    rels = dic["relations"]
    superseded = 0
    mine: dict[tuple, set] = {}
    items = raw.items()
    for i in items:
        e = i.get("edge")
        if i["by"] == "you" and e and (rels.get(e.get("rel")) or {}).get("single"):
            mine.setdefault((graph.canonical(e["s"], dic), e["rel"]), set()).add(graph.canonical(e["o"], dic).lower())
    for i in items:
        e = i.get("edge")
        if i["by"] == "you" or not e or not (rels.get(e.get("rel")) or {}).get("single"):
            continue
        key = (graph.canonical(e["s"], dic), e["rel"])
        if key in mine and graph.canonical(e["o"], dic).lower() not in mine[key]:
            raw.set_status(i["id"], "superseded")
            superseded += 1

    active = {}
    for i in raw.items():
        active[i["category"]] = active.get(i["category"], 0) + 1
    suggestions = [{"category": c, "items": active.get(c, 0)}
                   for c in sorted(policy.categories()) if active.get(c, 0) < 2]
    sync = questions.sync()
    return {"merged": merged, "superseded": superseded, "merge_suggestions": suggestions,
            "personas": len(sync)}
