"""Turn a written reply into something worth hearing.

A reply full of fenced code, absolute paths and bullet lists is unbearable
read aloud. The screen carries the detail; the voice carries the headline.
"""

from __future__ import annotations

import re

from app.runtime import config

_FENCED = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUMBERED = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|_)(.*?)\1")
_PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\w.\-]+[\\/]){1,}([\w.\-]+)")
_WHITESPACE = re.compile(r"\s+")
_URL = re.compile(r"https?://\S+")


def _describe_code_blocks(text: str) -> str:
    """Replace fenced code with a sentence about it."""

    def repl(match: re.Match) -> str:
        body = match.group(0).strip("`")
        first = body.split("\n", 1)[0].strip()
        lang = first if first.isalpha() and len(first) < 15 else ""
        return f" I've written the {lang} code out for you. " if lang else " I've written the code out for you. "

    return _FENCED.sub(repl, text)


def to_speakable(text: str, *, max_words: int | None = None) -> str:
    """Compress a written reply into a short spoken form."""
    if not text:
        return ""

    limit = max_words or config.SPEAKABLE_MAX_WORDS

    out = _describe_code_blocks(text)
    out = _URL.sub(" the link on screen ", out)
    out = _MD_LINK.sub(r"\1", out)
    out = _INLINE_CODE.sub(r"\1", out)
    out = _HEADING.sub("", out)
    out = _EMPHASIS.sub(r"\2", out)
    out = _BULLET.sub("", out)
    out = _NUMBERED.sub("", out)
    # Long paths become basenames: "decks/2026/IPsec.pptx" -> "IPsec.pptx"
    out = _PATH.sub(r"\1", out)
    out = out.replace("\n", ". ")
    out = _WHITESPACE.sub(" ", out).strip()
    out = re.sub(r"(\.\s*){2,}", ". ", out)
    out = re.sub(r"\s+([.,!?])", r"\1", out)

    words = out.split(" ")
    if len(words) > limit:
        clipped = " ".join(words[:limit])
        # Prefer ending on a sentence boundary.
        last_stop = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
        out = clipped[: last_stop + 1] if last_stop > 30 else clipped.rstrip(",;:") + "."

    return out.strip()


__all__ = ["to_speakable"]
