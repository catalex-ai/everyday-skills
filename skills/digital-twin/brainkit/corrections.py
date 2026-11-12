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


def _material_counts() -> dict:
    c = {"example": 0, "opinion": 0, "story": 0}
    for i in raw.items():
        if i.get("kind") in c:
            c[i["kind"]] += 1
    return c


NEW_MATERIAL = 3


def stale_texts() -> list[str]:
    """Persona voice/soul texts that new real messages, opinions or stories have
    overtaken. Voice follows examples; soul follows opinions and stories."""
    now = _material_counts()
    st = store.read_json(store.home() / "voice_state.json", {})
    out = []
    for p in policy.personas():
        slug = p["slug"]
        last = st.get(slug, {})
        v, so = last.get("voice"), last.get("soul")
        if now["example"] and (v is None or now["example"] - v.get("example", 0) >= NEW_MATERIAL):
            out.append(f"{slug}/voice")
        if now["opinion"] + now["story"] and (so is None or (now["opinion"] + now["story"])
                                              - (so.get("opinion", 0) + so.get("story", 0)) >= NEW_MATERIAL):
            out.append(f"{slug}/soul")
    return out


def stale_hint() -> str | None:
    s = stale_texts()
    if not s:
        return None
    return ("Out of date: " + ", ".join(s) + ". New real messages, opinions or stories came in since "
            "these were written. When this batch is done, rewrite each with write_persona_text from the "
            "examples, opinions and stories (observable habits with how often and with whom; values "
            "and stances in the first person).")


def write_text(persona: str, part: str, text: str) -> dict:
    """Whole-file write of soul/voice/rules. Held and dropped values are redacted."""
    if part not in ("soul", "voice", "rules"):
        raise ValueError("part must be soul, voice or rules")
    if policy.persona(persona) is None:
        raise ValueError(f"unknown persona: {persona}")
    body = gate.strip_tokens(gate.redact(str(text))[0]).strip()
    p = store.persona_dir(persona) / f"{part}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# {part.capitalize()}\n{body}\n", encoding="utf-8")
    store.append_jsonl(store.corrections_path(), {"ts": store.now(), "target": part, "persona": persona,
                                                  "said": "", "should": "(rewritten)", "payload": {}})
    st = store.read_json(store.home() / "voice_state.json", {})
    st.setdefault(persona, {})[part] = _material_counts()
    store.write_json(store.home() / "voice_state.json", st)
    store.log("write_text", persona=persona, part=part)
    return {"ok": True, "persona": persona, "part": part, "chars": len(body)}


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
