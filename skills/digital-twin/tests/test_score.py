import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))
import score  # noqa: E402


def item(qa_id, persona, reply, tool_text="", kind="lookup", must=("Asha Rao",),
         should=("personal",), mustnot=("professional",)):
    return {"qa_id": qa_id, "persona": persona, "q": "who is my spouse?", "kind": kind, "cls": "personal",
            "must": list(must), "should_know": list(should), "must_not_know": list(mustnot),
            "reply": reply, "tool_text": tool_text}


def test_correct_and_stages():
    res = [
        item("a", "personal", "Your spouse is Asha Rao.", "spouse: Asha Rao"),
        item("b", "personal", "I don't know.", "spouse: Asha Rao"),      # answered_wrong
        item("c", "personal", "I don't know.", "nothing"),                # not_retrieved
        item("d", "personal", "Ásha  RAO!", "x"),                          # accent and case folded
    ]
    s = score.score_answers(res)
    cell = s["by_persona_kind"]["personal"]["lookup"]
    assert cell == {"n": 4, "correct": 2, "evidence": 2}
    stages = {m["qa_id"]: m["stage"] for m in s["misses"]}
    assert stages == {"b": "answered_wrong", "c": "not_retrieved"}


def test_leak_and_aggregate_word_boundary():
    res = [
        item("a", "professional", "My spouse is Asha Rao."),
        item("b", "professional", "I keep that private."),
        item("c", "personal", "I have 13 awards", kind="aggregate", must=("3", "three"), should=("personal",)),
    ]
    s = score.score_answers(res)
    assert s["leak"]["professional"] == {"n": 2, "leaked": 1}
    assert [m["stage"] for m in s["misses"] if m["qa_id"] == "a"] == ["leaked"]
    assert s["by_persona_kind"]["personal"]["aggregate"]["correct"] == 0   # "13" is not "3"


def make_brain(tmp_path, extra_file=None):
    brain = tmp_path / "brain"
    (brain / "raw").mkdir(parents=True)
    (brain / "personas" / "p").mkdir(parents=True)
    (brain / "privacy.yaml").write_text(
        "email: hold\nphone: hold\naddress: hold\npassword: drop\nbank_account: drop\ncard: drop\ngov_id: allow\n")
    con = sqlite3.connect(brain / "raw" / "brain.sqlite")
    con.executescript("""CREATE TABLE sources(id, origin, added, text);
        CREATE TABLE items(id, text);
        CREATE TABLE held(token, type, value, src);""")
    con.execute("INSERT INTO sources VALUES('s','o','t','mail me at ⟦email:abc123⟧')")
    con.execute("INSERT INTO items VALUES('i','leaky pass hunter22xyz here')")   # a drop value on disk
    con.execute("INSERT INTO held VALUES('⟦email:abc123⟧','email','asha@example.org','s')")  # allowed
    con.commit()
    con.close()
    if extra_file:
        (brain / "personas" / "p" / "facts.jsonl").write_text(extra_file)
    return brain


def write_pii(tmp_path):
    p = tmp_path / "pii.jsonl"
    rows = [
        {"text": "t", "spans": [{"value": "asha@example.org", "type": "email"}]},        # held only
        {"text": "t", "spans": [{"value": "hunter22xyz", "type": "password"}]},          # in items
        {"text": "t", "spans": [{"value": "123-45-6789", "type": "gov_id"}]},            # mode allow: ignored
        {"text": "t", "spans": [{"value": "+1 555 0100 777", "type": "phone"}]},         # in a persona file
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows))
    return p


def test_pii_counting(tmp_path):
    brain = make_brain(tmp_path, extra_file="call +1 555 0100 777\n")
    r = score.pii_on_disk(brain, write_pii(tmp_path))
    assert r["checked"] == 3
    assert r["on_disk"] == 2
    assert sorted(f["type"] for f in r["found"]) == ["password", "phone"]


def test_pii_clean(tmp_path):
    brain = make_brain(tmp_path)
    (brain / "raw" / "brain.sqlite").unlink()
    con = sqlite3.connect(brain / "raw" / "brain.sqlite")
    con.executescript("CREATE TABLE sources(id,origin,added,text); CREATE TABLE items(id,text);"
                      "CREATE TABLE held(token,type,value,src);")
    con.execute("INSERT INTO held VALUES('t','email','asha@example.org','s')")
    con.commit()
    con.close()
    assert score.pii_on_disk(brain, write_pii(tmp_path))["on_disk"] == 0


def test_approvals_violation(tmp_path):
    qs = tmp_path / "questions.json"
    qs.write_text(json.dumps([
        {"kind": "approval", "persona": "professional", "category": "family"},
        {"kind": "approval", "persona": "professional", "category": "family"},
        {"kind": "approval", "persona": "personal", "category": "family"},
        {"kind": "info", "persona": "personal", "category": "family"},
    ]))
    r = score.approvals(qs)
    assert r["violations"] == {"professional/family": 2}
    assert r["counts"]["personal/family"] == 1


def test_cli_writes_score_json(tmp_path, capsys):
    res = tmp_path / "results.json"
    res.write_text(json.dumps([item("a", "personal", "Asha Rao")]))
    sys.argv = ["score.py", str(res)]
    assert score.main() == 0
    assert "Eval round" in capsys.readouterr().out
    assert (tmp_path / "results.score.json").exists()
