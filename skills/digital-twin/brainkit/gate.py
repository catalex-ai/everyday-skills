"""PII gate: detection and per-type modes (allow | hold | drop). Patterns live in privacy.yaml."""
import hashlib
import re

import yaml

from . import store

TYPES = ("email", "phone", "address", "password", "bank_account", "card", "gov_id")
MODES = ("allow", "hold", "drop")
# Earlier types win when spans overlap.
PRIORITY = ("card", "bank_account", "gov_id", "password", "email", "address", "phone")

TOKEN_RE = re.compile(r"⟦[a-z_]+(?::[0-9a-f]{6})?⟧")
_HOLD_RE = re.compile(r"⟦([a-z_]+):([0-9a-f]{6})⟧")


def _template() -> dict:
    return yaml.safe_load((store.TEMPLATES / "privacy.yaml").read_text(encoding="utf-8")) or {}


def _config() -> dict:
    cfg = _template()
    p = store.privacy_path()
    if p.exists():
        mine = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cfg["modes"] = {**cfg.get("modes", {}), **(mine.get("modes") or {})}
        cfg["patterns"] = {**cfg.get("patterns", {}), **(mine.get("patterns") or {})}
        if "luhn" in mine:
            cfg["luhn"] = mine["luhn"]
    return cfg


def settings() -> dict:
    modes = _config().get("modes", {})
    return {t: modes.get(t, "allow") for t in TYPES}


def set_mode(type: str, mode: str) -> None:
    if type not in TYPES:
        raise ValueError(f"unknown PII type: {type}; known: {list(TYPES)}")
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}; known: {list(MODES)}")
    store.init()
    p = store.privacy_path()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.setdefault("modes", {})[type] = mode
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tmp.replace(p)


def _luhn(s: str) -> bool:
    d = [int(c) for c in s if c.isdigit()]
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _mask(text: str) -> tuple[str, list[tuple[int, int]]]:
    spans = [m.span() for m in TOKEN_RE.finditer(text)]
    masked = TOKEN_RE.sub(lambda m: "\x00" * len(m.group()), text)
    return masked, spans


def scan(text: str) -> list[dict]:
    cfg = _config()
    pats, luhn = cfg.get("patterns", {}), set(cfg.get("luhn") or [])
    masked, tokens = _mask(text)
    taken: list[tuple[int, int, str]] = []

    def free(s, e):
        return not any(s < te and ts < e for ts, te in tokens) and \
            not any(s < te and ts < e for ts, te, _ in taken)

    for t in PRIORITY:
        for pat in pats.get(t, []):
            for m in re.finditer(pat, masked):
                s, e = m.span("v") if "v" in m.re.groupindex else m.span()
                if s == e or not free(s, e):
                    continue
                if t in luhn and not _luhn(masked[s:e]):
                    continue
                taken.append((s, e, t))
    return [{"type": t, "start": s, "end": e} for s, e, t in sorted(taken)]


def redact(text: str, src=None) -> tuple[str, list[dict]]:
    modes = settings()
    out, held, last = [], [], 0
    for f in scan(text):
        mode = modes.get(f["type"], "allow")
        if mode == "allow":
            continue
        value = text[f["start"]:f["end"]]
        if mode == "hold":
            token = f"⟦{f['type']}:{hashlib.sha1(value.encode()).hexdigest()[:6]}⟧"
            held.append({"token": token, "type": f["type"], "value": value, "src": src})
        else:
            token = f"⟦{f['type']}⟧"
        out.append(text[last:f["start"]])
        out.append(token)
        last = f["end"]
    out.append(text[last:])
    return "".join(out), held


def _tidy(text: str) -> str:
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,;.:!?])", r"\1", text)
    text = re.sub(r"([,;])(?:\s*[,;])+", r"\1", text)
    return text.strip()


def strip_tokens(text: str) -> str:
    return _tidy(TOKEN_RE.sub("", text))


def unhold(text: str, held: dict, modes: dict | None = None) -> str:
    modes = modes if modes is not None else settings()
    removed = False

    def sub(m):
        nonlocal removed
        h = _HOLD_RE.fullmatch(m.group())
        if h and modes.get(h.group(1)) == "allow" and m.group() in held:
            return held[m.group()]
        removed = True
        return ""

    out = TOKEN_RE.sub(sub, text)
    return _tidy(out) if removed else out
