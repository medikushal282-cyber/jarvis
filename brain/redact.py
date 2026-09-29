"""Secret redaction.

Redaction runs **before** an event is constructed, never at serialisation time. That ordering
is the whole point of this module: by the time a value has been placed into an event, a log
line, or a prompt, it has already been copied into structures that a crash dump, a debugger,
or an over-eager `repr()` in an error path can capture. Scrubbing on the way in is the only
version that cannot be bypassed by a code path someone forgot to update.

Two mechanisms, because they catch different leaks:

* :func:`redact_text` removes things that *look* like credentials, using patterns. This catches
  a key that a tool echoed back inside an otherwise innocuous log line.
* :func:`redact_paths` removes fields a tool *declared* sensitive in its `redact:` list. This
  catches values that carry no recognisable shape -- a customer's name, an internal hostname.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

REDACTED = "[REDACTED]"

#: Patterns matched against free text. Ordered most-specific first so that a prefixed key is
#: consumed whole rather than partially matched by a generic blob rule.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Authorization headers, in the several shapes a tool might echo one back.
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}"),
    # Known provider key prefixes. Kept as prefixes rather than full formats so a rotated or
    # lengthened key still matches.
    re.compile(r"\b(?:sk|gsk|hsk|rk|xoxb|xoxp)[-_][A-Za-z0-9]{12,}\b"),
    # AWS access key ids.
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # key=value and "key": "value" assignments for credential-ish names.
    re.compile(
        r"""(?ix)
        \b(api[_-]?key|secret|password|passwd|token|access[_-]?token|refresh[_-]?token|
           client[_-]?secret|private[_-]?key|authorization|credential)
        \b\s*[:=]\s*
        (?:"[^"]{4,}"|'[^']{4,}'|[^\s,;)}\]]{4,})
        """
    ),
    # Long hex or base64 runs. Last, because it is the most likely to produce a false positive;
    # the length floor keeps it off ordinary identifiers, commit shas, and trace ids.
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),
    re.compile(r"\b[A-Za-z0-9+/]{48,}={0,2}\b"),
)


def redact_text(text: str) -> str:
    """Replace anything credential-shaped in ``text`` with :data:`REDACTED`."""
    if not text:
        return text
    result = text
    for pattern in SECRET_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def _path_parts(path: str) -> list[str]:
    return [p for p in path.split(".") if p]


def _matches(parts: Sequence[str], key: str) -> bool:
    """Whether ``key`` is the leaf named by ``parts``.

    A single-segment path matches a key at any depth. That is intentional: a tool declaring
    ``redact: [env]`` means "any field called env, wherever it appears", because tool authors
    cannot know the nesting a provider will return and a too-strict match would silently leak.
    """
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] == "*" or parts[0].lower() == key.lower()
    return parts[-1].lower() == key.lower()


def redact_paths(value: Any, paths: Sequence[str]) -> Any:
    """Recursively copy ``value``, replacing the leaves named by ``paths``.

    Paths are dotted, e.g. ``config.env`` or ``connection_strings``. A single-segment path
    matches at any depth (see :func:`_matches`). Returns a new structure; the input is never
    mutated, so a caller holding the original for legitimate use is unaffected.
    """
    if not paths:
        return value

    segments = [list(_path_parts(p)) for p in paths]

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out: dict[Any, Any] = {}
            for key, item in node.items():
                key_str = str(key)
                if any(_matches(seg, key_str) for seg in segments):
                    out[key] = REDACTED
                else:
                    out[key] = walk(item)
            return out
        if isinstance(node, (list, tuple)):
            return [walk(item) for item in node]
        if isinstance(node, str):
            return redact_text(node)
        return node

    return walk(value)


def redact_args(args: dict[str, Any], paths: Sequence[str]) -> dict[str, Any]:
    """Redact a tool's arguments before they can reach an event.

    Always applies :func:`redact_text` to string leaves as well as the declared paths, so an
    undeclared secret embedded in a free-text argument still does not reach the trace.
    """
    if not args:
        return {}
    scrubbed = redact_paths(args, paths) if paths else args
    if not isinstance(scrubbed, dict):
        return {}
    return {k: (redact_text(v) if isinstance(v, str) else v) for k, v in scrubbed.items()}
