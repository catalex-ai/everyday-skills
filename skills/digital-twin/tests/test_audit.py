import pytest

from brainkit import audit_html, build, policy, questions, raw, store


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))
    store.init()
    policy.define_category("work", "Work life")
    policy.create_persona("pro", "colleagues", "work", "none")
    policy.set_active("pro")


def test_clean_brain_passes():
    raw.add_items([{"text": "Reach Asha at asha@northwind.example", "category": "work"}])
    questions.sync()
    r = audit_html.run()
    assert r["pii_findings"] == []
    page = open(r["path"], encoding="utf-8").read()
    assert "asha@northwind" not in page and "PII check passed" in page
    assert "http://" not in page and "https://" not in page
    assert "active" in page and "prefers-color-scheme" in page


def test_planted_phone_is_found_without_value():
    raw.add_items([{"text": "A work fact", "category": "work"}])
    policy.set_rule("pro", "work", "allow")
    questions.sync()
    page = store.persona_dir("pro") / "pages" / "me.md"
    page.write_text(page.read_text() + "\nCall (415) 555-0134 today\n")
    r = audit_html.run()
    hits = [f for f in r["pii_findings"] if f["type"] == "phone"]
    assert hits and hits[0]["file"].endswith("pages/me.md") and hits[0]["line"] > 1
    html_ = open(r["path"], encoding="utf-8").read()
    assert "555-0134" not in html_ and "PII check:" in html_


def test_allowed_types_are_not_findings():
    from brainkit import gate
    gate.set_mode("phone", "allow")
    p = store.persona_dir("pro") / "x.md"
    p.write_text("Call (415) 555-0134")
    assert audit_html.run()["pii_findings"] == []
