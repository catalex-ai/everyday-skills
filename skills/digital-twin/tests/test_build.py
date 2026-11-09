import json

import pytest

from brainkit import build, policy, questions, raw, store


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))
    store.init()
    policy.define_category("work", "Work life")
    policy.define_category("family", "Family and relatives")
    policy.define_category("health", "Health")
    policy.create_persona("pro", "colleagues", "work", "family")
    policy.create_persona("home", "friends", "family", "work")


def files(persona):
    d = store.persona_dir(persona)
    return {p: p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def test_rebuild_writes_only_allowed():
    raw.add_items([
        {"text": "Asha works at Northwind Ltd", "category": "work",
         "edge": {"s": "me", "rel": "works_at", "o": "Northwind Ltd"}},
        {"text": "Asha has a sister called Meera", "category": "family"},
    ])
    policy.set_rule("pro", "work", "allow")
    r = build.rebuild("pro")
    assert r["facts"] == 1
    d = store.persona_dir("pro")
    facts = store.read_jsonl(d / "facts.jsonl")
    assert [f["category"] for f in facts] == ["work"]
    assert set(facts[0]) == {"id", "about", "category", "text", "since", "by"}
    page = (d / "pages" / "northwind-ltd.md").read_text()
    assert page.startswith("# Northwind Ltd") and "Now: Asha works at Northwind Ltd" in page
    assert f"^{facts[0]['id']}" in page
    assert "Links:" in (d / "pages" / "me.md").read_text()
    assert "Work life" in (d / "profile.md").read_text()
    assert "northwind-ltd.md" in (d / "index.md").read_text()
    assert (d / "index.sqlite").exists()


def test_dictionary_only_used_relations_and_node_aliases():
    policy.define_relation("works_at", inverse="employs", words=["employer"])
    policy.define_relation("spouse_of", symmetric=True, single=True)
    policy.add_alias("NW", "Northwind Ltd")
    policy.add_alias("Mx", "Someone Else")
    raw.add_items([{"text": "Works at NW", "category": "work",
                    "edge": {"s": "me", "rel": "works_at", "o": "NW"}}])
    policy.set_rule("pro", "work", "allow")
    build.rebuild("pro")
    dic = json.loads((store.persona_dir("pro") / "dictionary.json").read_text())
    assert "spouse_of" not in dic["relations"] and "works_at" in dic["relations"]
    assert dic["aliases"] == {"NW": "Northwind Ltd"}


def test_stale_pages_removed_and_managed_files_kept():
    [a] = raw.add_items([{"text": "Led Project Atlas", "category": "work", "about": "Project Atlas"}])
    policy.set_rule("pro", "work", "allow")
    build.rebuild("pro")
    d = store.persona_dir("pro")
    assert (d / "pages" / "project-atlas.md").exists()
    (d / "voice.md").write_text("mine")
    raw.set_status(a, "superseded")
    build.rebuild("pro")
    assert not (d / "pages" / "project-atlas.md").exists()
    assert (d / "voice.md").read_text() == "mine"
    assert (d / "contract.md").exists() and (d / "soul.md").exists() and (d / "rules.md").exists()


def test_rebuild_is_byte_identical():
    raw.add_items([
        {"text": "Asha leads Project Atlas", "category": "work",
         "edge": {"s": "me", "rel": "leads", "o": "Project Atlas"}},
        {"text": "Ravi mentors Asha", "category": "work", "about": "Ravi"},
    ])
    policy.set_rule("pro", "work", "allow")
    build.rebuild("pro")
    a = {p: b for p, b in files("pro").items() if p.suffix in (".md", ".json", ".jsonl")}
    build.rebuild("pro")
    b = {p: b for p, b in files("pro").items() if p.suffix in (".md", ".json", ".jsonl")}
    assert a == b and a


def test_denied_text_in_no_file():
    raw.add_items([{"text": "Zebra-secret family detail", "category": "family"},
                   {"text": "Plain work fact", "category": "work"}])
    policy.set_rule("pro", "work", "allow")
    policy.set_rule("pro", "family", "deny")
    build.rebuild("pro")
    for p, data in files("pro").items():
        assert b"Zebra-secret" not in data, p


def test_rebuild_all():
    raw.add_items([{"text": "Fact one", "category": "work"}])
    policy.set_rule("pro", "work", "allow")
    out = build.rebuild_all()
    assert set(out) == {"pro", "home"} and out["pro"]["facts"] == 1 and out["home"]["facts"] == 0
    assert questions  # module import sanity


def test_facts_about_hidden_relatives_stay_out():
    raw.add_items([
        {"text": "My son is Ravi", "category": "family",
         "edge": {"s": "me", "rel": "child", "o": "Ravi"}},
        {"text": "Ravi works at Northwind Ltd", "category": "work", "about": "Ravi"},
        {"text": "Asha leads my team", "category": "work", "about": "Asha",
         "edge": {"s": "Asha", "rel": "manager_of", "o": "me"}},
        {"text": "Asha works at Northwind Ltd", "category": "work", "about": "Asha"},
        {"text": "I work at Northwind Ltd", "category": "work"},
    ])
    policy.set_rule("pro", "work", "allow")
    policy.set_rule("home", "work", "allow")
    policy.set_rule("home", "family", "allow")
    build.rebuild("pro")
    build.rebuild("home")
    pro = [f["text"] for f in store.read_jsonl(store.persona_dir("pro") / "facts.jsonl")]
    home = [f["text"] for f in store.read_jsonl(store.persona_dir("home") / "facts.jsonl")]
    assert "Ravi works at Northwind Ltd" not in pro
    assert "Asha works at Northwind Ltd" in pro and "I work at Northwind Ltd" in pro
    assert "Ravi works at Northwind Ltd" in home


def test_relative_who_is_also_a_coworker_stays_hidden():
    raw.add_items([
        {"text": "My daughter is Mira", "category": "family",
         "edge": {"s": "Mira", "rel": "child_of", "o": "me"}},
        {"text": "I worked with Mira on a project", "category": "work",
         "edge": {"s": "me", "rel": "worked_with", "o": "Mira"}},
        {"text": "Mira studied design", "category": "work", "about": "Mira"},
    ])
    policy.set_rule("pro", "work", "allow")
    build.rebuild("pro")
    pro = [f["text"] for f in store.read_jsonl(store.persona_dir("pro") / "facts.jsonl")]
    assert "Mira studied design" not in pro
    assert "I worked with Mira on a project" in pro
