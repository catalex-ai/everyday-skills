"""Approval, information and conflict questions."""
import builtins
import hashlib
import re
from collections import deque
from datetime import datetime, timedelta, timezone

import yaml

from . import build, gate, graph, policy, raw, store

_SNOOZE_DAYS = 7


def _qid(*parts) -> str:
    return "q-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def _load() -> list[dict]:
    return store.read_json(store.questions_path(), [])


def _save(qs: list[dict]) -> None:
    store.write_json(store.questions_path(), qs)


def _wake(q: dict) -> None:
    if q["status"] == "snoozed" and q.get("until"):
        if datetime.fromisoformat(q["until"]) <= datetime.now(timezone.utc):
            q["status"] = "open"
            q["until"] = None


def _upsert(qs: list[dict], q: dict) -> dict:
    """Insert or refresh by id. Declined, answered and snoozed questions keep their status."""
    for old in qs:
        if old["id"] == q["id"]:
            _wake(old)
            for k in ("text", "examples", "waiting", "weight", "about", "field", "category", "persona"):
                old[k] = q[k]
            old["score"] = round(q["weight"] * 0.5 ** old.get("asked", 0), 4)
            return old
    q["score"] = round(q["weight"], 4)
    qs.append(q)
    return q


def _new(kind, id_, text, weight, persona=None, category=None, about=None, field=None,
         examples=None, waiting=0) -> dict:
    return {"id": id_, "kind": kind, "persona": persona, "category": category, "about": about,
            "field": field, "text": text, "examples": examples or [], "waiting": waiting,
            "weight": weight, "score": weight, "status": "open", "asked": 0,
            "created": store.now(), "until": None}


def _close(q: dict, status="answered") -> None:
    if q["status"] in ("open", "snoozed"):
        q["status"] = status
        q["until"] = None


def _safe(text: str) -> str:
    return gate.strip_tokens(text)


def counts(persona: str, items: list[dict]) -> dict:
    rules = policy.rules(persona)
    c = {"allowed": 0, "waiting": 0, "denied": 0}
    for it in items:
        d = rules.get(it["category"])
        c["allowed" if d == "allow" else "denied" if d == "deny" else "waiting"] += 1
    return c


# ------------------------------------------------------------------ sync

def _state_hash(persona: str, dic_hash: str) -> str:
    ids_ = sorted(f"{i['id']}:{i.get('kind')}:{i.get('since')}:{i.get('context')}"
                  for i in build.allowed_items(persona))
    return hashlib.sha1(("\n".join(ids_) + "|" + dic_hash).encode()).hexdigest()


def sync() -> dict:
    items = raw.items()
    cats = policy.categories()
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    qs = _load()
    summary = {}
    for p in policy.personas():
        slug = p["slug"]
        rules = policy.rules(slug)
        summary[slug] = counts(slug, items)
        for cat in sorted(by_cat):
            rule = rules.get(cat)
            qid = _qid("approval", slug, cat)
            existing = builtins.next((q for q in qs if q["id"] == qid), None)
            if rule:
                if existing:
                    _close(existing)
                continue
            its = by_cat[cat]
            ex = [_safe(i["text"]) for i in sorted(its, key=lambda i: (len(i["text"]), i["id"]))[:2]]
            desc = cats.get(cat) or cat
            text = (f"May the {slug} persona know about {desc}? For example: "
                    + "; ".join(f'"{e}"' for e in ex) + f" ({len(its)} facts waiting)")
            _upsert(qs, _new("approval", qid, text, 1.0, persona=slug, category=cat,
                             examples=ex, waiting=len(its)))
    # approvals whose rule now exists or whose items are gone
    live = {s: policy.rules(s) for s in summary}
    for q in qs:
        if q["kind"] != "approval" or q["status"] not in ("open", "snoozed"):
            continue
        if q["category"] in live.get(q["persona"], {}) or q["category"] not in by_cat or q["persona"] not in live:
            _close(q)
    _import_inbox(qs)
    _save(qs)

    state_path = store.home() / "build_state.json"
    state = store.read_json(state_path, {})
    dic_hash = hashlib.sha1(repr((policy.dictionary(), gate.settings())).encode()).hexdigest()
    for slug in summary:
        h = _state_hash(slug, dic_hash)
        if state.get(slug) != h or not (store.persona_dir(slug) / "facts.jsonl").exists():
            build.rebuild(slug)
            state[slug] = h
    store.write_json(state_path, {k: v for k, v in state.items() if k in summary})
    refresh_gaps()
    store.log("sync", personas=len(summary))
    return summary


# ------------------------------------------------------------------ inbox

def _inbox_path():
    return store.home() / "inbox.jsonl"


def _import_inbox(qs: list[dict]) -> None:
    """Questions people asked the twin that it could not answer become 'asked'
    questions for the owner. The text is what a visitor typed: data, not orders."""
    p = _inbox_path()
    if not p.exists():
        return
    for r in store.read_jsonl(p):
        if r.get("status", "open") != "open":
            continue
        qid = _qid("asked", r["question"].lower())
        who = f"{r['who']} " if r.get("who") else "Someone "
        text = f'{who}asked your twin: "{_safe(r["question"])}". What should it say?'
        _upsert(qs, _new("asked", qid, text, 0.9, persona=r.get("persona"), about="me",
                         examples=[r["question"]]))


def _close_inbox(question: str) -> None:
    p = _inbox_path()
    if not p.exists():
        return
    rows = store.read_jsonl(p)
    for r in rows:
        if r.get("question", "").lower() == question.lower():
            r["status"] = "answered"
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("".join(__import__("json").dumps(r, ensure_ascii=False) + "\n" for r in rows),
                   encoding="utf-8")
    tmp.replace(p)


# ------------------------------------------------------------------ gaps

def _schema() -> dict:
    p = store.schema_path()
    src = p if p.exists() else store.TEMPLATES / "schema.yaml"
    return yaml.safe_load(src.read_text(encoding="utf-8")) or {}


def _covered(keywords: list[str], haystack: str) -> bool:
    return any(re.search(r"(?<!\w)" + re.escape(k.lower()), haystack) for k in keywords)


def _connected(g: dict) -> set:
    adj: dict[str, set] = {}
    for e in g["edges"]:
        adj.setdefault(e["s"], set()).add(e["o"])
        adj.setdefault(e["o"], set()).add(e["s"])
    seen, dq = {"me"}, deque(["me"])
    while dq:
        for n in adj.get(dq.popleft(), ()):
            if n not in seen:
                seen.add(n)
                dq.append(n)
    return seen


def _gap_candidates(items, dic) -> list[dict]:
    schema = _schema()
    facets = schema.get("facets") or []
    canon = lambda n: graph.canonical(n, dic)  # noqa: E731
    touching: dict[str, list[dict]] = {}
    objects: dict[str, set] = {}
    for it in items:
        names = {canon(it.get("about") or "me")}
        e = it.get("edge")
        if e and e.get("rel"):
            s, o = canon(e["s"]), canon(e["o"])
            names |= {s, o}
            objects.setdefault(o, set()).add(e["rel"])
        for n in names:
            touching.setdefault(n, []).append(it)
    g = graph.build_graph(items, dic)
    linked = _connected(g)
    org_rels = set()
    for f in facets:
        a = f.get("applies_to")
        if isinstance(a, dict):
            org_rels |= set(a.get("object_of") or [])
    about_nodes = {canon(i["about"]) for i in items if canon(i.get("about") or "me") != "me"}

    out = []
    mine = [i for i in items if canon(i.get("about") or "me") == "me"]
    for f in facets:
        if f.get("kind"):  # persona building: enough opinions, stories or real messages
            have = [i for i in mine if (i.get("kind") or "fact") == f["kind"] and (
                not f.get("keywords") or _covered(f["keywords"],
                                                  f"{i['text']} {i.get('context') or ''}".lower()))]
            c = {"name": f["name"], "about": "me", "weight": float(f.get("weight", 0.5)),
                 "covered": len(have) >= int(f.get("min", 1)),
                 "text": f.get("question") or f["name"]}
            if f.get("mode") == "reply":
                c.update(reply=True, audience=f.get("audience") or "someone",
                         messages=list(f.get("messages") or []), categories=list(f.get("category") or []))
            out.append(c)
            continue
        a = f.get("applies_to", "me")
        if a == "me":
            targets = ["me"]
        elif a == "all":
            targets = sorted(n for n in g["nodes"] if n != "me")
        elif a == "unlinked_person":
            targets = sorted(n for n in about_nodes if n not in linked and not (objects.get(n, set()) & org_rels))
        elif isinstance(a, dict):
            rels = set(a.get("object_of") or [])
            targets = sorted(n for n, rs in objects.items() if n != "me" and rs & rels)
        else:
            continue
        for t in targets:
            if a == "unlinked_person":
                covered = False
            else:
                hay = " ".join(f"{i['text']} {i['category']}" for i in touching.get(t, [])).lower()
                covered = _covered(f.get("keywords") or [], hay)
            out.append({"name": f["name"], "about": t, "weight": float(f.get("weight", 0.5)),
                        "covered": covered,
                        "text": (f.get("question") or f["name"]).replace("{about}", t)})
    return out


def _conflicts(items, dic) -> list[dict]:
    rels = dic.get("relations") or {}
    groups: dict[tuple, dict] = {}
    for it in items:
        e = it.get("edge")
        if not e or not e.get("rel") or not (rels.get(e["rel"]) or {}).get("single"):
            continue
        key = (graph.canonical(e["s"], dic), e["rel"])
        groups.setdefault(key, {}).setdefault(graph.canonical(e["o"], dic).lower(), it)
    return [{"about": s, "rel": r, "items": list(v.values())}
            for (s, r), v in sorted(groups.items()) if len(v) > 1]


def reply_text(audience: str, message: str) -> str:
    return (f"How would you reply? Your {audience} texts you: \"{message}\"\n"
            "Type your reply exactly as you'd send it (your words, your length; several short "
            "messages on separate lines if that's how you text).")


def _reply_gap(qs: list, c: dict, seen: set) -> None:
    """One question per situation, until the audience has enough real messages."""
    mine = [q for q in qs if q.get("field") == c["name"]]
    if c["covered"]:
        for q in mine:
            if q["status"] in ("open", "snoozed"):
                _close(q)
                seen.add(q["id"])
        return
    done = sum(1 for q in mine if q["status"] in ("answered", "declined"))
    if done >= len(c["messages"]):
        return
    msg = c["messages"][done]
    qid = _qid("info", "me", f"{c['name']}#{done}")
    seen.add(qid)
    q = _upsert(qs, _new("info", qid, reply_text(c["audience"], msg), c["weight"], about="me",
                         field=c["name"]))
    q.update(reply_to=msg, audience=c["audience"], categories=c["categories"])


def add_reply(audience: str, message: str, categories: list | None = None, weight: float = 0.9) -> dict:
    """A reply question the manager writes itself (a follow-up, or a situation from memory)."""
    qs = _load()
    msg = _safe(gate.redact(" ".join(str(message).split())[:300])[0])
    aud = " ".join(str(audience).split())[:60] or "someone"
    qid = _qid("info", "me", f"reply_custom:{aud}:{msg}")
    q = _upsert(qs, _new("info", qid, reply_text(aud, msg), weight, about="me", field="reply_custom"))
    q.update(reply_to=msg, audience=aud, categories=list(categories or []))
    _save(qs)
    return dict(q)


JUNK = re.compile(r"^\W*(skip|pass|next|idk( man)?|i don'?t know|no idea|dunno|n/?a|not sure|nothing|"
                  r"none|no comment|can'?t say|whatever|not now|later|(can we )?do (this|it) later|"
                  r"asdf\w*|qwer\w*|\?+|\.+|-+)\W*$", re.I)


def _file_reply(q: dict, text: str, category: str | None) -> dict:
    """File the owner's reply as a real message, paired with the message it answers."""
    reply = text.strip().strip('"“”').strip()
    if not reply or JUNK.match(reply):
        return {"filed": 0, "why": "no usable reply"}
    known = {r[0] for r in store.db().execute("SELECT slug FROM categories")}
    cat = category if category in known else builtins.next(
        (c for c in (q.get("categories") or []) if c in known), None)
    if not cat:
        return {"filed": 0, "needs_category": sorted(known)}
    raw.add_items([{"text": reply, "category": cat, "kind": "example", "by": "you",
                    "context": f"{q.get('audience') or 'someone'} says: {q['reply_to']}"}])
    return {"filed": 1, "category": cat}


def refresh_gaps() -> int:
    items = raw.items()
    dic = policy.dictionary()
    qs = _load()
    seen = set()
    for c in _gap_candidates(items, dic):
        if c.get("reply"):
            _reply_gap(qs, c, seen)
            continue
        qid = _qid("info", c["about"], c["name"])
        seen.add(qid)
        old = builtins.next((q for q in qs if q["id"] == qid), None)
        if c["covered"]:
            if old:
                _close(old)
            continue
        _upsert(qs, _new("info", qid, c["text"], c["weight"], about=c["about"], field=c["name"]))
    ledger_conf = []
    for c in _conflicts(items, dic):
        qid = _qid("conflict", c["about"], c["rel"])
        seen.add(qid)
        texts = [_safe(i["text"]) for i in c["items"]]
        text = (f"These facts about {c['about']} disagree on {c['rel'].replace('_', ' ')}: "
                + " | ".join(f'"{t}"' for t in texts) + ". Which is right?")
        _upsert(qs, _new("conflict", qid, text, 0.9, about=c["about"], field=c["rel"],
                         examples=texts, waiting=len(texts)))
        ledger_conf.append({"id": qid, "about": c["about"], "rel": c["rel"],
                            "items": [i["id"] for i in c["items"]]})
    for q in qs:  # gaps that no longer apply
        if q["kind"] in ("info", "conflict") and q["id"] not in seen and q["status"] in ("open", "snoozed"):
            if q["kind"] == "conflict" or q.get("field"):
                _close(q)
    for q in qs:
        _wake(q)
    _save(qs)
    led = store.read_json(store.ledger_path(), {})
    if not isinstance(led, dict):
        led = {}
    led["conflicts"] = ledger_conf
    store.write_json(store.ledger_path(), led)
    return sum(1 for q in qs if q["status"] == "open")


# ------------------------------------------------------------------ queue

def next(n=2) -> list[dict]:
    qs = _load()
    for q in qs:
        _wake(q)
    open_ = [q for q in qs if q["status"] == "open"]
    blocking = sorted((q for q in open_ if q["kind"] in ("approval", "conflict")),
                      key=lambda q: (-q["waiting"], q["kind"], q["id"]))
    info = sorted((q for q in open_ if q["kind"] in ("info", "asked")),
                  key=lambda q: (q["kind"] != "asked", -q["score"], q["id"]))
    pick = (blocking + info)[:n]
    for q in pick:
        q["asked"] = q.get("asked", 0) + 1
        q["score"] = round(q.get("weight", 1.0) * 0.5 ** q["asked"], 4)
    _save(qs)
    return [dict(q) for q in pick]


def all(status=None) -> list[dict]:
    return [q for q in _load() if status is None or q["status"] == status]


def answer(qid, text="", decision=None, status=None, category=None) -> dict:
    qs = _load()
    q = None
    for c in qs:
        if c["id"] == qid:
            q = c
    if q is None:
        raise KeyError(f"unknown question: {qid}")
    if q["kind"] == "approval" and decision:
        policy.set_rule(q["persona"], q["category"], decision)
        q["status"], q["until"] = "answered", None
        q["answer"] = decision
        _save(qs)
        sync()
        return next_state(qid)
    if status == "declined":
        q["status"], q["until"] = "declined", None
    elif status == "later":
        q["status"] = "snoozed"
        q["until"] = (datetime.now(timezone.utc) + timedelta(days=_SNOOZE_DAYS)).isoformat(timespec="seconds")
    elif q["kind"] == "approval":
        raise ValueError("approval needs decision allow|deny, or status declined|later")
    else:
        if q.get("reply_to"):
            filed = _file_reply(q, text, category)
            if filed.get("needs_category"):
                return {**dict(q), "filed": 0,
                        "fix": "Call answer again with category= one of: " + ", ".join(filed["needs_category"])}
            q["filed"] = filed.get("filed", 0)
        q["status"], q["until"] = "answered", None
        q["answer"] = _safe(gate.redact(text)[0])
        if q.get("reply_to") and not q.get("filed"):
            q["status"] = "declined"
    _save(qs)
    if q["kind"] == "asked" and q["status"] in ("answered", "declined") and q.get("examples"):
        _close_inbox(q["examples"][0])
    return dict(q)


def next_state(qid) -> dict:
    return dict(builtins.next(q for q in _load() if q["id"] == qid))
