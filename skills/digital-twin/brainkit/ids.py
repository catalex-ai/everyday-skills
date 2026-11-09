"""Stable ids and slugs."""
import hashlib
import re
import unicodedata

_TRAIL = ".,;:!?…"


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t.rstrip(_TRAIL + " ")


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def fact_id(text: str) -> str:
    return "f-" + _sha(norm(text))


def source_id(text: str) -> str:
    return "s-" + _sha(text)


def slug(name: str) -> str:
    t = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    return t[:60].strip("-")
