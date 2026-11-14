from brainkit import style


def test_joke_gets_no_holding_reply():
    fixes = style.tone_check("Not sure off the top of my head, let me check and get back to you.", "joking")
    assert any("playing, not asking" in f for f in fixes)


def test_witty_reply_to_joke_passes():
    assert style.tone_check("haha zero cats, all agents. the cats are on the roadmap", "joking") == []


def test_nonsense_help_desk_reply_flagged():
    assert style.tone_check("Sorry, I didn't catch that. What were you trying to say?", "nonsense")


def test_sarcasm_not_thanked():
    assert any("sarcasm" in f for f in style.tone_check("Thank you so much!", "sarcastic"))


def test_no_laughing_at_sad_news():
    assert style.tone_check("oh no haha", "sincere")
    assert style.tone_check("I'm so sorry. Here if you need anything.", "sincere") == []


def test_formal_no_slang():
    assert style.tone_check("haha sure bro", "formal")


def test_no_tone_no_check():
    assert style.tone_check("let me check", "") == []


def test_errand_half_promise_flagged():
    assert style.tone_check("Haan, I'll see if I can pick it up and let you know.", "nonsense")


def test_sarcasm_concede_and_defer_flagged():
    fixes = style.tone_check("Ha, fair point. Let me check on that and get back to you.", "sarcastic")
    assert any("conceding" in f for f in fixes) and any("playing, not asking" in f for f in fixes)


def test_closing_gets_a_few_words():
    assert style.tone_check("gn man", "closing") == []
    assert any("closing" in f for f in style.tone_check("gn! did you end up taking the job?", "closing"))
    assert style.tone_check("ha, thanks. you should come by sometime, the office is still a mess", "closing")


def test_venting_gets_no_advice():
    assert style.tone_check("ugh that's so unfair. he's the worst", "venting") == []
    assert any("venting" in f for f in style.tone_check("that sucks. you should talk to HR", "venting"))


def test_good_news_no_but():
    assert style.tone_check("YESSS. so happy for you", "excited") == []
    assert style.tone_check("congrats! but make sure you negotiate the notice period", "excited")
