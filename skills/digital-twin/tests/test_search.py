import sqlite3

import pytest

from brainkit import search

TEXTS = [
    "I studied economics at Lakeside College.",
    "I founded Northwind Ltd in 2010.",
    "My partner Asha is an architect.",
    "I live in a small coastal town.",
    "I enjoy hiking in the mountains every autumn.",
    "My brother Ravi works as a nurse.",
    "I drive an old green hatchback.",
    "I read science fiction novels before bed.",
    "I prefer tea over coffee in the morning.",
    "I adopted a grey cat named Pebble.",
    "I run a weekly book club for neighbours.",
    "I volunteer at the community garden on Sundays.",
]


def facts(texts=TEXTS):
    return [{"id": "f-%02d" % i, "about": "me", "text": t} for i, t in enumerate(texts)]


@pytest.fixture
def bm25_only(monkeypatch):
    monkeypatch.setattr(search, "_model", None)


@pytest.fixture
def embeddings():
    if not search.embedder_available():
        pytest.skip("embedding model not available")


def build(tmp_path, fs=None):
    search.build_index(tmp_path, fs or facts())
    return search.open_ro(tmp_path)


def test_bm25_where_did_i_study(tmp_path, bm25_only):
    idx = build(tmp_path)
    assert not (tmp_path / "vectors.npy").exists()
    assert idx.search("where did I study")[0]["text"].startswith("I studied economics")
    idx.close()


@pytest.mark.network
def test_hybrid_where_did_i_study(tmp_path, embeddings):
    idx = build(tmp_path)
    assert (tmp_path / "vectors.npy").exists()
    assert idx.search("where did I study")[0]["text"].startswith("I studied economics")
    idx.close()


@pytest.mark.network
def test_hybrid_partner_top3(tmp_path, embeddings):
    idx = build(tmp_path)
    top = [r["text"] for r in idx.search("who is my partner")[:3]]
    assert any("Asha" in t for t in top)
    idx.close()


def test_rare_token_bm25(tmp_path, bm25_only):
    idx = build(tmp_path)
    res = idx.search("Northwind")
    assert res[0]["id"] == "f-01" and res[0]["score"] > 0
    idx.close()


def test_read_only(tmp_path, bm25_only):
    idx = build(tmp_path)
    assert idx.search("Asha")
    with pytest.raises(sqlite3.OperationalError):
        idx._con.execute("INSERT INTO facts(id, about, text) VALUES ('x','me','y')")
    idx.close()


def test_rebuild_replaces(tmp_path, bm25_only):
    build(tmp_path).close()
    idx = build(tmp_path, facts(TEXTS[:1] + TEXTS[2:]))
    assert idx.search("Northwind") == []
    assert idx.search("Asha")
    idx.close()
    assert not list(tmp_path.glob("*.tmp"))


def test_fts_syntax_does_not_raise(tmp_path, bm25_only):
    idx = build(tmp_path)
    for q in ['"AND OR (*', "NEAR(", "a:b -c ^d", "", "   ", "***"]:
        assert isinstance(idx.search(q), list)
    assert idx.search("") == []
    idx.close()
