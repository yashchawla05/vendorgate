"""Detect instruction-like text inside a document (prompt-injection attempts).

Documents are data, never instructions. This deterministic check runs on the
text layer regardless of which extractor is used, so an injection attempt is
flagged for a human even if the LLM correctly ignores it.
"""
from __future__ import annotations

import re

_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any )?(previous|prior|above) (instructions|rules)",
    r"\b(system|developer) (note|prompt|message|instruction)s?\b",
    r"\bnote to (the )?(ai|llm|model|assistant|reviewer)\b",
    r"\byou are (now )?(an? )?(ai|assistant|language model)\b",
    r"mark (every|all) checks? as (passed|ok|approved)",
    r"set (the )?confidence to",
    r"\bpre-?approved\b",
    r"approve (this|the) vendor",
]
_REGEX = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)


def find_injection(text: str) -> list[str]:
    """Return the lines that contain instruction-like phrases (empty list if none)."""
    hits = []
    for line in text.splitlines():
        if _REGEX.search(line):
            hits.append(line.strip()[:240])
    return hits
