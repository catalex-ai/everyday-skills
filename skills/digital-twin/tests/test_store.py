import json
import sqlite3

import pytest

from brainkit import ids, store


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))


def test_home_uses_env(tmp_path):
    assert store.home() == tmp_path / "brain"


def test_init_creates_layout_and_is_idempotent(tmp_path):
    h = store.init()
    assert h == tmp_path / "brain"
    assert (h / "raw" / "brain.sqlite").exists()
    assert (h / "privacy.yaml").exists()
    assert json.loads((h / "dictionary.json").read_text()) == {"relations": {}, "aliases": {}}
    (h / "privacy.yaml").write_text("modes: {}\n")
    store.init()
    assert (h / "privacy.yaml").read_text() == "modes: {}\n"


def test_schema_tables():
    con = store.db()
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"sources", "items", "held", "categories", "rules", "personas"} <= names
    idx = {r[0] for r in con.execute("select name from sqlite_master where type='index'")}
    assert {"items_cat", "items_about", "items_status"} <= idx
    assert con.row_factory is sqlite3.Row


def test_json_roundtrip_atomic(tmp_path):
    p = tmp_path / "x" / "a.json"
    store.write_json(p, {"k": "é", "a": 1})
    assert store.read_json(p, None) == {"k": "é", "a": 1}
    assert "é" in p.read_text(encoding="utf-8")
    assert not list(p.parent.glob("*.tmp*"))
    assert store.read_json(tmp_path / "missing.json", {"d": 1}) == {"d": 1}


def test_jsonl_and_log():
    p = store.home() / "t.jsonl"
    assert store.read_jsonl(p) == []
    store.append_jsonl(p, {"a": 1})
    store.append_jsonl(p, {"a": 2})
    assert store.read_jsonl(p) == [{"a": 1}, {"a": 2}]
    store.log("hello", n=3)
    rec = store.read_jsonl(store.home() / "log.jsonl")[-1]
    assert rec["event"] == "hello" and rec["n"] == 3 and "ts" in rec


def test_paths(tmp_path):
    h = tmp_path / "brain"
    assert store.persona_dir("work") == h / "personas" / "work"
    assert store.questions_path() == h / "questions.json"
    assert store.ledger_path() == h / "ledger.json"
    assert store.corrections_path() == h / "corrections.jsonl"
    assert store.dictionary_path() == h / "dictionary.json"
    assert store.active_path() == h / "active"
    assert store.privacy_path() == h / "privacy.yaml"
    assert store.schema_path() == h / "schema.yaml"


def test_ids():
    assert ids.norm("  Hello   World!! ") == "hello world"
    assert ids.fact_id("Hello World.") == ids.fact_id("hello  world")
    assert ids.fact_id("a").startswith("f-") and len(ids.fact_id("a")) == 12
    assert ids.source_id("a").startswith("s-") and len(ids.source_id("a")) == 12
    assert ids.slug("Crème Brûlée & Co!") == "creme-brulee-co"
    assert ids.slug("me") == "me"
    assert len(ids.slug("x" * 100)) == 60
