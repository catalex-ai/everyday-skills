import pytest

from brainkit import policy, store


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))


def test_categories():
    policy.define_category("work", "Work life")
    policy.define_category("work", "Jobs")
    assert policy.categories() == {"work": "Jobs"}


def test_create_persona_writes_files():
    d = policy.create_persona("recruiter", "Hiring managers", "work history", "family")
    assert d == store.persona_dir("recruiter")
    text = (d / "contract.md").read_text()
    assert "Hiring managers" in text and "work history" in text and "family" in text
    for name in ("soul.md", "voice.md", "rules.md"):
        assert (d / name).read_text().strip()
    # existing files are not overwritten
    (d / "soul.md").write_text("custom")
    policy.create_persona("recruiter", "Hiring managers", "x", "y")
    assert (d / "soul.md").read_text() == "custom"
    p = policy.persona("recruiter")
    assert p["slug"] == "recruiter" and p["audience"] == "Hiring managers"
    assert [x["slug"] for x in policy.personas()] == ["recruiter"]
    assert policy.persona("ghost") is None


def test_rules_validation():
    policy.create_persona("a", "aud", "", "")
    policy.set_rule("a", "work", "allow")
    policy.set_rule("a", "family", "deny")
    policy.set_rule("a", "family", "allow")
    assert policy.rule("a", "work") == "allow"
    assert policy.rule("a", "missing") is None
    assert policy.rules("a") == {"work": "allow", "family": "allow"}
    with pytest.raises(ValueError):
        policy.set_rule("a", "work", "maybe")


def test_active():
    with pytest.raises(policy.NoActivePersona):
        policy.active()
    policy.create_persona("a", "aud", "", "")
    with pytest.raises(ValueError):
        policy.set_active("ghost")
    policy.set_active("a")
    assert policy.active() == "a"
    store.active_path().write_text("ghost\n")
    with pytest.raises(policy.NoActivePersona):
        policy.active()


def test_dictionary():
    assert policy.dictionary() == {"relations": {}, "aliases": {}}
    policy.define_relation("spouse_of", symmetric=True, single=True, words=["spouse", "wife"])
    policy.define_relation("works_at", inverse="employs", inverse_words=("employee", "staff"))
    policy.add_alias("Northwind", "Northwind Ltd")
    d = policy.dictionary()
    assert d["relations"]["spouse_of"] == {
        "inverse": None, "symmetric": True, "single": True,
        "words": ["spouse", "wife"], "inverse_words": []}
    assert d["relations"]["works_at"]["inverse"] == "employs"
    assert d["relations"]["works_at"]["inverse_words"] == ["employee", "staff"]
    assert d["aliases"] == {"Northwind": "Northwind Ltd"}
