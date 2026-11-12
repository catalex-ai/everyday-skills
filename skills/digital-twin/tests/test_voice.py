"""Kinds of memory, the owner's real messages, the style fingerprint, the reply
check, stale facts and the twin's question inbox."""
import json
import sqlite3

import pytest

from brainkit import build, mcp_read, policy, raw, store, style


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))
    store.init()
    policy.define_category("work", "Work life")
    policy.define_category("small-talk", "How I chat")
    policy.define_category("family", "Family")
    policy.define_relation("lives_in", single=True, words=["live", "home"])
    policy.create_persona("pro", "colleagues", "work, how I chat", "family")
    for c in ("work", "small-talk"):
        policy.set_rule("pro", c, "allow")
    policy.set_rule("pro", "family", "deny")
    policy.set_active("pro")
    mcp_read._cache.clear()


EXAMPLES = [
    ("friend asks how things are", "haha all good yaar, just buried in work this week"),
    ("colleague asks about the launch", "launch went fine!! still fixing a few things tbh"),
    ("friend asks about weekend plans", "haha nothing much, sleeping mostly"),
    ("someone asks about hiring", "hiring slowly tbh, rather wait for the right person"),
    ("friend says congrats", "thank you yaar!! means a lot"),
]


def add_examples(category="small-talk"):
    raw.add_items([{"text": t, "context": c, "category": category, "kind": "example"}
                   for c, t in EXAMPLES])


def test_kind_and_context_round_trip_and_bad_kind_rejected():
    raw.add_items([{"text": "I think small teams ship faster.", "category": "work", "kind": "opinion",
                    "since": "2025"}])
    add_examples()
    kinds = sorted({i["kind"] for i in raw.items()})
    assert kinds == ["example", "opinion"]
    ex = [i for i in raw.items() if i["kind"] == "example"]
    assert ex[0]["context"]
    with pytest.raises(ValueError, match="unknown kind"):
        raw.add_items([{"text": "x", "category": "work", "kind": "rumour"}])


def test_old_brain_gets_new_columns(tmp_path, monkeypatch):
    home = tmp_path / "old"
    (home / "raw").mkdir(parents=True)
    con = sqlite3.connect(home / "raw" / "brain.sqlite")
    con.execute("CREATE TABLE items(id TEXT PRIMARY KEY, text TEXT NOT NULL, about TEXT NOT NULL DEFAULT 'me',"
                " category TEXT NOT NULL, edge_s TEXT, edge_rel TEXT, edge_o TEXT, src TEXT, since TEXT,"
                " conf TEXT, by TEXT, status TEXT, created TEXT, updated TEXT)")
    con.execute("INSERT INTO items(id,text,category,status) VALUES('f1','old fact','work','active')")
    con.commit()
    con.close()
    monkeypatch.setenv("TWIN_HOME", str(home))
    store.init()
    assert raw.items()[0]["kind"] == "fact"


def test_examples_are_not_facts_but_are_searchable_as_examples():
    add_examples()
    raw.add_items([{"text": "I work at Northwind Ltd.", "category": "work"}])
    build.rebuild("pro")
    d = store.persona_dir("pro")
    assert [f["text"] for f in store.read_jsonl(d / "facts.jsonl")] == ["I work at Northwind Ltd."]
    assert len(store.read_jsonl(d / "examples.jsonl")) == 5
    assert "buried in work" not in mcp_read.search("how are things at work")
    out = mcp_read.examples("hey how are things")
    assert "me: " in out and "(when: " in out


def test_examples_follow_persona_rules():
    add_examples(category="family")
    build.rebuild("pro")
    assert store.read_jsonl(store.persona_dir("pro") / "examples.jsonl") == []
    assert "me:" not in mcp_read.examples("hello")


def test_fingerprint_and_brief_describe_measured_voice():
    fp = style.fingerprint([{"text": t} for _, t in EXAMPLES])
    assert fp["n"] == 5 and fp["lowercase_start"] == 1.0 and fp["emoji"] == 0.0
    assert "yaar" in " ".join(fp["phrases"]) or "tbh" in " ".join(fp["phrases"]) or "haha" in fp["openers"]
    add_examples()
    build.rebuild("pro")
    b = mcp_read.brief()
    assert "Measured from 5 of my real messages" in b and "lowercase" in b


def test_check_flags_chatbot_habits_and_passes_plain_text():
    fp = style.fingerprint([{"text": t} for _, t in EXAMPLES])
    assert style.check("haha yeah all good, busy week", "how are you?", fp) == []
    bad = style.check("Great question! I don't have anything on that to share. Let me know if you need more.",
                      "what did you eat?", fp)
    assert any("great question" in f.lower() for f in bad)
    assert any("refusal" in f for f in bad)
    assert any("assistant phrase" in f for f in bad)
    assert any("bullets" in f for f in style.check("- one\n- two", "", fp))
    assert any("Too long" in f for f in style.check("word " * 120, "hi", fp))
    assert any("emoji" in f for f in style.check("sure 😂", "hi", fp))
    assert any("notes" in f for f in style.check("according to my notes I live there", "", fp))


def test_check_reply_tool_uses_owner_fingerprint():
    add_examples()
    build.rebuild("pro")
    assert mcp_read.check_reply("haha all good", "how are you") == "OK. Send it as it is."
    assert mcp_read.check_reply("All good — thanks", "how are you").startswith("Fix before sending")


def test_stale_fact_is_flagged_older_in_search():
    raw.add_items([
        {"text": "I live in Pune.", "category": "work", "since": "2018",
         "edge": {"s": "me", "rel": "lives_in", "o": "Pune"}},
        {"text": "I live in Leeds.", "category": "work", "since": "2023",
         "edge": {"s": "me", "rel": "lives_in", "o": "Leeds"}},
    ])
    build.rebuild("pro")
    facts = {f["text"]: f for f in store.read_jsonl(store.persona_dir("pro") / "facts.jsonl")}
    assert facts["I live in Pune."].get("stale") and not facts["I live in Leeds."].get("stale")
    out = mcp_read.search("where do you live")
    assert "[2018 · older] I live in Pune." in out and "[2023] I live in Leeds." in out


def test_search_labels_opinions_and_never_scripts_a_refusal():
    raw.add_items([{"text": "I think small teams ship faster.", "category": "work", "kind": "opinion",
                    "since": "2025"}])
    build.rebuild("pro")
    out = mcp_read.search("what do you think about team size")
    assert "[opinion · 2025] I think small teams ship faster." in out
    empty = mcp_read.search("zzzz qqqq")
    assert "I don't have anything on that to share" not in out + empty
    assert "'missing' move" in out and ("ask_owner" in empty or "'missing' move" in empty)


def test_ask_owner_appends_redacted_deduped_and_never_touches_facts():
    build.rebuild("pro")
    before = raw.items()
    r = mcp_read.ask_owner("Are you coming to the wedding? call me on +44 7700 900123", who="Meera")
    assert "Noted" in r
    assert "Already noted" in mcp_read.ask_owner("Are you coming to the wedding? call me on +44 7700 900123")
    rows = store.read_jsonl(store.home() / "inbox.jsonl")
    assert len(rows) == 1 and rows[0]["who"] == "Meera" and rows[0]["persona"] == "pro"
    assert "7700" not in json.dumps(rows)
    assert raw.items() == before


def test_inbox_becomes_asked_question_and_answer_closes_it():
    from brainkit import questions
    build.rebuild("pro")
    mcp_read.ask_owner("are you coming to the wedding on the 14th?", who="Meera")
    questions.sync()
    asked = [q for q in questions.all("open") if q["kind"] == "asked"]
    assert len(asked) == 1 and "Meera asked your twin" in asked[0]["text"]
    assert questions.next(5)[0]["kind"] == "asked"
    questions.answer(asked[0]["id"], "Yes, I'll be there.")
    assert store.read_jsonl(store.home() / "inbox.jsonl")[0]["status"] == "answered"
    questions.sync()
    assert not [q for q in questions.all("open") if q["kind"] == "asked"]


def test_write_persona_text_replaces_voice_and_redacts():
    from brainkit import mcp_manage
    mcp_manage.write_persona_text("pro", "voice", "- Short, lowercase.\n- Mail me at a@b.com")
    v = (store.persona_dir("pro") / "voice.md").read_text()
    assert v.startswith("# Voice") and "lowercase" in v and "a@b.com" not in v
    build.rebuild("pro")
    assert "Short, lowercase." in mcp_read.brief()


def test_check_flags_deferral_about_own_life_but_not_about_plans():
    assert any("putting off" in f for f in style.check("let me check and get back to you on that",
                                                    "how are the kids?"))
    assert any("putting off" in f for f in style.check("let me think about it and come back to you",
                                                    "do you think fame changes people?"))
    assert style.check("let me check my week and get back to you", "drinks on saturday?") == []
    assert style.check("let me check and come back on that", "did you see the deck I sent?") == []


def test_life_card_in_brief_spreads_categories_and_respects_persona():
    policy.define_relation("child_of", words=["child", "kid", "son", "daughter"])
    policy.set_rule("pro", "family", "deny")
    raw.add_items([
        {"text": "I run Northwind Ltd.", "category": "work",
         "edge": {"s": "me", "rel": "works_at", "o": "Northwind Ltd"}},
        {"text": "I live in Leeds.", "category": "work", "since": "2023",
         "edge": {"s": "me", "rel": "lives_in", "o": "Leeds"}},
        {"text": "I lived in Pune.", "category": "work", "since": "2018",
         "edge": {"s": "me", "rel": "lives_in", "o": "Pune"}},
        {"text": "I think small teams win.", "category": "work", "kind": "opinion"},
        {"text": "Asha is my daughter.", "category": "family",
         "edge": {"s": "me", "rel": "child_of", "o": "Asha"}},
    ])
    policy.create_persona("home", "friends", "everything", "nothing")
    for c in ("work", "family", "small-talk"):
        policy.set_rule("home", c, "allow")
    build.rebuild("pro")
    build.rebuild("home")
    pro = (store.persona_dir("pro") / "card.md").read_text()
    home = (store.persona_dir("home") / "card.md").read_text()
    assert "I run Northwind Ltd." in pro and "I live in Leeds." in pro
    assert "Pune" not in pro and "small teams" not in pro and "Asha" not in pro
    assert "Asha is my daughter." in home and "- child: Asha" in home
    assert "things I always know" in mcp_read.brief()


def test_brief_carries_real_message_anchors_from_distinct_contexts():
    add_examples()
    build.rebuild("pro")
    b = mcp_read.brief()
    assert "Some of my real messages" in b
    shown = [t for _, t in EXAMPLES if t in b]
    assert len(shown) == 5
    a = style.anchors([{"text": "hi there", "context": "friend asks"}] * 3 + [{"text": "ok", "context": "boss asks"}], n=2)
    assert {x["context"] for x in a} == {"friend asks", "boss asks"}


def test_reply_questions_one_situation_at_a_time_and_close_when_covered():
    from brainkit import questions
    raw.add_items([{"text": "I run Northwind Ltd.", "category": "work"}])
    questions.sync()
    fam = [q for q in questions.all("open") if q.get("field") == "reply_family"]
    assert len(fam) == 1 and fam[0]["reply_to"] == "did you eat? call me when you're free"
    assert "How would you reply?" in fam[0]["text"]
    raw.add_items([{"text": f"msg {k}", "context": "mother says hi", "category": "small-talk",
                    "kind": "example", "by": "you"} for k in range(10)])
    questions.sync()
    assert not [q for q in questions.all("open") if q.get("field") == "reply_family"]


def test_answering_a_reply_question_files_a_pair_and_moves_on():
    from brainkit import questions
    questions.sync()
    q = next(q for q in questions.all("open") if q.get("field") == "reply_friends")
    questions.answer(q["id"], "haha alive. barely", category="small-talk")
    ex = [i for i in raw.items() if i.get("kind") == "example"]
    assert ex[-1]["text"] == "haha alive. barely"
    assert ex[-1]["context"] == "close friend says: heyyy long time! what's going on with you?"
    questions.sync()
    nxt = [q for q in questions.all("open") if q.get("field") == "reply_friends"]
    assert nxt and nxt[0]["reply_to"] == "ugh worst week ever. my manager is impossible"
    before = len([i for i in raw.items() if i.get("kind") == "example"])
    out = questions.answer(nxt[0]["id"], "skip")
    assert out["status"] == "declined"
    assert len([i for i in raw.items() if i.get("kind") == "example"]) == before


def test_reply_answer_asks_for_category_when_none_fits():
    from brainkit import questions
    q = questions.add_reply("sister", "so are you coming home for diwali or not")
    out = questions.answer(q["id"], "yes!! landing on the 30th")
    assert out["filed"] == 0 and "category=" in out["fix"]
    questions.answer(q["id"], "yes!! landing on the 30th", category="small-talk")
    assert any(i.get("context") == "sister says: so are you coming home for diwali or not"
               for i in raw.items())


def test_check_flags_moving_own_story_to_a_call_and_meta_talk():
    assert any("putting off" in f for f in style.check(
        "how we met is a longer story, ask me when we're in the same room", "how did you two meet?"))
    assert any("putting off" in f for f in style.check("that one's not for text", "you sleeping at all?"))
    assert any("notes" in f for f in style.check("I went with the list from memory, `stack`", "why?"))
    assert any("putting off" in f for f in style.check("let me check where we are on hiring",
                                                       "Are you hiring? I've done 4 years of backend"))


def test_manager_is_told_to_rewrite_voice_when_new_examples_arrive():
    from brainkit import mcp_manage
    out = mcp_manage.add_items([{"text": t, "context": c, "category": "small-talk", "kind": "example"}
                                for c, t in EXAMPLES])
    assert "pro/voice" in out.get("next", "")
    mcp_manage.write_persona_text("pro", "voice", "- Often lowercase.")
    assert "pro/voice" not in (mcp_manage.sync().get("next") or "")
    out = mcp_manage.add_items([{"text": f"new msg {i}", "context": "friend", "category": "small-talk",
                                 "kind": "example"} for i in range(3)])
    assert "pro/voice" in out.get("next", "")


def test_local_register_check_uses_nearest_real_messages():
    near_low = [{"text": "haha all good yaar"}, {"text": "launch went fine!! fixing stuff"},
                {"text": "nothing much, sleeping"}, {"text": "thank you yaar!!"}]
    assert any("lowercase" in f for f in style.local_check("All good, thanks for asking.", near_low))
    near_formal = [{"text": "Hi Arjun. Thanks for the note. We closed our pre-seed in January."},
                   {"text": "Happy to share the update deck. Numbers are in there."},
                   {"text": "Not raising right now. Seed conversations start in January."}]
    assert any("capitals" in f for f in style.local_check("hey yeah not raising lol", near_formal))
    assert any("haha" in f for f in style.local_check("Haha we are not raising right now.", near_formal))
    bursts = [{"text": "ugh\nok so the pdf thing broke again"}, {"text": "lol yes\nstill checking truck bills"},
              {"text": "define sleeping\nok 6 hrs"}]
    assert any("own line" in f for f in style.local_check(
        "ok so the release went fine and the customers are happy and we are fixing the last bugs now", bursts))


def test_check_tiers_deferral_by_kind_of_ask():
    # a real request: holding is fine
    assert style.check("let me check my week", "can we meet up thursday?") == []
    # routine and status: you know these
    assert any("putting off" in f for f in style.check("let me check and get back", "are you hiring?"))
    # plannable words but no new ask: a gentle nudge
    assert any("NEW commitment" in f for f in style.check("i'll check and get back", "how did the interview go on monday?"))
    money = style.check("easier to talk valuation on a call", "what valuation are you thinking?")
    assert len(money) == 1 and "terms themselves" in money[0]
    assert any("status part" in f for f in style.check(
        "let me check where we are on the round and get back to you", "Are you raising right now? I'd love to put in a cheque"))


def test_check_flags_holding_back_what_memory_has():
    assert any("holding back" in f for f in style.check("keeping the family news to myself today", "how are your parents?"))
    assert not any("holding back" in f for f in style.check("they're good, baba walks 5k a day", "how are your parents?"))


def test_examples_and_check_prefer_messages_to_the_same_kind_of_person():
    rows = [("close friend asks about the weekend", "hahaha no way, see you sat"),
            ("close friend teases her", "lol ok fine"),
            ("investor asks about the round", "Thanks for the note. We are not raising until next year."),
            ("investors ask for the deck", "Happy to share the deck once it is ready. I will send it next week.")]
    raw.add_items([{"text": t, "context": c, "category": "small-talk", "kind": "example"} for c, t in rows])
    build.rebuild("pro")
    out = mcp_read.examples("weekend plans", "investor")
    assert out.index("We are not raising") < out.index("hahaha")
    assert "capital" in mcp_read.check_reply("Not raising till next year, i think", "When are you raising?", "investor")
    assert "No messages to them (journalist)" in mcp_read.examples("weekend", "journalist")


def test_check_flags_vague_mirrored_and_copied_lines():
    assert any("vague" in f for f in style.check("not sure yet, family time for sure", "what are you up to this weekend"))
    assert any("mirrored" in f for f in style.check("busy week. what about you?", "what are you up to this weekend"))
    assert not any("mirrored" in f for f in style.check("good! how are you?", "hey how are you?"))
    assert style.copied("honestly I'd rather raise with two quarters we're proud of",
                        ["wait to raise until you have two quarters you're proud of"]) == "two quarters you're proud of" or \
        style.copied("I'd rather raise with two quarters we're proud of", ["raise with two quarters we're proud of, not tired"])
    assert style.copied("see you soon", ["see you soon then"]) == ""


def test_local_check_asks_for_usual_sign_off():
    near = [{"text": "Yes of course, see you Friday x"}, {"text": "Love you, call tomorrow x"},
            {"text": "Tell Dad I'm fine x"}]
    assert any("end with 'x'" in f for f in style.local_check("Yes, see you Friday.", near))
    assert not any("end with" in f for f in style.local_check("Yes, see you Friday x", near))


def test_examples_show_pairs_spread_and_typical_length():
    rows = [(f"close friend says: msg {n}", f"lol ok {'yeah ' * (n % 4)}see you") for n in range(12)]
    raw.add_items([{"text": t, "context": c, "category": "small-talk", "kind": "example"} for c, t in rows])
    build.rebuild("pro")
    out = mcp_read.examples("weekend", "close friend")
    assert "close friend: msg" in out and "\nme: lol ok" in out
    assert "usually" in out and "words" in out
    assert len({m for m in out.split() if m.isdigit()}) >= 3  # spread, not one cluster


def test_reply_answer_drops_keyboard_mash_and_put_offs():
    from brainkit import questions
    for junk in ("asdf", "idk man", "can we do this later", "not now"):
        q = questions.add_reply("sister", f"are you coming home? {junk}")
        out = questions.answer(q["id"], junk, category="small-talk")
        assert out["status"] == "declined", junk


def test_check_flags_stock_opener_closing_question_and_unasked_years():
    rows = [("close friend says: hows things", t) for t in
            ("all good, busy week", "ya fine. tired", "work is mad but ok", "not bad! shipping stuff")]
    raw.add_items([{"text": t, "context": c, "category": "small-talk", "kind": "example"} for c, t in rows])
    build.rebuild("pro")
    out = mcp_read.check_reply("Fair question. All good. Busy week. Shipping a lot. How about your side, all well?",
                               "hows things", "close friend")
    assert "open with 'fair question'" in out and "end on a question" in out
    assert "open with" not in mcp_read.check_reply("honestly all good, busy week", "hows things", "close friend")
    leak = mcp_read.check_reply("ya all good. I left out the rest of what memory has.", "hows things")
    assert "how you wrote the reply" in leak
    assert "didn't ask when" in mcp_read.check_reply("I worked there from 2015 to 2019.", "what did you do before?")
    assert "didn't ask when" not in mcp_read.check_reply("I joined in 2015.", "when did you join?")


def test_foils_show_bot_version_next_to_real_message():
    from brainkit import foils
    add_examples()
    import json as _j
    out = foils.generate(runner=lambda prompt: _j.dumps(
        {x["id"]: "Thanks so much for asking! Things are going really well overall." for x in foils.missing()}))
    assert out["made"] == len(EXAMPLES) and not foils.missing()
    build.rebuild("pro")
    ex = mcp_read.examples("how are things", "friend")
    assert "✗ a bot would send: Thanks so much" in ex and "me: " in ex


def test_whatsapp_budget_flags_long_replies_and_long_lines():
    from brainkit import style
    long = " ".join(["word"] * 40)
    assert any("Too long for WhatsApp" in f for f in style.check(long, "hey how's it going"))
    assert not any("Too long" in f for f in style.check(long, "any advice on hiring?"))
    one_line = " ".join(["word"] * 24)
    assert any("Split it" in f for f in style.check(one_line, "any advice on hiring?"))
    assert not style.whatsapp_budget("ya all good\nbusy week", "hows things")
