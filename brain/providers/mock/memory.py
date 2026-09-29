"""An in-process memory provider with real ranking, real deduplication, and stable ids.

This is the mock that most needs to be *correct* rather than merely convenient, because the
hackathon's heaviest single criterion is whether memory is load-bearing. Three properties make
that demonstrable rather than asserted, and the conformance suite checks all three:

* **Stable ids.** A memory returned twice carries the same id, because ``memory.influenced``
  events point at ids. A provider that minted a fresh id per query would silently empty the
  trace's memory lane while still reporting hits -- the worst possible failure, because it looks
  like memory is off.
* **Idempotent retain.** Retaining the same lesson twice is one memory, deduplicated by
  :meth:`MemoryItem.content_fingerprint`. Without this, replaying a completed run inflates the
  benchmark and the learning curve becomes an artefact of the harness.
* **Deterministic ranking.** A documented score with no hash-order dependence, so the same query
  returns the same order every time and a benchmark comparing two runs is comparing the runs.

Ranking weights ``failure`` and ``correction`` above ``outcome`` deliberately. A remembered
failure is what stops an agent repeating a dead end, so it is worth surfacing more eagerly than
a remembered success -- and the zero-cost way to encode that is in the score.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from brain.contracts import (
    MemoryItem,
    MemoryKind,
    RecallQuery,
    RetainResult,
    SkippedRetention,
)
from brain.util.text import content_words, jaccard

#: How eagerly each kind is surfaced, all else equal. Failures and corrections outrank outcomes
#: because avoiding a repeat mistake is worth more than reusing a success.
_KIND_WEIGHT: dict[MemoryKind, float] = {
    MemoryKind.FAILURE: 1.00,
    MemoryKind.CORRECTION: 0.95,
    MemoryKind.PREFERENCE: 0.85,
    MemoryKind.ENTITY_FACT: 0.75,
    MemoryKind.OUTCOME: 0.70,
}

_ENTITY_WEIGHT = 0.45
_LEXICAL_WEIGHT = 0.35
_ALWAYS_KIND_BONUS = 0.25


class MockMemory:
    """A deterministic, file-backed memory store."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        store_path: Path | None = None,
        seed: Path | None = None,
        recall_limit: int = 8,
        always_recall_kinds: Sequence[MemoryKind] = (),
    ) -> None:
        self.enabled = enabled
        self.store_path = Path(store_path) if store_path else None
        self.seed_path = Path(seed) if seed else None
        self.recall_limit = recall_limit
        self.always_recall_kinds = tuple(always_recall_kinds)
        self._items: dict[str, MemoryItem] = {}
        self._by_fingerprint: dict[str, str] = {}
        self._order: list[str] = []
        self._load()

    # ------------------------------------------------------------------ protocol

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """Rank stored memories against ``query`` and return the best ``limit``.

        Returns an empty list when memory is disabled, without pretending a search happened.
        The loop relies on that distinction: an empty result with memory on is evidence about the
        world, whereas memory off is evidence about the run's configuration.
        """
        if not self.enabled:
            return []

        query_words = content_words(query.text)
        query_entities = {e.lower() for e in query.entities}
        limit = query.limit if query.limit > 0 else self.recall_limit
        scored: list[tuple[float, MemoryItem]] = []

        for item in self._items.values():
            if query.kinds and item.kind not in query.kinds:
                continue
            score = self._score(item, query_words, query_entities)
            if score <= 0.0:
                continue
            scored.append((score, item))

        # Sort by score descending, then by id for a total order -- without the id tiebreak the
        # result would depend on insertion order and quietly drift between runs.
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [dataclasses.replace(item, score=round(score, 4)) for score, item in scored[:limit]]

    def retain(self, items: Sequence[MemoryItem]) -> RetainResult:
        """Store ``items``, skipping ones whose content is already known."""
        if not self.enabled:
            return RetainResult(
                skipped=tuple(
                    SkippedRetention(candidate=i.text[:120], reason="memory_disabled")
                    for i in items
                )
            )

        written: list[str] = []
        deduped: list[str] = []
        for item in items:
            fingerprint = item.content_fingerprint()
            existing = self._by_fingerprint.get(fingerprint)
            if existing is not None:
                deduped.append(existing)
                continue
            self._items[item.id] = item
            self._by_fingerprint[fingerprint] = item.id
            self._order.append(item.id)
            written.append(item.id)

        self._persist()
        return RetainResult(written=tuple(written), deduplicated=tuple(deduped))

    # ------------------------------------------------------------------ tool-provider interface
    # These methods satisfy the ToolProvider protocol for the `memory` provider. The loop
    # routes mid-plan tool calls (recall_memory, save_memory) through the provider registry,
    # which calls invoke() -- the same pattern as ObservabilityMock, IncidentMock, etc.

    def invoke(self, method: str, args: dict[str, Any]) -> "ToolResult":
        from brain.contracts import ToolResult
        handler = getattr(self, method, None)
        if handler is None or method.startswith("_"):
            from brain.errors import ErrorClass
            return ToolResult.failure(
                ErrorClass.UNKNOWN_TOOL, f"memory provider has no method {method!r}"
            )
        return handler(args)

    def recall_memory(self, args: Mapping[str, Any]) -> "ToolResult":
        """Tool entry point for mid-plan memory lookup."""
        from brain.contracts import ToolResult
        query_text = str(args.get("query", ""))
        entities = tuple(str(e) for e in args.get("entities", []) or [])
        kinds_raw = args.get("kinds", []) or []
        limit = int(args.get("limit", 5))
        query = RecallQuery(
            text=query_text, entities=entities,
            kinds=tuple(MemoryKind(k) for k in kinds_raw if k in MemoryKind._value2member_map_),
            limit=limit,
        )
        hits = self.recall(query)
        return ToolResult.success({"memories": [m.as_event_data() for m in hits]})

    def save_memory(self, args: Mapping[str, Any]) -> "ToolResult":
        """Tool entry point for mid-run memory writes."""
        from brain.contracts import ToolResult
        from brain.errors import ErrorClass
        text = str(args.get("text", "")).strip()
        if not text:
            return ToolResult.failure(ErrorClass.VALIDATION, "save_memory requires non-empty 'text'")
        kind_raw = str(args.get("kind", "outcome"))
        try:
            kind = MemoryKind(kind_raw)
        except ValueError:
            kind = MemoryKind.OUTCOME
        item = MemoryItem(
            id=f"mem-save-{abs(hash(text)) % 100000:05d}",
            kind=kind,
            text=text,
            entities=tuple(str(e) for e in args.get("entities", []) or []),
            confidence=float(args.get("confidence", 0.7)),
        )
        result = self.retain([item])
        return ToolResult.success({
            "memory_id": item.id,
            "stored": bool(result.written),
            "deduplicated_with": result.deduplicated[0] if result.deduplicated else None,
        })

    # ------------------------------------------------------------------ inspection

    def all(self) -> tuple[MemoryItem, ...]:
        return tuple(self._items[i] for i in self._order)

    def __len__(self) -> int:
        return len(self._items)

    # ------------------------------------------------------------------ internals

    def _score(
        self, item: MemoryItem, query_words: frozenset[str], query_entities: set[str]
    ) -> float:
        item_entities = {e.lower() for e in item.entities}
        if query_entities and item_entities:
            entity_overlap = len(query_entities & item_entities) / len(query_entities)
        else:
            # No entities on either side is not evidence of a match; it is absence of signal.
            entity_overlap = 0.0

        lexical = jaccard(query_words, content_words(item.text))
        if entity_overlap == 0.0 and lexical == 0.0:
            return 0.0

        score = (
            _ENTITY_WEIGHT * entity_overlap
            + _LEXICAL_WEIGHT * lexical
            + _KIND_WEIGHT.get(item.kind, 0.5)
        )
        # Confidence scales the whole claim: a low-confidence memory is still retrievable, but it
        # should not outrank a confident one on the same evidence.
        score *= 0.5 + 0.5 * max(0.0, min(1.0, item.confidence))
        if item.kind in self.always_recall_kinds:
            score += _ALWAYS_KIND_BONUS
        return score

    def _load(self) -> None:
        source = self.store_path if (self.store_path and self.store_path.exists()) else self.seed_path
        if source is None or not source.exists():
            return
        try:
            text = source.read_text(encoding="utf-8")
            # Seed files are YAML; the runtime store is JSON. Detect by extension.
            if source.suffix in {".yaml", ".yml"}:
                raw = yaml.safe_load(text)
            else:
                raw = json.loads(text)
        except (json.JSONDecodeError, yaml.YAMLError, OSError):
            # A corrupt store must not prevent a run. Starting empty is the safe degradation, and
            # the loop's own error path surfaces the resulting thin recall as a real signal.
            return
        for entry in (raw or {}).get("memories", []) or []:
            item = _item_from(entry)
            self._items[item.id] = item
            self._by_fingerprint[item.content_fingerprint()] = item.id
            self._order.append(item.id)

    def _persist(self) -> None:
        if self.store_path is None:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "memories": [
                {
                    "id": i.id,
                    "kind": str(i.kind),
                    "text": i.text,
                    "entities": list(i.entities),
                    "confidence": i.confidence,
                    "observed_at": i.observed_at.isoformat() if i.observed_at else None,
                    "source_run_id": i.source_run_id,
                }
                for i in self.all()
            ],
        }
        self.store_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )


def _item_from(entry: Mapping[str, Any]) -> MemoryItem:
    observed = entry.get("observed_at")
    return MemoryItem(
        id=str(entry["id"]),
        kind=MemoryKind(str(entry["kind"])),
        text=str(entry["text"]),
        entities=tuple(entry.get("entities", []) or ()),
        confidence=float(entry.get("confidence", 0.7)),
        observed_at=_parse_dt(observed) if observed else None,
        source_run_id=entry.get("source_run_id"),
    )


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build(settings: dict[str, Any], *, root: Path, impl: str | None = None) -> Any:
    """Factory. ``impl: hindsight`` is served by a different module; this one is the mock."""
    store = settings.get("store_path")
    seed = settings.get("seed")
    return MockMemory(
        enabled=bool(settings.get("enabled", True)),
        store_path=(root / str(store)) if store else None,
        seed=(root / str(seed)) if seed else None,
        recall_limit=int(settings.get("recall_limit", 8)),
        always_recall_kinds=[MemoryKind(k) for k in settings.get("always_recall_kinds", []) or []],
    )
