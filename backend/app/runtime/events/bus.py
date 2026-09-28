"""Per-run event bus: fan-out, ordering, replay, persistence, cleanup.

Replaces the 21-line queue in ``app/events.py``. The properties that matter:

* **Fan-out, not hand-off.** Each subscriber gets its own queue, so two
  browser tabs both see the whole timeline instead of splitting it.
* **Monotonic ``seq`` assigned at publish.** The only ordering guarantee;
  timestamps are not precise enough.
* **Ring buffer + durable ndjson.** A refresh mid-run replays cleanly, and a
  finished run still has a timeline after a restart.
* **Publishing never blocks and never raises.** A slow subscriber drops its
  oldest events; a broken pipe is logged, not propagated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import Any, AsyncIterator, Deque, Dict, List, Optional

from app.runtime import config
from app.runtime.events import catalog
from app.runtime.ids import utc_now

logger = logging.getLogger(__name__)

_SECRET_KEY_NAMES = re.compile(
    r"(api[-_]?key|authorization|auth[-_]?token|access[-_]?token|password|secret|cookie|bearer)",
    re.IGNORECASE,
)
_SECRET_ENV_VARS = (
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ELEVENLABS_API_KEY",
    "GITHUB_TOKEN",
)
_REDACTED = "[REDACTED]"


def _secret_values() -> List[str]:
    out = []
    for name in _SECRET_ENV_VARS:
        val = os.environ.get(name)
        if val and len(val) >= 8:
            out.append(val)
    return out


def _sanitize(value: Any, depth: int = 0) -> Any:
    """Redact secrets and truncate oversized strings. Never raises."""
    if depth > 8:
        return "[TRUNCATED: too deep]"

    if isinstance(value, str):
        for secret in _secret_values():
            if secret in value:
                value = value.replace(secret, _REDACTED)
        if len(value) > config.EVENT_MAX_STRING:
            return value[: config.EVENT_MAX_STRING] + f"... [+{len(value) - config.EVENT_MAX_STRING} chars]"
        return value

    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k)
            if _SECRET_KEY_NAMES.search(key):
                out[key] = _REDACTED
            else:
                out[key] = _sanitize(v, depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        return [_sanitize(v, depth + 1) for v in list(value)[:500]]

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return _sanitize(str(value), depth + 1)


class _Subscriber:
    __slots__ = ("queue", "dropped")

    def __init__(self, maxsize: int):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0


class RunStream:
    """The event stream for a single run."""

    def __init__(self, run_id: str, *, log_path: Optional[Path] = None, **identity: str):
        self.run_id = run_id
        self.identity = {k: v for k, v in identity.items() if v}
        self.seq = 0
        self.closed = False
        self.terminal_event: Optional[str] = None

        self._ring: Deque[dict] = deque(maxlen=config.EVENT_RING_SIZE)
        self._subs: List[_Subscriber] = []
        self._lock = threading.Lock()
        self._log_path = log_path
        self._pending_writes: List[dict] = []
        self._writer_task: Optional[asyncio.Task] = None

        if self._log_path is not None:
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning("event log unavailable for %s: %s", run_id, exc)
                self._log_path = None

    # --- publish ------------------------------------------------------------

    def publish(self, event: str, data: Optional[dict] = None, *, node: str = "") -> Optional[dict]:
        """Assign a seq, fan out, buffer, persist. Never raises."""
        try:
            payload = _sanitize(data if data is not None else {})
            if not isinstance(payload, dict):
                payload = {"value": payload}

            encoded_len = len(json.dumps(payload, default=str))
            if encoded_len > config.EVENT_MAX_PAYLOAD:
                payload = {
                    "_truncated": True,
                    "_original_bytes": encoded_len,
                    "preview": json.dumps(payload, default=str)[: config.EVENT_MAX_STRING],
                }

            name = catalog.canonical(event)

            if config.VALIDATE_EVENTS:
                if not catalog.is_known(name):
                    logger.warning("unknown event %r on run %s", name, self.run_id)
                else:
                    missing = catalog.missing_keys(name, payload)
                    if missing:
                        logger.warning(
                            "event %r on run %s missing keys: %s",
                            name, self.run_id, ", ".join(sorted(missing)),
                        )

            with self._lock:
                if self.closed:
                    return None
                self.seq += 1
                envelope = {
                    "seq": self.seq,
                    "event": name,
                    "run_id": self.run_id,
                    **self.identity,
                    "node": node or "",
                    "ts": utc_now(),
                    "data": payload,
                }
                self._ring.append(envelope)
                subs = list(self._subs)
                if catalog.is_terminal(name):
                    self.terminal_event = name

            for sub in subs:
                self._offer(sub, envelope)

            self._persist(envelope)
            return envelope

        except Exception:  # noqa: BLE001 - telemetry must never break a run
            logger.exception("failed to publish event %r on run %s", event, self.run_id)
            return None

    @staticmethod
    def _offer(sub: _Subscriber, envelope: dict) -> None:
        """Non-blocking put; drop oldest when the subscriber falls behind."""
        try:
            sub.queue.put_nowait(envelope)
        except asyncio.QueueFull:
            try:
                sub.queue.get_nowait()
                sub.dropped += 1
                marked = dict(envelope)
                marked["data"] = {**envelope.get("data", {}), "_dropped": sub.dropped}
                sub.queue.put_nowait(marked)
            except Exception:  # noqa: BLE001
                sub.dropped += 1
        except Exception:  # noqa: BLE001
            pass

    # --- persistence --------------------------------------------------------

    def _persist(self, envelope: dict) -> None:
        if self._log_path is None or not config.EVENT_PERSIST:
            return
        with self._lock:
            self._pending_writes.append(envelope)
            needs_task = self._writer_task is None or self._writer_task.done()
        if needs_task:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                self._flush_sync()
                return
            self._writer_task = loop.create_task(self._flush_soon())

    async def _flush_soon(self) -> None:
        await asyncio.sleep(0.05)
        await asyncio.to_thread(self._flush_sync)

    def _flush_sync(self) -> None:
        with self._lock:
            batch, self._pending_writes = self._pending_writes, []
        if not batch or self._log_path is None:
            return
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                for envelope in batch:
                    fh.write(json.dumps(envelope, default=str) + "\n")
        except OSError as exc:
            logger.warning("event log write failed for %s: %s", self.run_id, exc)

    def flush(self) -> None:
        self._flush_sync()

    # --- subscribe ----------------------------------------------------------

    def history(self, from_seq: int = 0) -> List[dict]:
        """Buffered events with ``seq > from_seq``, falling back to the log."""
        with self._lock:
            ring = list(self._ring)

        if ring and ring[0]["seq"] <= from_seq + 1:
            return [e for e in ring if e["seq"] > from_seq]
        if not ring and from_seq == 0 and self._log_path is None:
            return []

        replayed = self.read_log(from_seq)
        if replayed:
            seen = {e["seq"] for e in replayed}
            replayed.extend(e for e in ring if e["seq"] > from_seq and e["seq"] not in seen)
            replayed.sort(key=lambda e: e["seq"])
            return replayed
        return [e for e in ring if e["seq"] > from_seq]

    def read_log(self, from_seq: int = 0) -> List[dict]:
        if self._log_path is None or not self._log_path.exists():
            return []
        out: List[dict] = []
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        envelope = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if envelope.get("seq", 0) > from_seq:
                        out.append(envelope)
        except OSError as exc:
            logger.warning("event log read failed for %s: %s", self.run_id, exc)
        return out

    async def subscribe(self, from_seq: int = 0) -> AsyncIterator[dict]:
        """Replay from ``from_seq``, then stream live. Heartbeats on idle."""
        sub = _Subscriber(config.EVENT_QUEUE_SIZE)
        with self._lock:
            self._subs.append(sub)
            already_terminal = self.terminal_event is not None
            current_seq = self.seq

        try:
            yield {
                "seq": 0,
                "event": catalog.STREAM_READY,
                "run_id": self.run_id,
                **self.identity,
                "node": "runtime",
                "ts": utc_now(),
                "data": {"run_id": self.run_id, "resumed_from_seq": from_seq,
                         "current_seq": current_seq},
            }

            last_seq = from_seq
            for envelope in self.history(from_seq):
                last_seq = max(last_seq, envelope["seq"])
                yield envelope

            if already_terminal and last_seq >= current_seq:
                return

            while True:
                try:
                    envelope = await asyncio.wait_for(
                        sub.queue.get(), timeout=config.SSE_HEARTBEAT_S
                    )
                except asyncio.TimeoutError:
                    with self._lock:
                        done = self.closed or (
                            self.terminal_event is not None and sub.queue.empty()
                        )
                    yield {
                        "seq": last_seq,
                        "event": catalog.HEARTBEAT,
                        "run_id": self.run_id,
                        **self.identity,
                        "node": "runtime",
                        "ts": utc_now(),
                        "data": {"ts": utc_now()},
                    }
                    if done:
                        return
                    continue

                if envelope["seq"] <= last_seq:
                    continue
                last_seq = envelope["seq"]
                yield envelope

                if catalog.is_terminal(envelope["event"]):
                    return
        finally:
            with self._lock:
                if sub in self._subs:
                    self._subs.remove(sub)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def close(self) -> None:
        with self._lock:
            self.closed = True
        self._flush_sync()


class EventBus:
    """Registry of per-run streams, with lazy creation and delayed cleanup."""

    def __init__(self) -> None:
        self._streams: Dict[str, RunStream] = {}
        self._lock = threading.Lock()
        self._log_paths: Dict[str, Path] = {}
        self._identities: Dict[str, Dict[str, str]] = {}

    def configure_run(self, run_id: str, *, log_path: Optional[Path] = None, **identity: str) -> None:
        """Attach a durable log path and identity keys before the run starts."""
        with self._lock:
            if log_path is not None:
                self._log_paths[run_id] = log_path
            if identity:
                self._identities[run_id] = {k: v for k, v in identity.items() if v}
            stream = self._streams.get(run_id)
        if stream is not None:
            if log_path is not None and stream._log_path is None:
                try:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    stream._log_path = log_path
                except OSError:
                    pass
            if identity:
                stream.identity.update({k: v for k, v in identity.items() if v})

    def stream(self, run_id: str) -> RunStream:
        with self._lock:
            existing = self._streams.get(run_id)
            if existing is not None:
                return existing
            log_path = self._log_paths.get(run_id)
            identity = self._identities.get(run_id, {})
            stream = RunStream(run_id, log_path=log_path, **identity)
            self._streams[run_id] = stream
            return stream

    def get(self, run_id: str) -> Optional[RunStream]:
        with self._lock:
            return self._streams.get(run_id)

    def publish(self, run_id: str, event: str, data: Optional[dict] = None, *, node: str = "") -> Optional[dict]:
        return self.stream(run_id).publish(event, data, node=node)

    def read_log(self, run_id: str, log_path: Optional[Path] = None, from_seq: int = 0) -> List[dict]:
        """Read a run's timeline, including for runs this process never served."""
        stream = self.get(run_id)
        if stream is not None:
            events = stream.history(from_seq)
            if events:
                return events
        path = log_path or self._log_paths.get(run_id)
        if path is None:
            return []
        probe = RunStream(run_id, log_path=path)
        return probe.read_log(from_seq)

    async def cleanup_later(self, run_id: str, delay: Optional[int] = None) -> None:
        """Drop buffers once the run is terminal and nobody is watching."""
        wait = config.EVENT_CLEANUP_DELAY_S if delay is None else delay
        await asyncio.sleep(wait)
        with self._lock:
            stream = self._streams.get(run_id)
        if stream is None:
            return
        if stream.subscriber_count > 0:
            asyncio.create_task(self.cleanup_later(run_id, wait))
            return
        stream.close()
        with self._lock:
            self._streams.pop(run_id, None)
            self._log_paths.pop(run_id, None)
            self._identities.pop(run_id, None)

    def discard(self, run_id: str) -> None:
        with self._lock:
            stream = self._streams.pop(run_id, None)
            self._log_paths.pop(run_id, None)
            self._identities.pop(run_id, None)
        if stream is not None:
            stream.close()

    @property
    def active_runs(self) -> List[str]:
        with self._lock:
            return list(self._streams)


bus = EventBus()
