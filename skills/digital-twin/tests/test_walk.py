import pytest

from brainkit import graph as G
from brainkit import router

DICT = {
    "relations": {
        "spouse_of": {"inverse": None, "symmetric": True, "single": True,
                      "words": ["spouse", "wife", "husband", "married"], "inverse_words": []},
        "educated_at": {"inverse": None, "symmetric": False, "single": False,
                        "words": ["studied", "college", "school", "university", "educated"],
                        "inverse_words": ["alumni", "student"]},
        "founded": {"inverse": None, "symmetric": False, "single": False,
                    "words": ["founded", "company I founded"], "inverse_words": ["founder"]},
        "works_at": {"inverse": None, "symmetric": False, "single": False,
                     "words": ["employer", "works at"],
                     "inverse_words": ["employee", "staff", "works at"]},
        "parent_of": {"inverse": None, "symmetric": False, "single": False,
                      "words": ["child", "son", "daughter", "kids"],
                      "inverse_words": ["parent", "father", "mother"]},
    },
    "aliases": {"Northwind": "Northwind Ltd"},
}


def it(i, s, rel, o):
    return {"id": i, "text": f"{s} {rel} {o}", "about": "me", "category": "c",
            "edge": {"s": s, "rel": rel, "o": o}}


ITEMS = [
    it("f1", "me", "spouse_of", "Asha"),
    it("f2", "Asha", "educated_at", "Lakeside College"),
    it("f3", "me", "founded", "Northwind Ltd"),
    it("f4", "Ravi", "works_at", "Northwind Ltd"),
    it("f5", "Meera", "works_at", "Northwind"),
    it("f6", "me", "parent_of", "Kabir"),
]


@pytest.fixture
def g():
    return G.build_graph(ITEMS, DICT)


def first(g, q):
    r = G.walk(q, g, DICT)
    assert r, q
    return r[0]


def test_chain_wife(g):
    r = first(g, "where did my wife study")
    assert r["answer"] == "Lakeside College"
    assert r["kind"] == "chain"
    assert ["Asha", "educated_at", "Lakeside College"] in r["chain"]
    assert len(r["chain"]) == 2
    assert r["restated"].endswith(": Lakeside College")
    assert "wife" in r["restated"]


def test_chain_spouse_college(g):
    assert first(g, "where did my spouse go to college")["answer"] == "Lakeside College"


def test_possessive_and_of(g):
    assert first(g, "my spouse's school")["answer"] == "Lakeside College"
    assert first(g, "the school of my spouse")["answer"] == "Lakeside College"
    assert first(g, "the school of the spouse of me")["answer"] == "Lakeside College"


def test_set_works_at(g):
    for q in ("who works at the company I founded", "who works at Northwind"):
        r = first(g, q)
        assert r["kind"] == "set"
        assert set(r["answer"]) == {"Ravi", "Meera"}


def test_who_else(g):
    r = first(g, "who else works at Northwind besides Ravi")
    assert r["answer"] == ["Meera"]


def test_count(g):
    r = first(g, "how many people work at Northwind")
    assert r["kind"] == "count" and r["answer"] == "2"
    r = first(g, "how many kids do I have")
    assert r["kind"] == "count" and r["answer"] == "1"


def test_path(g):
    r = first(g, "how is Asha connected to Northwind")
    assert r["kind"] == "path"
    assert "me" in r["answer"]
    assert r["answer"][0] == "Asha" and r["answer"][-1] == "Northwind Ltd"
    assert len(r["chain"]) == 2


def test_inverse_word(g):
    assert first(g, "who is Kabir's father")["answer"] == "me"


def test_canonical():
    assert G.canonical("northwind", DICT) == "Northwind Ltd"
    assert G.canonical("my", DICT) == "me"
    assert G.canonical("I", DICT) == "me"
    assert G.canonical("Myself", DICT) == "me"


def test_build_deterministic_and_shape(g):
    assert G.build_graph(ITEMS, DICT) == g
    assert G.build_graph(list(reversed(ITEMS)), DICT) == g
    assert "me" in g["nodes"]
    assert "Northwind Ltd" in g["nodes"] and "Northwind" not in g["nodes"]
    assert "f5" in g["nodes"]["Northwind Ltd"]["facts"]
    assert "Northwind" in g["nodes"]["Northwind Ltd"]["aliases"]


def test_symmetric_once():
    items = [it("a", "me", "spouse_of", "Asha"), it("b", "Asha", "spouse_of", "me")]
    g = G.build_graph(items, DICT)
    assert len([e for e in g["edges"] if e["rel"] == "spouse_of"]) == 1


def test_inverse_stored_one_way():
    d = {"relations": {**DICT["relations"],
                       "child_of": {"inverse": "parent_of", "symmetric": False, "single": False,
                                    "words": ["parent"], "inverse_words": ["child"]}},
         "aliases": {}}
    d["relations"]["parent_of"] = {**d["relations"]["parent_of"], "inverse": "child_of"}
    items = [it("a", "me", "parent_of", "Kabir"), it("b", "Kabir", "child_of", "me")]
    g = G.build_graph(items, d)
    assert len(g["edges"]) == 1
    assert g["edges"][0]["rel"] == "child_of"
    assert G.walk("how many kids do I have", g, d)[0]["answer"] == "1"
    assert G.walk("who is Kabir's father", g, d)[0]["answer"] == "me"


def test_router(g):
    for q in ("where did my wife study", "who works at Northwind", "how many kids do I have",
              "who else works at Northwind besides Ravi", "how is Asha connected to Northwind",
              "who is Kabir's father", "Asha and I went to the same school as Ravi",
              "who is related to me"):
        assert router.needs_graph(q, g, DICT), q
    for q in ("what did I study", "tell me about my work", "what languages do I speak"):
        assert not router.needs_graph(q, g, DICT), q


def test_unknown_relation_word_no_guess(g):
    assert G.walk("who mentors Ravi", g, DICT) == []
    assert G.walk("who is Ravi's mentor", g, DICT) == []
    d2 = {"relations": {k: v for k, v in DICT["relations"].items() if k != "educated_at"},
          "aliases": DICT["aliases"]}
    # leftover unknown words are ignored: the anchor and the known word still answer
    r = G.walk("where did my wife study", g, d2)
    assert r and r[0]["answer"] == "Asha"
    assert G.walk("hello there", g, DICT) == []


def test_mentions(g):
    m = G.mentions("who is Kabir's father", g, DICT)
    assert m["entities"] == ["Kabir"]
    assert ("parent_of", "in") in m["relations"]


# ---- shape of the manager-written dictionary and graph (placeholder names)

REAL_D = {
    "relations": {
        "child_of": {"inverse": "parent_of", "symmetric": False, "single": False,
                     "words": ["parent", "father", "mother"],
                     "inverse_words": ["child", "son", "daughter"]},
        "parent_of": {"inverse": "child_of", "symmetric": False, "single": False,
                      "words": ["child", "son", "daughter"],
                      "inverse_words": ["parent", "father", "mother"]},
        "born_in": {"inverse": None, "symmetric": False, "single": True,
                    "words": ["birthplace"], "inverse_words": ["born"]},
        "studied_at": {"inverse": None, "symmetric": False, "single": False,
                       "words": ["school", "college", "university"], "inverse_words": ["student"]},
        "sibling_of": {"inverse": None, "symmetric": True, "single": False,
                       "words": ["sister", "brother", "sibling"],
                       "inverse_words": ["sister", "brother", "sibling"]},
        "owns": {"inverse": "owned_by", "symmetric": False, "single": False,
                 "words": ["owns", "owner of"], "inverse_words": ["owned by"]},
        "co_owns": {"inverse": "co_owned_by", "symmetric": False, "single": False,
                    "words": ["team", "franchise", "company"], "inverse_words": ["co-owner"]},
        "received": {"inverse": "awarded_to", "symmetric": False, "single": False,
                     "words": ["award", "honour", "order"], "inverse_words": ["awarded to"]},
    },
    "aliases": {"Pine Co": "Pine Company"},
}


def e(s, rel, o):
    return {"s": s, "rel": rel, "o": o, "fact": "f"}


REAL_G = {"nodes": {n: {"aliases": [], "facts": []} for n in
                    ["me", "Kian", "Kian Vale", "Mira", "Tobi", "Rhea Vale", "Oak Institute",
                     "Pine Company", "Elm Team", "Grand Medal", "Order of Birch", "Old Harbour",
                     "Nora", "Bay College", "Hill College"]},
          "edges": [e("Tobi", "child_of", "me"), e("Kian", "child_of", "me"),
                    e("Kian Vale", "child_of", "me"), e("Mira", "child_of", "me"),
                    e("me", "child_of", "Nora"), e("me", "sibling_of", "Rhea Vale"),
                    e("Pine Company", "owned_by", "me"), e("Elm Team", "co_owned_by", "me"),
                    e("Kian", "studied_at", "Oak Institute"), e("me", "studied_at", "Bay College"),
                    e("me", "studied_at", "Hill College"), e("me", "born_in", "Old Harbour"),
                    e("Grand Medal", "awarded_to", "me"), e("Order of Birch", "awarded_to", "me")]}


def rw(q):
    return G.walk(q, REAL_G, REAL_D)


def test_real_count_children_folds_bare_name():
    r = rw("how many children do I have?")
    assert r[0]["kind"] == "count" and r[0]["answer"] == "3"


def test_real_children_set():
    r = rw("who are my children?")
    assert set(r[0]["answer"]) == {"Kian Vale", "Mira", "Tobi"}


def test_real_siblings():
    assert rw("how many siblings do I have?")[0]["answer"] == "1"


def test_real_companies():
    assert set(rw("which company do I own?")[0]["answer"]) == {"Pine Company", "Elm Team"}
    assert rw("how many companies do I own?")[0]["answer"] == "2"


def test_real_appositive_study():
    assert rw("where did my son Kian study?")[0]["answer"] == "Oak Institute"


def test_real_born():
    assert rw("where was I born?")[0]["answer"] == "Old Harbour"


def test_real_awards():
    assert set(rw("what awards have I won?")[0]["answer"]) == {"Grand Medal", "Order of Birch"}


def test_real_parents_and_no_relation_word():
    assert rw("who is my mother")[0]["answer"] == "Nora"
    assert rw("tell me about Kian") == []


def test_inflection():
    assert G._stem("children") == G._stem("child")
    assert G._stem("companies") == G._stem("company")
    assert G._stem("studied") == G._stem("study") == G._stem("studies")
    assert G._stem("owned") == G._stem("owns") == G._stem("own")
    assert G._stem("siblings") == G._stem("sibling")


def test_router_real_shape():
    for q in ("who are my children?", "where was I born?", "what awards have I won?",
              "how many siblings do I have?"):
        assert router.needs_graph(q, REAL_G, REAL_D), q
    assert not router.needs_graph("what languages do I speak", REAL_G, REAL_D)
