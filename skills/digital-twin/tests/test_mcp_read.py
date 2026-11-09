import json
import subprocess
import sys
from pathlib import Path

import pytest

from brainkit import graph as G
from brainkit import mcp_read, policy, search, store

ROOT = Path(__file__).resolve().parent.parent
NO_PERSONA = "No active persona is set. Ask the owner to set one in the twin manager."

DICT = {
    "relations": {
        "spouse_of": {"inverse": None, "symmetric": True, "single": True,
                      "words": ["spouse", "wife", "husband", "married"], "inverse_words": []},
        "educated_at": {"inverse": None, "symmetric": False, "single": False,
                        "words": ["studied", "college", "school", "university"],
                        "inverse_words": ["alumni"]},
    },
    "aliases": {"Asha K": "Asha"},
}
FACTS = [
    {"id": "f-1", "about": "me", "text": "I live in Springfield and enjoy cycling",
     "edge": None},
    {"id": "f-2", "about": "me", "text": "Asha is my spouse",
     "edge": {"s": "me", "rel": "spouse_of", "o": "Asha"}},
    {"id": "f-3", "about": "Asha", "text": "Asha studied at Lakeside College",
     "edge": {"s": "Asha", "rel": "educated_at", "o": "Lakeside College"}},
]


def make_persona(slug, facts):
    policy.create_persona(slug, "friends", "everything", "nothing")
    d = store.persona_dir(slug)
    (d / "facts.jsonl").write_text("\n".join(json.dumps(f) for f in facts) + "\n", encoding="utf-8")
    store.write_json(d / "graph.json", G.build_graph(facts, DICT))
    store.write_json(d / "dictionary.json", DICT)
    (d / "pages").mkdir(exist_ok=True)
    (d / "pages" / "Asha.md").write_text("# Asha\n- spouse\n", encoding="utf-8")
    (d / "profile.md").write_text("Profile text", encoding="utf-8")
    (d / "soul.md").write_text("SOUL-MARK", encoding="utf-8")
    (d / "voice.md").write_text("VOICE-MARK", encoding="utf-8")
    (d / "rules.md").write_text("RULES-MARK", encoding="utf-8")
    search.build_index(d, facts)
    return d


@pytest.fixture(autouse=True)
def twin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "brain"))
    store.init()
    mcp_read._cache.clear()


def test_no_active():
    for fn, args in ((mcp_read.search, ("cycling",)), (mcp_read.brief, ()), (mcp_read.walk, ("x",)),
                     (mcp_read.page, ("Asha",)), (mcp_read.profile, ())):
        assert fn(*args) == NO_PERSONA


def test_search_finds_fact_and_brief_and_profile():
    make_persona("friends", FACTS)
    policy.set_active("friends")
    assert "- I live in Springfield and enjoy cycling [f-1]" in mcp_read.search("where does cycling happen")
    b = mcp_read.brief()
    assert all(m in b for m in ("SOUL-MARK", "VOICE-MARK", "RULES-MARK"))
    assert mcp_read.profile() == "Profile text"


def test_relational_walk_first():
    make_persona("friends", FACTS)
    policy.set_active("friends")
    out = mcp_read.search("where did my spouse study")
    assert out.splitlines()[0].startswith("The ") and "Lakeside College" in out.splitlines()[0]
    assert "because:" in out and "Asha —" in out
    assert "Lakeside College" in mcp_read.walk("where did my spouse study")
    assert mcp_read.walk("who is the moon").startswith("No connection found.")
    assert len(out) <= 1900 + len(mcp_read.REPLY_HINT) + 2


def test_other_persona_isolated():
    make_persona("friends", FACTS)
    make_persona("work", [{"id": "f-9", "about": "me", "text": "Secret zeppelin hobby", "edge": None}])
    policy.set_active("friends")
    assert "zeppelin" not in mcp_read.search("zeppelin hobby")
    policy.set_active("work")
    assert "zeppelin" in mcp_read.search("zeppelin hobby")
    assert "cycling" not in mcp_read.search("cycling")


def test_cache_reloads_on_change():
    d = make_persona("friends", FACTS)
    policy.set_active("friends")
    assert "kayak" not in mcp_read.search("kayak")
    make_persona("friends", FACTS + [{"id": "f-4", "about": "me", "text": "I enjoy kayak trips", "edge": None}])
    assert "kayak" in mcp_read.search("kayak")


def test_page_alias():
    make_persona("friends", FACTS)
    policy.set_active("friends")
    assert mcp_read.page("Asha K").startswith("# Asha")
    assert mcp_read.page("nobody") == "No page for that."


def test_missing_persona_dir():
    make_persona("friends", FACTS)
    policy.set_active("friends")
    import shutil
    shutil.rmtree(store.persona_dir("friends"))
    assert mcp_read.search("cycling") == NO_PERSONA


def _tools(module, tmp_path):
    import os
    env = {**os.environ, "TWIN_HOME": str(tmp_path / "brain")}
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    p = subprocess.Popen([sys.executable, "-m", module], cwd=ROOT, env=env, text=True,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        def call(m):
            p.stdin.write(json.dumps(m) + "\n")
            p.stdin.flush()
            if "id" in m:
                while True:
                    r = json.loads(p.stdout.readline())
                    if r.get("id") == m["id"]:
                        return r
        init = call(msgs[0])
        assert "serverInfo" in init["result"]
        call(msgs[1])
        return sorted(t["name"] for t in call(msgs[2])["result"]["tools"])
    finally:
        p.kill()
        p.wait()


def test_stdio_smoke(tmp_path):
    assert _tools("brainkit.mcp_read", tmp_path) == ["brief", "page", "profile", "search", "walk"]
