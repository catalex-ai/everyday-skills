"""Raw store: sources, items, held values. Everything written passes through gate.redact."""
from . import gate, store
from .ids import fact_id, source_id

_COLS = ("id", "text", "about", "category", "edge_s", "edge_rel", "edge_o", "src", "since",
         "conf", "by", "status", "created", "updated")


def _save_held(con, rows, src=None):
    for h in rows:
        con.execute("INSERT OR IGNORE INTO held(token,type,value,src) VALUES(?,?,?,?)",
                    (h["token"], h["type"], h["value"], h["src"] or src))


def add_source(text: str, origin: str) -> str:
    red, held = gate.redact(text)
    sid = source_id(red)
    con = store.db()
    with con:
        con.execute(
            "INSERT INTO sources(id,origin,added,text) VALUES(?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET origin=excluded.origin",
            (sid, origin, store.now(), red))
        _save_held(con, held, sid)
    con.close()
    store.log("add_source", id=sid, origin=origin, held=len(held))
    return sid


def add_items(items: list[dict]) -> list[str]:
    con = store.db()
    try:
        known = sorted(r[0] for r in con.execute("SELECT slug FROM categories"))
        for it in items:
            if it["category"] not in known:
                raise ValueError(f"unknown category: {it['category']}; known: {known}")
        out = []
        with con:
            for it in items:
                src = it.get("src")
                text, held = gate.redact(it["text"], src)
                edge = it.get("edge")
                es = erel = eo = None
                if edge:
                    es, erel = edge.get("s"), edge.get("rel")
                    eo, h2 = gate.redact(edge["o"], src)
                    held += h2
                _save_held(con, held, src)
                iid = fact_id(text)
                out.append(iid)
                by = it.get("by", "doc")
                now = store.now()
                old = con.execute("SELECT by FROM items WHERE id=?", (iid,)).fetchone()
                if old and old["by"] == "you" and by != "you":
                    continue
                vals = (text, it.get("about", "me"), it["category"], es, erel, eo, src,
                        it.get("since"), it.get("conf", "medium"), by)
                if old:
                    con.execute(
                        "UPDATE items SET text=?,about=?,category=?,edge_s=?,edge_rel=?,edge_o=?,src=?,"
                        "since=?,conf=?,by=?,updated=? WHERE id=?", vals + (now, iid))
                else:
                    con.execute(
                        "INSERT INTO items(text,about,category,edge_s,edge_rel,edge_o,src,since,conf,by,"
                        "id,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,'active',?,?)",
                        vals + (iid, now, now))
    finally:
        con.close()
    store.log("add_items", n=len(out))
    return out


def _row(r) -> dict:
    d = {k: r[k] for k in _COLS if not k.startswith("edge_")}
    d["edge"] = ({"s": r["edge_s"], "rel": r["edge_rel"], "o": r["edge_o"]}
                 if any(r[k] is not None for k in ("edge_s", "edge_rel", "edge_o")) else None)
    return d


def items(status="active", categories: list[str] | None = None) -> list[dict]:
    where, args = [], []
    if status is not None:
        where.append("status=?")
        args.append(status)
    if categories is not None:
        where.append("category IN (%s)" % ",".join("?" * len(categories)))
        args += list(categories)
    sql = "SELECT * FROM items" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created, id"
    con = store.db()
    try:
        return [_row(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def get(item_id: str) -> dict | None:
    con = store.db()
    try:
        r = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return _row(r) if r else None
    finally:
        con.close()


def set_status(item_id: str, status: str) -> None:
    con = store.db()
    with con:
        con.execute("UPDATE items SET status=?, updated=? WHERE id=?", (status, store.now(), item_id))
    con.close()


def held_map() -> dict:
    con = store.db()
    try:
        return {r["token"]: r["value"] for r in con.execute("SELECT token,value FROM held")}
    finally:
        con.close()


def _demote(text, dropped):
    """Turn hold tokens of types now set to drop into plain drop tokens."""
    if text is None or not dropped:
        return text
    import re
    return re.sub(r"⟦(" + "|".join(map(re.escape, dropped)) + r"):[0-9a-f]+⟧", r"⟦\1⟧", text)


def apply_privacy() -> dict:
    con = store.db()
    ns = ni = 0
    dropped = sorted(t for t, m in gate.settings().items() if m == "drop")
    try:
        with con:
            for r in con.execute("SELECT id,text FROM sources").fetchall():
                new, held = gate.redact(r["text"], r["id"])
                new = _demote(new, dropped)
                _save_held(con, held)
                if new != r["text"]:
                    con.execute("UPDATE sources SET text=? WHERE id=?", (new, r["id"]))
                    ns += 1
            for r in con.execute("SELECT id,text,edge_o,src FROM items").fetchall():
                new, held = gate.redact(r["text"], r["src"])
                eo, h2 = (gate.redact(r["edge_o"], r["src"]) if r["edge_o"] is not None
                          else (None, []))
                new, eo = _demote(new, dropped), _demote(eo, dropped)
                _save_held(con, held + h2)
                if new != r["text"] or eo != r["edge_o"]:
                    con.execute("UPDATE items SET text=?, edge_o=?, updated=? WHERE id=?",
                                (new, eo, store.now(), r["id"]))
                    ni += 1
            if dropped:
                con.execute(f"DELETE FROM held WHERE type IN ({','.join('?'*len(dropped))})", dropped)
    finally:
        con.close()
    store.log("apply_privacy", sources=ns, items=ni)
    return {"sources": ns, "items": ni}


def stats() -> dict:
    con = store.db()
    try:
        def counts(col):
            return {r[0]: r[1] for r in con.execute(
                f"SELECT {col}, COUNT(*) FROM items GROUP BY {col} ORDER BY {col}")}
        by_status = counts("status")
        return {"total": sum(by_status.values()), "by_status": by_status, "by_category": counts("category")}
    finally:
        con.close()
