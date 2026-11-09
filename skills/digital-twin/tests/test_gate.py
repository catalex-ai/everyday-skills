import pytest

from brainkit import gate


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))


def types(text):
    return [f["type"] for f in gate.scan(text)]


POSITIVES = [
    ("Write to asha@northwind.example today", "email"),
    ("reach me at asha at gmail dot com please", "email"),
    ("call +91 98765 43210 now", "phone"),
    ("call 98-765-43210 now", "phone"),
    ("call (415) 555-0134 now", "phone"),
    ("call +44 20 7946 0958 now", "phone"),
    ("Office is 12 Baker Street", "address"),
    ("Northwind Ltd, Pune 411001", "address"),
    ("password: hunter2", "password"),
    ("my pin is 4821", "password"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "bank_account"),
    ("account number 123456789012", "bank_account"),
    ("IFSC: ABCD0123456", "bank_account"),
    ("card 4111 1111 1111 1111", "card"),
    ("PAN ABCDE1234F", "gov_id"),
    ("Aadhaar 1234 5678 9012", "gov_id"),
    ("SSN 123-45-6789", "gov_id"),
    ("passport A1234567", "gov_id"),
]


@pytest.mark.parametrize("text,kind", POSITIVES)
def test_positive(text, kind):
    assert kind in types(text), gate.scan(text)


@pytest.mark.parametrize("text", [
    "In 2004 I led a team of 12",
    "won 14 awards",
    "Q3 revenue grew 40%",
    "1,200 people",
    "from 1992 to 2001",
    "a 4111 word essay",
])
def test_negative(text):
    assert gate.scan(text) == []


def test_luhn_invalid_card_is_not_a_card():
    assert "card" not in types("card 4111 1111 1111 1112")


def test_finding_has_no_value():
    text = "mail asha@northwind.example or password: hunter2"
    found = gate.scan(text)
    assert len(found) == 2
    for f in found:
        assert set(f) == {"type", "start", "end"}
        assert "asha@northwind.example" not in str(f) and "hunter2" not in str(f)
    assert found == sorted(found, key=lambda f: f["start"])


def test_card_not_also_reported_as_aadhaar():
    assert types("4111 1111 1111 1111") == ["card"]


def test_redact_hold_makes_token_and_held_row():
    out, held = gate.redact("mail asha@northwind.example now", src="s-1")
    assert "asha@northwind.example" not in out
    assert gate.TOKEN_RE.search(out)
    assert len(held) == 1
    row = held[0]
    assert row["type"] == "email" and row["value"] == "asha@northwind.example"
    assert row["src"] == "s-1" and row["token"] in out
    assert row["token"].startswith("⟦email:") and len(row["token"]) == len("⟦email:xxxxxx⟧")


def test_redact_drop_has_no_value_anywhere():
    out, held = gate.redact("password: hunter2")
    assert out == "password: ⟦password⟧"
    assert held == []


def test_redact_allow_unchanged():
    gate.set_mode("email", "allow")
    text = "mail asha@northwind.example"
    assert gate.redact(text) == (text, [])


def test_redact_idempotent():
    once, held = gate.redact("asha@northwind.example, password: hunter2, +91 98765 43210")
    twice, held2 = gate.redact(once)
    assert twice == once and held2 == []


def test_strip_tokens():
    out, _ = gate.redact("Call +91 98765 43210 , thanks. Pass password: hunter2")
    assert gate.strip_tokens(out) == "Call, thanks. Pass password:"


def test_unhold_swaps_value_back_after_allow():
    text = "mail asha@northwind.example, password: hunter2"
    out, held = gate.redact(text)
    hm = {h["token"]: h["value"] for h in held}
    # still hold: token stripped
    assert "asha" not in gate.unhold(out, hm)
    gate.set_mode("email", "allow")
    back = gate.unhold(out, hm)
    assert "asha@northwind.example" in back
    assert "⟦" not in back  # drop token stripped too


def test_unhold_explicit_modes():
    out, held = gate.redact("mail asha@northwind.example")
    hm = {h["token"]: h["value"] for h in held}
    assert gate.unhold(out, hm, {"email": "allow"}) == "mail asha@northwind.example"
    assert gate.unhold(out, hm, {"email": "hold"}) == "mail"


def test_set_mode_persists_and_validates():
    assert gate.settings()["phone"] == "hold"
    gate.set_mode("phone", "allow")
    assert gate.settings()["phone"] == "allow"
    assert gate.settings()["email"] == "hold"  # others untouched
    with pytest.raises(ValueError):
        gate.set_mode("nope", "allow")
    with pytest.raises(ValueError):
        gate.set_mode("phone", "maybe")


def test_defaults():
    s = gate.settings()
    for t in ("email", "phone", "address"):
        assert s[t] == "hold"
    for t in ("password", "bank_account", "card", "gov_id"):
        assert s[t] == "drop"
