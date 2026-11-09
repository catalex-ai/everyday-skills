"""Fetch labelled PII rows for the eval.

    python evals/fetch_pii.py --n 40 --out ~/.twin-corpora/pii

Writes DIR/pii.jsonl, one {text, spans: [{value, type}]} per line, using our
types: email, phone, address, password, bank_account, card, gov_id.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

UA = "twin-eval-corpus/0.1 (local research)"
URL = ("https://datasets-server.huggingface.co/rows?dataset=ai4privacy/pii-masking-200k"
       "&config=default&split=train&offset={offset}&length=100")

# dataset label -> our type. Anything else is ignored.
LABELS = {
    "EMAIL": "email", "TELEPHONENUM": "phone", "PHONENUMBER": "phone",
    "PASSWORD": "password", "IBAN": "bank_account", "ACCOUNTNUMBER": "bank_account",
    "CREDITCARDNUMBER": "card", "SOCIALNUM": "gov_id", "SSN": "gov_id",
    "STREET": "address", "STREETADDRESS": "address", "SECONDARYADDRESS": "address",
}


def get(url: str) -> dict:
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 + attempt * 2)
    return {}


def keep(row: dict) -> dict | None:
    if row.get("language") != "en":
        return None
    spans = []
    for m in row.get("privacy_mask") or []:
        t = LABELS.get(str(m.get("label", "")).upper())
        if t and m.get("value"):
            spans.append({"value": m["value"], "type": t})
    if not spans:
        return None
    return {"text": row["source_text"], "spans": spans}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", type=int, default=30)
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for page in range(a.pages):
        data = get(URL.format(offset=page * 100))
        for r in data.get("rows", []):
            k = keep(r["row"])
            if k:
                rows.append(k)
        if len(rows) >= a.n:
            break
        time.sleep(0.2)
    rows = rows[:a.n]
    with (out / "pii.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts: dict[str, int] = {}
    for r in rows:
        for s in r["spans"]:
            counts[s["type"]] = counts.get(s["type"], 0) + 1
    print(f"{len(rows)} rows -> {out / 'pii.jsonl'}; spans by type: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
