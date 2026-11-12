"""Deterministic chatbot tells in a reply. Used by the eval report only.

Kept separate from the twin's own reply check on purpose: the judge's view
should not be the same code the twin is told to satisfy.
"""
from __future__ import annotations

import re

TELLS = {
    "dont_know": r"\b(i don'?t have (anything|any|much|info|information|details)|nothing (on|about) that to share|"
                 r"not something i can share|i('m| am) not able to (share|say|discuss)|i don'?t know)\b",
    "assistant_phrasing": r"\b(great question|i'?d be happy to|i hope this helps|feel free to|let me know if|"
                          r"as an ai|i('m| am) an ai|language model|how can i (help|assist)|i understand your|"
                          r"thank you for (asking|reaching out|your (question|feedback)))\b",
    "meta_leak": r"\b(persona|digital twin|my (notes|records|data|files)|the (brain|database|tool|search)|"
                 r"according to|on file|knowledge base|stored)\b",
    "markdown": r"(^|\n)\s*([-*•]\s|\d+\.\s|#{1,6}\s)|\*\*[^*]+\*\*",
    "em_dash": r"—",
}


def tells(reply: str) -> dict[str, bool]:
    low = reply.lower()
    return {k: bool(re.search(p, reply if k in ("markdown", "em_dash") else low)) for k, p in TELLS.items()}


def words(reply: str) -> int:
    return len(reply.split())
