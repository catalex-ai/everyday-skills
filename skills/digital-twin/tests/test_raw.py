import pytest

from brainkit import gate, policy, raw, store


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))
    policy.define_category("work", "Work life")
    policy.define_category("contact", "Contact details")


def sqlite_bytes():
    return (store.home() / "raw" / "brain.sqlite").read_bytes()


def test_add_items_and_read_back():
    ids_ = raw.add_items([
        {"text": "Asha works at Northwind Ltd.", "category": "work",
         "edge": {"s": "me", "rel": "works_at", "o": "Northwind Ltd"}},
        {"text": "Led Project Atlas", "category": "work", "about": "Ravi"},
    ])
    assert len(ids_) == 2
    rows = raw.items()
    assert len(rows) == 2
    r = raw.get(ids_[0])
    assert r["edge"] == {"s": "me", "rel": "works_at", "o": "Northwind Ltd"}
    assert r["about"] == "me" and r["conf"] == "medium" and r["by"] == "doc" and r["status"] == "active"
    other = raw.get(ids_[1])
    assert other["edge"] is None and other["about"] == "Ravi"
    assert raw.get("f-nope") is None


def test_email_is_tokenised_in_file_bytes():
    [iid] = raw.add_items([{"text": "Reach Asha at asha@northwind.example", "category": "contact"}])
    row = raw.get(iid)
    assert "asha@northwind.example" not in row["text"] and "⟦email:" in row["text"]
    data = sqlite_bytes()
    # value lives only in the held table: exactly one place, and never in items/sources text
    assert raw.held_map()[row["text"].split()[-1]] == "asha@northwind.example"
    con = store.db()
    assert con.execute("select count(*) from items where text like '%asha@%'").fetchone()[0] == 0
    assert data.count(b"asha@northwind.example") >= 1  # in held


def test_drop_value_nowhere_in_file():
    raw.add_items([{"text": "password: hunter2zz", "category": "contact"}])
    raw.add_source("my password: hunter2zz", "chat")
    assert b"hunter2zz" not in sqlite_bytes()


def test_edge_object_redacted():
    [iid] = raw.add_items([{"text": "Asha email", "category": "contact",
                            "edge": {"s": "me", "rel": "email", "o": "asha@northwind.example"}}])
    assert "@" not in raw.get(iid)["edge"]["o"]


def test_by_you_not_overwritten_by_doc():
    [a] = raw.add_items([{"text": "Likes tea", "category": "work", "by": "you", "conf": "high"}])
    [b] = raw.add_items([{"text": "Likes tea", "category": "work", "by": "doc", "conf": "low"}])
    assert a == b
    r = raw.get(a)
    assert r["by"] == "you" and r["conf"] == "high"
    # you may overwrite doc
    [c] = raw.add_items([{"text": "Likes coffee", "category": "work", "by": "doc"}])
    raw.add_items([{"text": "Likes coffee", "category": "work", "by": "you"}])
    assert raw.get(c)["by"] == "you"


def test_unknown_category_raises():
    with pytest.raises(ValueError, match="unknown category: nope; known:"):
        raw.add_items([{"text": "x", "category": "nope"}])
    assert raw.items() == []


def test_status_and_filters_and_stats():
    [a, b] = raw.add_items([{"text": "one", "category": "work"}, {"text": "two", "category": "contact"}])
    raw.set_status(b, "archived")
    assert [r["id"] for r in raw.items()] == [a]
    assert [r["id"] for r in raw.items(status="archived")] == [b]
    assert raw.items(categories=["contact"]) == []
    assert [r["id"] for r in raw.items(status="archived", categories=["contact"])] == [b]
    s = raw.stats()
    assert s["by_status"] == {"active": 1, "archived": 1}
    assert s["by_category"] == {"work": 1, "contact": 1}


def test_add_source_redacts_and_upserts():
    s1 = raw.add_source("Call +91 98765 43210 about Project Atlas", "chat")
    s2 = raw.add_source("Call +91 98765 43210 about Project Atlas", "chat")
    assert s1 == s2 and s1.startswith("s-")
    con = store.db()
    assert con.execute("select count(*) from sources").fetchone()[0] == 1
    assert "98765" not in con.execute("select text from sources").fetchone()[0]
    assert "+91 98765 43210" in raw.held_map().values()


def test_apply_privacy_after_allow_to_hold():
    gate.set_mode("phone", "allow")
    raw.add_source("Call +91 98765 43210", "chat")
    [iid] = raw.add_items([{"text": "Phone is +91 98765 43210", "category": "contact"}])
    assert "98765" in raw.get(iid)["text"]
    gate.set_mode("phone", "hold")
    res = raw.apply_privacy()
    assert res == {"sources": 1, "items": 1}
    assert "98765" not in raw.get(iid)["text"] and "⟦phone:" in raw.get(iid)["text"]
    assert "+91 98765 43210" in raw.held_map().values()
    assert raw.apply_privacy() == {"sources": 0, "items": 0}
