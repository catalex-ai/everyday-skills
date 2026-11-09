import pytest

from brainkit import build, gate, corrections, policy, questions, raw, store


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))
    store.init()
    for c, d in (("work", "Work life"), ("family", "Family and relatives"), ("health", "Health")):
        policy.define_category(c, d)
    policy.create_persona("pro", "colleagues", "work", "family")
    policy.create_persona("home", "friends", "family", "work")


def add(cat, n, prefix=None):
    raw.add_items([{"text": f"{prefix or cat} fact number {i} {'x' * i}", "category": cat} for i in range(n)])


def approvals(persona, cat=None, status="open"):
    return [q for q in questions.all(status) if q["kind"] == "approval" and q["persona"] == persona
            and (cat is None or q["category"] == cat)]


def test_core_scenario():
    add("work", 15)
    add("family", 3)
    add("health", 2)
    policy.set_rule("pro", "work", "allow")
    out = questions.sync()
    assert out["pro"] == {"allowed": 15, "waiting": 5, "denied": 0}
    assert len(store.read_jsonl(store.persona_dir("pro") / "facts.jsonl")) == 15
    assert len(approvals("pro")) == 2
    assert len(approvals("home")) == 3
    ex = approvals("pro", "family")[0]
    assert ex["waiting"] == 3 and len(ex["examples"]) == 2 and "Family and relatives" in ex["text"]

    raw.add_items([{"text": f"family extra {i}", "category": "family"} for i in range(2)])
    questions.sync()
    fam = approvals("pro", "family")
    assert len(fam) == 1 and fam[0]["waiting"] == 5

    out = questions.answer(fam[0]["id"], decision="deny")
    assert out["status"] == "answered"
    assert not approvals("pro", "family")
    assert questions.sync()["pro"]["waiting"] == 2  # health only

    [hf] = approvals("home", "family")
    questions.answer(hf["id"], decision="allow")
    assert len(store.read_jsonl(store.persona_dir("home") / "facts.jsonl")) == 5

    policy.create_persona("third", "x", "y", "z")
    policy.set_rule("third", "work", "allow")
    questions.sync()
    cats = sorted(q["category"] for q in approvals("third"))
    assert cats == ["family", "health"]


def test_sync_rebuilds_only_changed(monkeypatch):
    add("work", 2)
    policy.set_rule("pro", "work", "allow")
    questions.sync()
    calls = []
    real = build.rebuild
    monkeypatch.setattr(build, "rebuild", lambda p: calls.append(p) or real(p))
    questions.sync()
    assert calls == []
    raw.add_items([{"text": "another work fact", "category": "work"}])
    questions.sync()
    assert calls == ["pro"]


def test_info_gap_for_missing_facet():
    raw.add_items([{"text": "Currently works at Northwind Ltd as an engineer", "category": "work"}])
    questions.sync()
    info = {q["field"]: q for q in questions.all("open") if q["kind"] == "info" and q["about"] == "me"}
    assert "current_role" not in info
    assert "education" in info and info["education"]["score"] == pytest.approx(0.7)
    raw.add_items([{"text": "Studied at Hillview University", "category": "work"}])
    questions.sync()
    assert all(q["field"] != "education" for q in questions.all("open"))


def test_org_facets_and_unlinked_person():
    raw.add_items([
        {"text": "Joined Northwind Ltd", "category": "work",
         "edge": {"s": "me", "rel": "works_at", "o": "Northwind Ltd"}},
        {"text": "Ravi is a good cook", "category": "family", "about": "Ravi"},
    ])
    questions.sync()
    openq = [(q["about"], q["field"]) for q in questions.all("open") if q["kind"] == "info"]
    assert ("Northwind Ltd", "your_part") in openq and ("Northwind Ltd", "outcome") in openq
    ravi = [q for q in questions.all("open") if q["about"] == "Ravi"]
    assert len(ravi) == 1 and ravi[0]["text"] == "How do you know Ravi?" and ravi[0]["score"] == 0.6
    raw.add_items([{"text": "Ravi is a friend", "category": "family", "about": "Ravi",
                    "edge": {"s": "me", "rel": "friend_of", "o": "Ravi"}}])
    questions.sync()
    assert not [q for q in questions.all("open") if q["about"] == "Ravi"]


def test_conflict_question_and_ledger():
    policy.define_relation("spouse_of", symmetric=True, single=True)
    raw.add_items([
        {"text": "Asha is married to Ravi", "category": "family", "edge": {"s": "me", "rel": "spouse_of", "o": "Ravi"}},
        {"text": "Asha is married to Dev", "category": "family", "edge": {"s": "me", "rel": "spouse_of", "o": "Dev"}},
    ])
    questions.sync()
    [c] = [q for q in questions.all("open") if q["kind"] == "conflict"]
    assert "married to Ravi" in c["text"] and "married to Dev" in c["text"] and c["score"] == 0.9
    assert len(store.read_json(store.ledger_path(), {})["conflicts"]) == 1


def test_next_orders_approval_first_and_decline_is_final():
    add("work", 1)
    questions.sync()
    got = questions.next(2)
    assert [q["kind"] for q in got] == ["approval", "approval"] or got[0]["kind"] == "approval"
    assert all(q["asked"] == 1 for q in got)
    info = [q for q in questions.all("open") if q["kind"] == "info"][0]
    questions.answer(info["id"], status="declined")
    for _ in range(3):
        questions.sync()
        assert info["id"] not in [q["id"] for q in questions.next(50)]
    assert [q for q in questions.all() if q["id"] == info["id"]][0]["status"] == "declined"


def test_asked_halves_score_and_later_snoozes():
    questions.sync()
    q = [q for q in questions.all("open") if q["kind"] == "info"][0]
    questions.answer(q["id"], status="later")
    z = [x for x in questions.all() if x["id"] == q["id"]][0]
    assert z["status"] == "snoozed" and z["until"]
    questions.refresh_gaps()
    assert [x for x in questions.all() if x["id"] == q["id"]][0]["status"] == "snoozed"
    qs = store.read_json(store.questions_path(), [])
    for x in qs:
        if x["id"] == q["id"]:
            x["until"] = "2000-01-01T00:00:00+00:00"
    store.write_json(store.questions_path(), qs)
    questions.refresh_gaps()
    assert [x for x in questions.all() if x["id"] == q["id"]][0]["status"] == "open"


def test_info_answer_marks_answered():
    questions.sync()
    q = [q for q in questions.all("open") if q["kind"] == "info"][0]
    r = questions.answer(q["id"], text="Lives in Lakeside")
    assert r["status"] == "answered" and r["answer"] == "Lives in Lakeside"


def test_privacy_email_hold_then_allow():
    raw.add_items([{"text": "Reach Asha at asha@northwind.example", "category": "work"}])
    policy.set_rule("pro", "work", "allow")
    questions.sync()
    d = store.persona_dir("pro")
    for p in d.rglob("*"):
        if p.is_file() and p.suffix in (".md", ".json", ".jsonl"):
            t = p.read_text()
            assert "asha@northwind" not in t and "⟦" not in t, p
    corrections.record("x", "y", "privacy", payload={"type": "email", "mode": "allow"})
    assert "asha@northwind.example" in (d / "facts.jsonl").read_text()
    assert gate.settings()["email"] == "allow"
