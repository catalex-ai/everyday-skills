import pytest

from brainkit import corrections, policy, questions, raw, store


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))
    store.init()
    policy.define_category("work", "Work life")
    policy.create_persona("pro", "colleagues", "work", "none")


def test_voice_appends_line():
    r = corrections.record("too formal", "keep it casual", "voice", persona="pro")
    assert r["target"] == "voice"
    text = (store.persona_dir("pro") / "voice.md").read_text()
    assert text.rstrip().endswith("- When: too formal → Instead: keep it casual")
    assert store.read_jsonl(store.corrections_path())[0]["target"] == "voice"


def test_payload_line_and_persona_required():
    corrections.record("a", "b", "rules", persona="pro", payload={"line": "- Never discuss pay"})
    assert (store.persona_dir("pro") / "rules.md").read_text().rstrip().endswith("- Never discuss pay")
    with pytest.raises(ValueError):
        corrections.record("a", "b", "soul")


def test_item_supersedes_old():
    [old] = raw.add_items([{"text": "Asha works at Northwind", "category": "work"}])
    corrections.record("wrong", "Asha works at Northwind Ltd", "item", payload={"id": old})
    assert raw.get(old)["status"] == "superseded"
    new = [i for i in raw.items() if i["by"] == "you"]
    assert len(new) == 1 and new[0]["text"] == "Asha works at Northwind Ltd" and new[0]["category"] == "work"


def test_category_sets_rule():
    raw.add_items([{"text": "A fact", "category": "work"}])
    r = corrections.record("", "", "category", payload={"persona": "pro", "category": "work", "decision": "allow"})
    assert policy.rule("pro", "work") == "allow" and "allow" in r["applied"]
    assert len(store.read_jsonl(store.persona_dir("pro") / "facts.jsonl")) == 1


def test_schema_merge():
    corrections.record("", "", "schema", payload={"yaml": "extra: {a: 1}"})
    import yaml
    y = yaml.safe_load(store.schema_path().read_text())
    assert y["extra"] == {"a": 1} and "facets" in y
