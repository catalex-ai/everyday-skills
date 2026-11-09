"""Static audit page plus a PII re-scan of the whole brain. Never prints held values."""
import html
import re
from pathlib import Path

from . import gate, policy, questions, raw, store

_SKIP_EXT = {".npy"}
_PRINTABLE = re.compile(r"[\x20-\x7e -\U0010ffff]{8,}")


def _text_of(path: Path) -> str | None:
    if path.suffix in _SKIP_EXT:
        return None
    data = path.read_bytes()
    if path.suffix == ".sqlite" or b"\x00" in data[:8192]:
        s = data.decode("utf-8", "ignore")
        return "\n".join(_PRINTABLE.findall(s)) if path.suffix == ".sqlite" else None
    return data.decode("utf-8", "ignore")


def _bad_types() -> set:
    return {t for t, m in gate.settings().items() if m in ("hold", "drop")}


def scan_brain() -> list[dict]:
    bad, home, out = _bad_types(), store.home(), []
    skip = {home / "raw" / "brain.sqlite", home / "audit.html",
            home / "privacy.yaml"}  # config: its own detection patterns and "password: drop" would self-match
    for p in sorted(home.rglob("*")):
        if not p.is_file() or p in skip or p.name.endswith(".tmp") or p.name.startswith("brain.sqlite"):
            continue
        text = _text_of(p)
        if text is None:
            continue
        rel = str(p.relative_to(home))
        for n, line in enumerate(text.splitlines(), 1):
            for f in gate.scan(line):
                if f["type"] in bad:
                    out.append({"file": rel, "line": n, "type": f["type"]})
    con = store.db()
    try:
        for n, r in enumerate(con.execute("SELECT id,text FROM sources ORDER BY id"), 1):
            for f in gate.scan(r["text"] or ""):
                if f["type"] in bad:
                    out.append({"file": "raw/brain.sqlite:sources", "line": n, "type": f["type"]})
        for n, r in enumerate(con.execute("SELECT id,text,edge_o FROM items ORDER BY created,id"), 1):
            for col in ("text", "edge_o"):
                for f in gate.scan(r[col] or ""):
                    if f["type"] in bad:
                        out.append({"file": f"raw/brain.sqlite:items.{col}", "line": n, "type": f["type"]})
    finally:
        con.close()
    return out


def _mask(text: str) -> str:
    bad = _bad_types()
    out, last = [], 0
    for f in gate.scan(text):
        if f["type"] in bad:
            out += [text[last:f["start"]], f"[{f['type']}]"]
            last = f["end"]
    out.append(text[last:])
    return "".join(out)


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


CSS = """
:root{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e2dc;--ok:#1f7a45;--bad:#b3261e;--warn:#9a6700;--acc:#2f5fb3}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--mut:#9a9a93;--card:#1f1f1d;--line:#34332f;--ok:#58c27d;--bad:#ff7b72;--warn:#e3b341;--acc:#7aa2f7}}
*{box-sizing:border-box}body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto}h1{font-size:1.5rem;margin:0 0 16px}h2{font-size:1.1rem;margin:28px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-x:auto}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:.85rem}.banner{padding:12px 16px;border-radius:10px;font-weight:600;border:1px solid var(--line)}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.mut{color:var(--mut)}.tag{font-size:.75rem;border:1px solid var(--acc);color:var(--acc);border-radius:999px;padding:1px 8px;margin-left:6px}
details{margin:6px 0}summary{cursor:pointer;font-weight:600}li{margin:2px 0}code{font-size:.85em}
"""


def run() -> dict:
    home = store.home()
    findings = scan_brain()
    try:
        active = policy.active()
    except policy.NoActivePersona:
        active = None
    items = raw.items()
    personas = policy.personas()
    cats = policy.categories()
    modes = gate.settings()
    counts = {p["slug"]: questions.counts(p["slug"], items) for p in personas}
    qs = questions.all("open")
    rules = {p["slug"]: policy.rules(p["slug"]) for p in personas}

    h = [f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>Twin audit</title><style>{CSS}</style></head><body><main><h1>Twin audit</h1>"]
    if findings:
        h.append(f"<div class='banner bad'>PII check: {len(findings)} finding(s) of types set to hold or drop</div>")
        h.append("<div class=card><table><tr><th>File</th><th>Line</th><th>Type</th></tr>"
                 + "".join(f"<tr><td><code>{_e(f['file'])}</code></td><td>{f['line']}</td><td>{_e(f['type'])}</td></tr>"
                           for f in findings) + "</table></div>")
    else:
        h.append("<div class='banner ok'>PII check passed: no raw hold or drop values found anywhere in the brain</div>")

    h.append("<h2>Privacy modes</h2><div class=card><table><tr><th>Type</th><th>Mode</th></tr>"
             + "".join(f"<tr><td>{_e(t)}</td><td>{_e(m)}</td></tr>" for t, m in modes.items()) + "</table></div>")

    h.append("<h2>Personas</h2><div class=card><table><tr><th>Persona</th><th>Allowed</th><th>Waiting</th><th>Denied</th></tr>")
    for p in personas:
        c = counts[p["slug"]]
        tag = "<span class=tag>active</span>" if p["slug"] == active else ""
        h.append(f"<tr><td>{_e(p['slug'])}{tag}</td><td>{c['allowed']}</td><td>{c['waiting']}</td><td>{c['denied']}</td></tr>")
    h.append("</table></div>")

    h.append("<h2>Category rules</h2><div class=card><table><tr><th>Category</th>"
             + "".join(f"<th>{_e(p['slug'])}</th>" for p in personas) + "</tr>")
    for c in sorted({*cats, *(i["category"] for i in items)}):
        cells = []
        for p in personas:
            d = rules[p["slug"]].get(c)
            cells.append(f"<td class={'ok' if d == 'allow' else 'bad' if d == 'deny' else 'mut'}>{d or '–'}</td>")
        h.append(f"<tr><td>{_e(c)}</td>{''.join(cells)}</tr>")
    h.append("</table></div>")

    h.append(f"<h2>Open questions ({len(qs)})</h2><div class=card>")
    h.append("<ul>" + "".join(f"<li><b>{_e(q['kind'])}</b> {_e(_mask(q['text']))}</li>" for q in qs) + "</ul>"
             if qs else "<span class=mut>None</span>")
    h.append("</div><h2>Facts per persona</h2>")
    for p in personas:
        facts = store.read_jsonl(store.persona_dir(p["slug"]) / "facts.jsonl")
        h.append(f"<details class=card><summary>{_e(p['slug'])} ({len(facts)})</summary><ul>"
                 + "".join(f"<li>{_e(_mask(f['text']))} <span class=mut>[{_e(f['category'])}]</span></li>" for f in facts)
                 + "</ul></details>")
    log = store.read_jsonl(home / "log.jsonl")[-30:]
    h.append("<h2>Recent log</h2><div class=card><table><tr><th>When</th><th>Event</th><th>Detail</th></tr>")
    for r in reversed(log):
        detail = ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("ts", "event"))
        h.append(f"<tr><td class=mut>{_e(r.get('ts'))}</td><td>{_e(r.get('event'))}</td><td>{_e(_mask(detail))}</td></tr>")
    h.append("</table></div></main></body></html>")

    path = home / "audit.html"
    path.write_text("\n".join(h), encoding="utf-8")
    return {"pii_findings": findings, "personas": counts, "waiting": sum(c["waiting"] for c in counts.values()),
            "open_questions": len(qs), "path": str(path)}
