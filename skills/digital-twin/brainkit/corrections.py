"""Owner corrections: logged, then routed to the file or table they change."""
import yaml

from . import build, gate, policy, questions, raw, store

TARGETS = ("voice", "rules", "item", "category", "schema", "soul", "privacy")


def _clean(text) -> str:
    return gate.strip_tokens(gate.redact(str(text))[0]) if text else ""


def _append_line(persona, target, line) -> str:
    if not persona:
        raise ValueError(f"persona is required for target {target}")
    if policy.persona(persona) is None:
        raise ValueError(f"unknown persona: {persona}")
    p = store.persona_dir(persona) / f"{target}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = p.read_text(encoding="utf-8") if p.exists() else ""
    if cur and not cur.endswith("\n"):
        cur += "\n"
    p.write_text(cur + line + "\n", encoding="utf-8")
    return f"appended to personas/{persona}/{target}.md"


def _item(said, should, payload) -> str:
    old = raw.get(payload["id"]) if payload.get("id") else None
    if payload.get("id") and old is None:
        raise ValueError(f"unknown item: {payload['id']}")
    category = payload.get("category") or (old or {}).get("category")
    if not category:
        raise ValueError("item correction needs payload id or category")
    text = payload.get("text") or should
    if not text:
        raise ValueError("item correction needs corrected text")
    new = {"text": text, "category": category, "by": "you",
           "about": payload.get("about") or (old or {}).get("about") or "me",
           "edge": payload.get("edge") or (old or {}).get("edge"),
           "since": payload.get("since") or (old or {}).get("since"),
           "src": (old or {}).get("src")}
    [nid] = raw.add_items([new])
    if old and old["id"] != nid:
        raw.set_status(old["id"], "superseded")
    questions.sync()
    return f"item {nid} written by you" + (f"; {old['id']} superseded" if old and old["id"] != nid else "")


def record(said, should, target, persona=None, payload=None) -> dict:
    if target not in TARGETS:
        raise ValueError(f"unknown target: {target}; known: {list(TARGETS)}")
    payload = payload or {}
    said, should = _clean(said), _clean(should)
    store.append_jsonl(store.corrections_path(), {
        "ts": store.now(), "target": target, "persona": persona, "said": said, "should": should,
        "payload": {k: v for k, v in payload.items() if k in ("id", "persona", "category", "type", "mode")}})
    if target in ("voice", "rules", "soul"):
        line = _clean(payload["line"]) if payload.get("line") else f"- When: {said} → Instead: {should}"
        applied = _append_line(persona, target, line)
    elif target == "item":
        applied = _item(said, should, payload)
    elif target == "category":
        policy.set_rule(payload["persona"], payload["category"], payload["decision"])
        questions.sync()
        applied = f"rule {payload['persona']}/{payload['category']} = {payload['decision']}"
    elif target == "schema":
        y = payload["yaml"]
        new = yaml.safe_load(y) if isinstance(y, str) else y
        if not isinstance(new, dict):
            raise ValueError("schema payload must be a mapping")
        store.init()
        p = store.schema_path()
        cur = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
        cur.update(new)
        p.write_text(yaml.safe_dump(cur, sort_keys=False, allow_unicode=True), encoding="utf-8")
        questions.refresh_gaps()
        applied = "schema updated: " + ", ".join(sorted(new))
    else:  # privacy
        gate.set_mode(payload["type"], payload["mode"])
        r = raw.apply_privacy()
        build.rebuild_all()
        applied = f"{payload['type']} = {payload['mode']}; re-scanned {r['sources']} sources, {r['items']} items"
    store.log("correction", target=target, persona=persona)
    return {"target": target, "applied": applied}
