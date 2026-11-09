import pytest

from brainkit import mcp_manage as M
from brainkit import policy, store
from tests.test_mcp_read import _tools

MANAGE_TOOLS = sorted([
    "init", "status", "add_source", "add_items", "define_category", "define_relation", "add_alias",
    "create_persona", "set_rule", "set_active", "set_privacy", "sync", "next_questions", "answer",
    "record_correction", "tidy", "audit", "gate_scan", "list_items"])


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))


def test_flow():
    assert "home" in M.init()
    M.define_category("contact", "Contact details")
    M.define_category("work", "Work life")
    M.create_persona("friends", "friends", "work", "contact")
    r = M.add_items([{"text": "Reach Asha at asha@northwind.example", "category": "contact"},
                     {"text": "Works at Northwind Ltd", "category": "work"}])
    assert len(r["ids"]) == 2 and "waiting" in r
    findings = M.gate_scan("mail asha@northwind.example")["findings"]
    assert findings[0]["type"] == "email" and set(findings[0]) == {"type", "start", "end"}
    items = M.list_items("contact")
    assert items["total"] == 1 and "asha@northwind" not in items["items"][0]["text"]
    M.set_active("friends")
    s = M.status()
    assert s["active"] == "friends" and s["stats"]["total"] == 2
    assert s["privacy"]["email"] == "hold" and "contact" in s["categories"]
    assert s["personas"][0]["slug"] == "friends"


def test_errors_are_dicts():
    M.init()
    assert "unknown category" in M.add_items([{"text": "x", "category": "nope"}])["error"]
    assert "error" in M.set_active("ghost")
    assert "error" in M.set_rule("p", "c", "maybe")
    assert "error" in M.set_privacy("email", "bogus")


def test_set_privacy_applies():
    M.init()
    M.define_category("contact", "c")
    M.add_items([{"text": "mail a@b.example", "category": "contact"}])
    r = M.set_privacy("email", "drop")
    assert r["ok"] and "items" in r["applied"]
    assert "a@b.example" not in M.list_items()["items"][0]["text"]


def test_wave2_tools():
    pytest.importorskip("brainkit.questions")
    M.init()
    assert isinstance(M.sync(), dict)
    assert isinstance(M.next_questions(2), list)


def test_stdio_smoke(tmp_path):
    assert _tools("brainkit.mcp_manage", tmp_path) == MANAGE_TOOLS
