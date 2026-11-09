"""Brain home, SQLite schema, JSON helpers."""
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, origin TEXT, added TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, text TEXT NOT NULL, about TEXT NOT NULL DEFAULT 'me',
  category TEXT NOT NULL, edge_s TEXT, edge_rel TEXT, edge_o TEXT, src TEXT, since TEXT,
  conf TEXT DEFAULT 'medium', by TEXT DEFAULT 'doc', status TEXT DEFAULT 'active',
  created TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS items_cat ON items(category);
CREATE INDEX IF NOT EXISTS items_about ON items(about);
CREATE INDEX IF NOT EXISTS items_status ON items(status);
CREATE TABLE IF NOT EXISTS held(token TEXT PRIMARY KEY, type TEXT, value TEXT, src TEXT);
CREATE TABLE IF NOT EXISTS categories(slug TEXT PRIMARY KEY, description TEXT);
CREATE TABLE IF NOT EXISTS rules(persona TEXT, category TEXT, decision TEXT, PRIMARY KEY(persona, category));
CREATE TABLE IF NOT EXISTS personas(slug TEXT PRIMARY KEY, audience TEXT, include TEXT, exclude TEXT, created TEXT);
"""


def home() -> Path:
    return Path(os.environ.get("TWIN_HOME", "~/.twin/brain")).expanduser()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init(home_: Path | None = None) -> Path:
    h = Path(home_) if home_ is not None else home()
    (h / "raw").mkdir(parents=True, exist_ok=True)
    (h / "personas").mkdir(exist_ok=True)
    for name in ("privacy.yaml", "schema.yaml"):
        src = TEMPLATES / name
        if not (h / name).exists() and src.exists():
            shutil.copyfile(src, h / name)
    con = sqlite3.connect(h / "raw" / "brain.sqlite")
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()
    if not (h / "dictionary.json").exists():
        write_json(h / "dictionary.json", {"relations": {}, "aliases": {}})
    return h


def db() -> sqlite3.Connection:
    h = init()
    con = sqlite3.connect(h / "raw" / "brain.sqlite")
    con.row_factory = sqlite3.Row
    # Overwrite deleted content so purged PII does not linger in free pages.
    con.execute("PRAGMA secure_delete=ON")
    return con


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, obj) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False), encoding="utf-8")
    os.replace(tmp, p)


def append_jsonl(path, obj) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def log(event: str, **kw) -> None:
    append_jsonl(home() / "log.jsonl", {"ts": now(), "event": event, **kw})


def persona_dir(slug: str) -> Path:
    return home() / "personas" / slug


def questions_path() -> Path:
    return home() / "questions.json"


def ledger_path() -> Path:
    return home() / "ledger.json"


def corrections_path() -> Path:
    return home() / "corrections.jsonl"


def dictionary_path() -> Path:
    return home() / "dictionary.json"


def active_path() -> Path:
    return home() / "active"


def privacy_path() -> Path:
    return home() / "privacy.yaml"


def schema_path() -> Path:
    return home() / "schema.yaml"
