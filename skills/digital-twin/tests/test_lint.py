from brainkit import store, raw, policy, lint, mcp_manage


def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path))
    store.init()
    for c in ("work", "family"):
        policy.define_category(c, c)
    policy.create_persona("pro", "colleagues", "work", "family")
    policy.set_rule("pro", "work", "allow")
    policy.set_rule("pro", "family", "deny")
    policy.define_relation("spouse_of", symmetric=True, single=True, words=["wife", "husband", "spouse"])
    raw.add_items([{"text": "Asha is my wife.", "category": "family",
                    "edge": {"s": "me", "rel": "spouse_of", "o": "Asha"}}])


def test_mixed_fact_is_flagged(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    out = mcp_manage.add_items([{"text": "I co-founded Northwind Ltd with my wife Asha.", "category": "work"}])
    assert out["mixed"][0]["word"] == "wife"
    assert out["mixed"][0]["belongs_to"] == ["family"]


def test_clean_fact_not_flagged_and_replace_fixes(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    ok = mcp_manage.add_items([{"text": "Asha co-founded Northwind Ltd with me.", "category": "work"}])
    assert "mixed" not in ok
    bad = mcp_manage.add_items([{"text": "My wife Asha leads design at Northwind Ltd.", "category": "work"}])
    old = bad["mixed"][0]["id"]
    out = mcp_manage.replace_item(old, [{"text": "Asha leads design at Northwind Ltd.", "category": "work"}])
    assert "mixed" not in out
    assert raw.get(old)["status"] == "superseded"
    assert lint.mixed() == []


def test_not_flagged_when_no_persona_splits_them(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    policy.set_rule("pro", "family", "allow")
    out = mcp_manage.add_items([{"text": "I co-founded Northwind Ltd with my wife Asha.", "category": "work"}])
    assert "mixed" not in out
