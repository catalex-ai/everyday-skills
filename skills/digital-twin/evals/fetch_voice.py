"""Fetch a subject's own public words (interview answers, talks) for voice evals.

    python evals/fetch_voice.py --out ~/.twin-corpora/<name> \
        [--wikiquote "<Page title>"] [--ted <talk_slug> ...] [--qa <file.jsonl>] [--heldout 0.3]

--qa: interview answers collected by hand from public pages, one JSON record per
line: {source, url, date, setting, question, text, paraphrased, kind: "direct"}.
A share (--qa-heldout) is held out by interview, the rest trains.

Writes into the corpus folder (never into the repo):
- voice/records.jsonl   one record per utterance: source, url, setting, question
                        (when the source states it), text, kind ("direct")
- voice/editorial.jsonl third-party text (quotes ABOUT the subject, captions),
                        kept apart and never fed to the twin
- sources/voice-*.txt   the training part, as "things I said" documents
- voice_gold.jsonl      held-out direct answers, for the judge and the
                        style-probe scenarios

Only direct speech goes to sources/ and gold. Selection is by the source's own
structure, not by how quotable a line is, so catchphrases are not favoured.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

UA = "twin-eval/0.1 (personal research script)"


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def _clean_wiki(t: str) -> str:
    t = re.sub(r"<ref[^>]*/>", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+\s*([^\]]*)\]", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("'''", "").replace("''", "")
    return html.unescape(re.sub(r"\s+", " ", t)).strip()


_Q = re.compile(r"\((?:as an answer to the question|when asked|on being asked|asked)[:\s]*(.+?)\)\s*$", re.I)
_ABOUT = re.compile(r"\b(about|on him|on her|said of|quotes about|misattributed|disputed)\b", re.I)


def _not_speech(text: str) -> bool:
    """A label before a quote ("When speaking to X in a stadium") or a chant."""
    w = re.findall(r"[a-z']+", text.lower())
    if len(text) < 70 and not re.search(r"[.!?\"”]$", text):
        return True
    return len(w) >= 6 and len(set(w)) / len(w) < 0.4


def wikiquote(title: str) -> tuple[list[dict], list[dict]]:
    api = ("https://en.wikiquote.org/w/api.php?action=parse&prop=wikitext&format=json"
           "&formatversion=2&redirects=1&page=" + urllib.parse.quote(title))
    wt = json.loads(get(api))["parse"]["wikitext"]
    url = "https://en.wikiquote.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    direct, editorial = [], []
    section, setting, third_party = "", "", False
    for line in wt.splitlines():
        m = re.match(r"^(=+)\s*(.*?)\s*\1\s*$", line)
        if m:
            section = _clean_wiki(m.group(2))
            third_party = bool(_ABOUT.search(section)) or section.lower() in ("external links", "see also")
            setting = section
            continue
        if line.startswith("[[File:"):
            editorial.append({"source": "wikiquote", "url": url, "section": section,
                              "text": _clean_wiki(line), "why": "image caption"})
            continue
        if not line.startswith("*"):
            if line.strip() and not line.startswith(("{", "|", "[[Category")) and section:
                setting = f"{section}. {_clean_wiki(line)}"[:300]
            continue
        depth = len(line) - len(line.lstrip("*"))
        body = line.lstrip("*").strip()
        raw_q = None
        body = re.sub(r"(''+)\s*$", "", body).rstrip()
        body = re.sub(r"''(\([^()]*\))\s*$", r"\1", body)
        mq = _Q.search(body)
        if mq:
            raw_q = _clean_wiki(mq.group(1)).rstrip(".")
            body = body[:mq.start()]
        text = _clean_wiki(body)
        if len(text) < 25 or _not_speech(text):
            continue
        rec = {"source": "wikiquote", "url": url, "section": section, "setting": setting,
               "question": raw_q, "text": text}
        if third_party:
            editorial.append({**rec, "why": "section about the subject"})
        elif depth >= 3:
            editorial.append({**rec, "why": "citation or note"})
        else:
            direct.append({**rec, "kind": "direct"})
    return direct, editorial


def ted(slug: str) -> list[dict]:
    url = f"https://www.ted.com/talks/{slug}/transcript"
    h = get(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    data = json.loads(m.group(1))
    paras = data["props"]["pageProps"]["transcriptData"]["translation"]["paragraphs"]
    out = []
    for i, p in enumerate(paras):
        text = " ".join(c["text"].replace("\n", " ") for c in p.get("cues", [])).strip()
        text = re.sub(r"\((?:Laughter|Applause|Music)[^)]*\)", "", text).strip()
        if len(text) >= 25 and not _not_speech(text):
            out.append({"source": "ted", "url": url, "section": f"talk part {i:02d}",
                        "setting": "A public talk I gave on stage", "question": None,
                        "text": text, "kind": "direct"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--wikiquote")
    ap.add_argument("--ted", nargs="*", default=[])
    ap.add_argument("--qa")
    ap.add_argument("--qa-heldout", type=float, default=0.4)
    ap.add_argument("--heldout", type=float, default=0.3)
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    (out / "voice").mkdir(parents=True, exist_ok=True)
    (out / "sources").mkdir(parents=True, exist_ok=True)

    direct, editorial = [], []
    if a.wikiquote:
        d, e = wikiquote(a.wikiquote)
        direct += d
        editorial += e
    for s in a.ted:
        direct += ted(s)
    if a.qa:
        for line in Path(a.qa).expanduser().read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind", "direct") != "direct" or not str(r.get("text", "")).strip():
                continue
            direct.append({"source": "qa", "url": r.get("url", ""), "section": r.get("url", ""),
                           "setting": r.get("setting") or r.get("source"), "outlet": r.get("source"),
                           "date": r.get("date"), "question": r.get("question"),
                           "question_paraphrased": bool(r.get("paraphrased")),
                           "text": " ".join(str(r["text"]).split()), "kind": "direct"})
    for i, r in enumerate(direct):
        r["id"] = f"v{i:03d}"
    with (out / "voice" / "records.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in direct)
    with (out / "voice" / "editorial.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in editorial)

    # Held out: every answer with a stated question (best probes), plus every
    # k-th other record. The rest trains.
    step = max(2, round(1 / a.heldout)) if a.heldout else 0
    gold, train = [], []
    qa_urls = sorted({r["url"] for r in direct if r["source"] == "qa"})
    # Hold out whole interviews, so a held-out answer's neighbours never train.
    f = a.qa_heldout
    qa_gold = {u for i, u in enumerate(qa_urls) if int((i + 1) * f) > int(i * f)}
    for i, r in enumerate(direct):
        if r["source"] == "qa":
            (gold if r["url"] in qa_gold else train).append(r)
        else:
            (gold if r.get("question") or (step and i % step == 0) else train).append(r)
    with (out / "voice_gold.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in gold)

    for old in (out / "sources").glob("voice-*.txt"):
        old.unlink()
    groups: dict[tuple, list[dict]] = {}
    for r in train:
        groups.setdefault((r["source"], r["section"] if r["source"] != "ted" else r["url"]), []).append(r)
    for n, ((src, sec), rs) in enumerate(groups.items()):
        head = (f"My own words, verbatim. Source: {src}, {rs[0]['url']}. "
                f"Setting: {rs[0].get('setting') or sec}.\n\n")
        body = "\n\n".join(f"Asked: {r['question']}\nMe: {r['text']}" if r.get("question")
                           else f"Me: {r['text']}" for r in rs)
        (out / "sources" / f"voice-{n:02d}.txt").write_text(head + body + "\n", encoding="utf-8")
    print(json.dumps({"direct": len(direct), "editorial": len(editorial), "gold": len(gold),
                      "train": len(train), "files": len(groups)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
