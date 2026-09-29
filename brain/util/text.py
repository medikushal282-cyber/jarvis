"""Text helpers: token estimation, content-word extraction, and overlap scoring.

These are deliberately dependency-free and deterministic. Two of them carry real weight:

* :func:`estimate_tokens` drives the token budget, so it must never be wildly wrong in either
  direction. A provider's reported usage is always preferred when available; this is the
  fallback for the assembler, which has to budget *before* it calls the model.
* :func:`content_words` and :func:`jaccard` are the weakest rung of memory attribution. They
  only ever produce a ``lexical_overlap`` claim, which the trace renders differently from an
  explicit citation -- so a false positive here degrades gracefully instead of overstating
  the agent's reasoning.
"""

from __future__ import annotations

import re

#: Conservative characters-per-token ratio. English prose runs nearer 4; code and JSON run
#: lower. We use a slightly conservative value in the *cost* direction (fewer characters per
#: token means a higher token estimate) so budgeting errs toward leaving headroom.
CHARS_PER_TOKEN = 3.6

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_\-.]*", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

#: Words carrying no discriminative signal for overlap scoring. Kept short on purpose: an
#: aggressive stop-list would suppress genuine matches in log text, where the informative
#: tokens are often short identifiers.
_STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those is are was were be been being
    of in on at to for from with without by as it its into over under about after before
    do does did done have has had not no nor so such very can could may might must shall
    should will would you your we our they their he she them i me my
    """.split()
)


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text``.

    A character-ratio heuristic rather than a real tokenizer: the brain must budget before
    calling the provider, and shipping a tokenizer would add a dependency and a model-specific
    vocabulary for an estimate that only needs to be close. Always prefer a provider's reported
    usage when a real response is in hand.
    """
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def normalize_ws(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip the ends."""
    return _WS_RE.sub(" ", text).strip()


def content_words(text: str) -> frozenset[str]:
    """Extract the discriminative words from ``text``, lowercased.

    Drops stopwords and single characters. Keeps identifier-shaped tokens (``checkout-api``,
    ``db_pool_max``) intact, because in operational text those are exactly the tokens whose
    overlap is meaningful.
    """
    return frozenset(
        w
        for w in (m.group(0).lower() for m in _WORD_RE.finditer(text))
        if w not in _STOPWORDS and len(w) > 1
    )


def jaccard(left: frozenset[str] | set[str], right: frozenset[str] | set[str]) -> float:
    """Jaccard similarity of two token sets, in ``[0, 1]``.

    Returns 0.0 when both are empty rather than 1.0: two texts with no content words carry no
    evidence that they are related, and treating "both empty" as a perfect match would make
    empty tool arguments look like a strong memory citation.
    """
    if not left and not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def truncate_middle(text: str, *, max_chars: int, marker: str = "\n[... truncated ...]\n") -> str:
    """Truncate ``text`` to ``max_chars``, keeping both ends.

    Keeps the head *and* the tail because in log and error output both matter: the head carries
    the request context and the tail carries the exception that actually killed it. Cutting the
    middle is the only choice that preserves the diagnostic value of both.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if len(marker) >= max_chars:
        return text[:max_chars]
    keep = max_chars - len(marker)
    head = keep // 2
    tail = keep - head
    return f"{text[:head]}{marker}{text[-tail:]}"
