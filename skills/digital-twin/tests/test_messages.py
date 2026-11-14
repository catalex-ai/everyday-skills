from brainkit import messages

WA = """WhatsApp chat export: me with Dev.

[03/10/2026, 22:41] Dev: oi founder. alive?
[03/10/2026, 22:58] Asha: barely lol
[03/10/2026, 22:58] Asha: ok so we're launching a thing on the 20th
it's an email template
[03/10/2026, 23:01] Dev: hahaha what's the thing
[03/10/2026, 23:04] Asha: the new billing thing
[03/10/2026, 23:05] Dev: <Media omitted>
"""

DASH = "12/01/26, 9:15 pm - Mum: did you eat?\n12/01/26, 9:20 pm - Sam: Yes, pasta. x\n"

QA = """My own words, verbatim. Source: qa.

Asked: Why did you start?
Me: Honestly, I was annoyed.

Asked: And now?
Me: Still annoyed. Less alone."""


def test_whatsapp_bursts_and_pairs():
    p = messages.pairs(WA, "Asha")
    assert [x["text"] for x in p] == ["barely lol\nok so we're launching a thing on the 20th\nit's an email template",
                                      "the new billing thing"]
    assert p[0]["they"] == "oi founder. alive?" and p[0]["they_who"] == "Dev"
    assert p[1]["they"] == "hahaha what's the thing"


def test_dashed_export_and_first_name_match():
    p = messages.pairs(DASH, "Sam Reid")
    assert p == [{"text": "Yes, pasta. x", "they": "did you eat?", "they_who": "Mum"}]


def test_interview_notes():
    p = messages.pairs(QA, "")
    assert [x["text"] for x in p] == ["Honestly, I was annoyed.", "Still annoyed. Less alone."]
    assert p[1]["they"] == "And now?" and p[1]["they_who"] == "interviewer"
    assert messages.context("journalist", "interviewer", "And now?") == "journalist says: And now?"
    assert messages.context("close friend", "Dev", "alive?") == "close friend (Dev) says: alive?"


THREAD = """[22/07/2026, 22:40] Rohan: bro do you even have friends anymore
[22/07/2026, 22:41] Asha: i have you. that's the list
[22/07/2026, 22:42] Rohan: no but seriously. are you ok?
[22/07/2026, 22:43] Asha: honestly, tired. the launch slipped again
[23/07/2026, 08:00] Rohan: gn was yesterday, gm now
[23/07/2026, 08:01] Asha: gm
"""


def test_thread_keeps_earlier_turns_same_day():
    p = messages.pairs(THREAD, "Asha")
    assert "earlier" not in p[0]
    assert p[1]["they"] == "no but seriously. are you ok?"
    assert p[1]["earlier"] == ["Rohan: bro do you even have friends anymore", "me: i have you. that's the list"]
    assert "earlier" not in p[2]  # a new day starts a new thread
    ctx = messages.context("close friend", "Rohan", p[1]["they"], p[1]["earlier"])
    assert ctx.startswith("close friend (Rohan) says: (just before: Rohan: bro")
    assert ctx.endswith("are you ok?")
