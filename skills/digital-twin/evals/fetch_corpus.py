"""Build a local eval corpus about a public figure, treated as the "owner".

    python evals/fetch_corpus.py --seed <WIKIDATA_QID> --out ~/.twin-corpora/<name>

The subject is only ever a command-line argument. Output goes outside the repo:

  DIR/sources/NN-<slug>.txt   the seed's article, one file per section in article
                              order (00 is the lead), then neighbours' intros
  DIR/heldout/NN-<slug>.txt   every 4th non-lead section, "in the owner's head"
  DIR/truth.json              [{s, s_aliases, p, p_label, o, o_aliases, cls, hop, via}]
                              the seed's own label is "me"; its real label is in meta.json
  DIR/meta.json               {seed, label, fetched}

Text is from Wikipedia (CC BY-SA 4.0) and Wikidata (CC0).
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

UA = "twin-eval-corpus/0.1 (local research)"

PERSONAL = {
    "P26": "spouse", "P40": "child", "P22": "father", "P25": "mother",
    "P3373": "sibling", "P551": "residence", "P19": "place of birth", "P1038": "relative",
}
PROFESSIONAL = {
    "P69": "educated at", "P108": "employer", "P166": "award received", "P1830": "owner of",
    "P127": "owned by", "P112": "founded by", "P463": "member of", "P800": "notable work",
    "P39": "position held", "P106": "occupation", "P1411": "nominated for",
}
# Inverse relations: things that name the seed as their owner / founder.
INVERSE = {"P127": "owns", "P112": "founded"}
PLACE = {"P131": "located in", "P17": "country"}
FAMILY = ("P26", "P40", "P22", "P25", "P3373", "P1038")
LABEL = {**PERSONAL, **PROFESSIONAL, **PLACE}
CLS = {**{p: "personal" for p in PERSONAL}, **{p: "professional" for p in PROFESSIONAL}}
TAIL = {"see also", "references", "notes", "further reading", "external links",
        "bibliography", "sources", "citations"}


def get(url: str) -> dict:
    """GET json, 3 retries. A 429 waits out the rate limit."""
    for attempt in range(4):
        try:
            time.sleep(0.2)
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:  # rate limits, timeouts
            if attempt == 3:
                print(f"  warning: {url[:90]}... failed: {e}", file=sys.stderr)
                return {}
            wait = 3 + attempt * 5
            if getattr(e, "code", None) == 429:
                ra = getattr(e, "headers", {}).get("Retry-After", "") if hasattr(e, "headers") else ""
                wait = min(90, max(int(ra) if ra.isdigit() else 0, 20))
            print(f"  retry {attempt + 1} in {wait}s", file=sys.stderr, flush=True)
            time.sleep(wait)
    return {}


def entities(ids: list[str], claims: bool) -> dict:
    out: dict = {}
    ids = sorted(set(ids))
    props = "labels|aliases|sitelinks" + ("|claims" if claims else "")
    for i in range(0, len(ids), 50):
        q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]),
                                    "props": props, "languages": "en", "sitefilter": "enwiki",
                                    "format": "json"})
        out.update(get(f"https://www.wikidata.org/w/api.php?{q}").get("entities", {}))
    return out


def targets(e: dict, props) -> list[tuple[str, str]]:
    out = []
    for p in props:
        for c in e.get("claims", {}).get(p, []):
            v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(v, dict) and str(v.get("id", "")).startswith("Q"):
                out.append((p, v["id"]))
    return out


def inverse_of(qid: str, prop: str) -> list[str]:
    """Entities whose `prop` points at qid, via the search API (the SPARQL endpoint is often throttled)."""
    q = urllib.parse.urlencode({"action": "query", "list": "search", "format": "json", "srlimit": 80,
                                "srsearch": f"haswbstatement:{prop}={qid}"})
    rows = get(f"https://www.wikidata.org/w/api.php?{q}").get("query", {}).get("search", [])
    return [r["title"] for r in rows if re.fullmatch(r"Q\d+", r["title"])]


def label_of(e: dict) -> str:
    return (e.get("labels", {}).get("en") or {}).get("value", "")


def aliases_of(e: dict) -> list[str]:
    lab = label_of(e)
    out = [lab] if lab else []
    short = re.sub(r"\s*\(.*?\)\s*$", "", lab).strip()
    if short and short not in out:
        out.append(short)
    for a in e.get("aliases", {}).get("en", []):
        if a["value"] not in out:
            out.append(a["value"])
    return out


def is_human(e: dict) -> bool:
    return any(t == "Q5" for _, t in targets(e, ["P31"]))


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50] or "x"


def extract(title: str, intro: bool) -> str:
    params = {"action": "query", "prop": "extracts", "explaintext": 1, "titles": title,
              "format": "json", "redirects": 1}
    if intro:
        params["exintro"] = 1
    pages = get("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)).get("query", {}).get("pages", {})
    return (next(iter(pages.values()), {}).get("extract") or "").strip()


def split_sections(text: str) -> list[tuple[str, str]]:
    """Level-2 sections in article order; the lead comes first as "lead"."""
    parts = re.split(r"(?m)^== (.+?) ==\s*$", text)
    secs = [("lead", parts[0].strip())]
    for i in range(1, len(parts), 2):
        title, body = parts[i].strip(), parts[i + 1].strip()
        if title.lower() in TAIL or len(body) < 80:
            continue
        secs.append((title, f"{title}\n\n{body}"))
    return [s for s in secs if s[1]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True, help="Wikidata id of the owner, e.g. Q42")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-neighbours", type=int, default=60)
    ap.add_argument("--heldout", type=float, default=0.25)
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    for d in ("sources", "heldout"):
        (out / d).mkdir(parents=True, exist_ok=True)
        for f in (out / d).glob("*.txt"):
            f.unlink()

    seed = entities([a.seed], claims=True).get(a.seed)
    if not seed or "missing" in seed:
        print("seed not found", file=sys.stderr)
        return 1
    seed_label = label_of(seed)

    # hop 1: (prop, target, inverse?)
    hop1 = [(p, t, False) for p, t in targets(seed, {**PERSONAL, **PROFESSIONAL})]
    for p in INVERSE:
        hop1 += [(p, t, True) for t in inverse_of(a.seed, p)]
    hop1 = [(p, t, inv) for p, t, inv in dict.fromkeys(hop1) if t != a.seed]
    ents = entities([t for _, t, _ in hop1], claims=True)

    # hop 2 from neighbours
    facts: list[dict] = []
    hop2: list[tuple[str, str, str, str, str]] = []   # (s, p, o, cls, via_prop)
    for p, t, inv in hop1:
        e = ents.get(t)
        if not e or "missing" in e or not label_of(e):
            continue
        facts.append({"s": a.seed, "p": p, "o": t, "cls": CLS[p], "hop": 1, "via": None, "inv": inv})
        if inv:
            continue
        rels = {**PERSONAL, **PROFESSIONAL} if (p in FAMILY and is_human(e)) else PLACE
        for p2, t2 in dict.fromkeys(targets(e, rels)):
            if t2 == a.seed:
                continue
            cls2 = CLS.get(p2, CLS[p])
            hop2.append((t, p2, t2, cls2, p))
    ents.update(entities([o for _, _, o, _, _ in hop2 if o not in ents], claims=False))
    for s, p2, o, cls2, via in hop2:
        if o in ents and label_of(ents[o]):
            facts.append({"s": s, "p": p2, "o": o, "cls": cls2, "hop": 2, "via": via, "inv": False})

    def block(q: str) -> dict:
        e = seed if q == a.seed else ents[q]
        return {"label": "me" if q == a.seed else label_of(e),
                "aliases": ["me", "I", "myself"] if q == a.seed else aliases_of(e)}

    truth = []
    for f in facts:
        s, o = block(f["s"]), block(f["o"])
        p_label = INVERSE[f["p"]] if f["inv"] else LABEL[f["p"]]
        truth.append({"s": s["label"], "s_aliases": s["aliases"], "p": f["p"], "p_label": p_label,
                      "o": o["label"], "o_aliases": o["aliases"], "cls": f["cls"], "hop": f["hop"],
                      "via": f["via"], "inverse": f["inv"]})
    (out / "truth.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False))

    # seed sections
    title = (seed.get("sitelinks", {}).get("enwiki") or {}).get("title")
    secs = split_sections(extract(title, intro=False)) if title else []
    n_held = 0
    non_lead = 0
    step = max(2, round(1 / a.heldout)) if a.heldout > 0 else 0
    for i, (name, text) in enumerate(secs):
        fname = f"{i:02d}-{slug(name)}.txt"
        held = False
        if name != "lead":
            non_lead += 1
            held = bool(step) and non_lead % step == 0
        (out / ("heldout" if held else "sources") / fname).write_text(text + "\n")
        n_held += held

    # neighbours: most truth edges first
    edges: dict[str, int] = {}
    for f in facts:
        for q in (f["s"], f["o"]):
            if q != a.seed:
                edges[q] = edges.get(q, 0) + 1
    hop1_ids = list(dict.fromkeys(t for _, t, _ in hop1 if t in ents))
    ranked = sorted(hop1_ids, key=lambda q: (-edges.get(q, 0), q))
    ranked = [q for q in ranked if (ents[q].get("sitelinks", {}).get("enwiki") or {}).get("title")]
    n = len(secs)
    n_nb = 0
    for q in ranked[:a.max_neighbours]:
        t = ents[q]["sitelinks"]["enwiki"]["title"]
        text = extract(t, intro=True)
        if len(text) < 80:
            continue
        (out / "sources" / f"{n:02d}-{slug(label_of(ents[q]))}.txt").write_text(f"{t}\n\n{text}\n")
        n += 1
        n_nb += 1

    (out / "meta.json").write_text(json.dumps({
        "seed": a.seed, "label": seed_label,
        "fetched": datetime.date.today().isoformat()}, indent=1, ensure_ascii=False))
    by_cls: dict[str, int] = {}
    for t in truth:
        k = f"{t['cls']}/hop{t['hop']}"
        by_cls[k] = by_cls.get(k, 0) + 1
    print(f"sources: {len(list((out / 'sources').glob('*.txt')))} "
          f"({len(secs) - n_held} seed sections + {n_nb} neighbours); heldout: {n_held}; "
          f"truth: {len(truth)} {by_cls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
