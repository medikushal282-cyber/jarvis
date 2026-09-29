"""Run lifecycle orchestration.

The eight steps in docs/runtime/SESSIONS.md section 5. Note how little this
knows about the agent: it resolves identity, records the turn, builds a
request, hands it to an ``AgentRunner``, and turns whatever events come back
into a persisted result.

Step 7 -- finalisation -- runs in a ``finally`` so a crashed, hung or
cancelled run still produces a record.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.runtime import config
from app.runtime.adapters.legacy_graph import get_agent_runner
from app.runtime.events import catalog
from app.runtime.events.bus import bus
from app.runtime.events.emitter import get_emitter
from app.runtime.ids import LOCAL_USER_ID, new_run_id, utc_now
from app.runtime.models import (
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PAUSED,
    RUN_PENDING,
    RUN_RUNNING,
    Run,
    Session,
    Turn,
)
from app.runtime.results.builder import ResultBuilder
from app.runtime.sessions import summarizer
from app.runtime.sessions.store import run_store, session_store, workspace_store

logger = logging.getLogger(__name__)

#: run_id -> the asyncio.Task executing it, so cancel() can reach it.
_active_tasks: Dict[str, asyncio.Task] = {}


class RunService:
    def __init__(self, sessions=session_store, runs=run_store, workspaces=workspace_store):
        self.sessions = sessions
        self.runs = runs
        self.workspaces = workspaces

    # --- session helpers ----------------------------------------------------

    def ensure_session(
        self,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        user_id: str = LOCAL_USER_ID,
        title: str = "New Session",
    ) -> Session:
        """Resolve a session, creating a default one when none is given."""
        if session_id:
            session = self.sessions.get(session_id, workspace_id)
            if session is not None:
                return session

        ws_id = workspace_id or config.DEFAULT_WORKSPACE_ID
        self.workspaces.ensure(ws_id, user_id)

        existing = self.sessions.list(workspace_id=ws_id, user_id=user_id, status="active")
        if existing and not session_id:
            found = self.sessions.get(existing[0]["id"], ws_id)
            if found is not None:
                return found

        return self.sessions.create(
            workspace_id=ws_id, user_id=user_id, title=title, session_id=session_id
        )

    # --- starting a run -----------------------------------------------------

    async def start_run(
        self,
        objective: str,
        *,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        user_id: str = LOCAL_USER_ID,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        input_mode: str = "text",
        execution_mode: str = "normal",
        attachments: Optional[List[Dict[str, Any]]] = None,
        audio_url: Optional[str] = None,
    ) -> Run:
        """Steps 1-6. Returns as soon as the run is dispatched."""
        from app.runtime.protocols import EXECUTION_MODES

        if execution_mode not in EXECUTION_MODES:
            raise ValueError(
                f"execution_mode must be one of {sorted(EXECUTION_MODES)}"
            )
        session = self.ensure_session(
            session_id, workspace_id, user_id, title=objective[:60] or "New Session"
        )

        run = Run(
            id=new_run_id(),
            session_id=session.id,
            user_id=session.user_id,
            workspace_id=session.workspace_id,
            objective=objective,
            model=model or config.DEFAULT_MODEL,
            provider=provider or config.DEFAULT_PROVIDER,
            input_mode=input_mode,
            execution_mode=execution_mode,
            status=RUN_PENDING,
        )

        # Step 2: the user's turn is recorded before anything can fail.
        async with self.sessions.lock(session.id):
            self.sessions.append_turn(
                session.id,
                Turn(
                    role="user",
                    content=objective,
                    input_mode=input_mode,
                    run_id=run.id,
                    audio_url=audio_url,
                ),
                session.workspace_id,
            )

        self.runs.save(run)

        # Step 4: arm the event stream before the agent can emit anything.
        bus.configure_run(
            run.id,
            log_path=self.runs.events_path(run.workspace_id, run.id),
            session_id=session.id,
            user_id=session.user_id,
        )

        task = asyncio.create_task(self._execute(run, session))
        _active_tasks[run.id] = task
        task.add_done_callback(lambda _t, rid=run.id: _active_tasks.pop(rid, None))

        return run

    # --- executing ----------------------------------------------------------

    async def _execute(self, run: Run, session: Session) -> None:
        emit = get_emitter(run.id)
        builder = ResultBuilder(
            run_id=run.id, session_id=session.id, objective=run.objective
        )
        stream = bus.stream(run.id)

        run.status = RUN_RUNNING
        run.started_at = utc_now()
        self.runs.save(run)

        outcome = None
        failure: Optional[BaseException] = None

        try:
            request = self._build_request(run, session)
            runner = get_agent_runner()
            outcome = await asyncio.wait_for(
                runner.run(request, emit), timeout=config.RUN_TIMEOUT_S
            )
        except asyncio.CancelledError:
            emit("run_cancelled", {"reason": "cancelled by user"}, node="runtime")
            run.status = RUN_CANCELLED
            raise
        except asyncio.TimeoutError:
            failure = asyncio.TimeoutError(
                f"run exceeded {config.RUN_TIMEOUT_S}s"
            )
            logger.warning("run %s timed out", run.id)
        except Exception as exc:  # noqa: BLE001 - any brain failure lands here
            failure = exc
            logger.exception("run %s failed", run.id)
        finally:
            # Step 7. Must happen however we got here.
            await self._finalize(run, session, stream, builder, outcome, failure, emit)

    def _build_request(self, run: Run, session: Session):
        from app.runtime.protocols import RunRequest

        ws_meta = self.workspaces.get(run.workspace_id) or {}
        return RunRequest(
            run_id=run.id,
            session_id=session.id,
            user_id=session.user_id,
            workspace_id=run.workspace_id,
            objective=run.objective,
            model=run.model,
            provider=run.provider,
            input_mode=run.input_mode,
            execution_mode=run.execution_mode,
            attachments=run.metadata.get("attachments", []),
            conversation=session.recent_turns(6),
            context_summary=session.context_summary,
            workspace_root=ws_meta.get("root_path"),
        )

    async def _finalize(
        self,
        run: Run,
        session: Session,
        stream,
        builder: ResultBuilder,
        outcome,
        failure: Optional[BaseException],
        emit,
    ) -> None:
        try:
            # The brain may have returned without a terminal event.
            if stream.terminal_event is None and run.status != RUN_CANCELLED:
                if failure is not None:
                    emit(
                        "run_failed",
                        {
                            "error_type": type(failure).__name__,
                            "message": str(failure)[:1000],
                            "node": "runtime",
                        },
                        node="runtime",
                    )
                else:
                    status = getattr(outcome, "status", "completed")
                    emit(
                        "run_completed",
                        {
                            "status": status,
                            "summary": getattr(outcome, "reply", "") or "",
                            "reply": getattr(outcome, "reply", "") or "",
                        },
                        node="runtime",
                    )

            stream.flush()
            events = stream.history(0) or self.runs.read_events(run.id, run.workspace_id)
            builder.add_all(events)
            result = builder.build()
            # Keep this run's version of each produced file, even if a later
            # run overwrites the original.
            from app.runtime.results.artifacts import capture

            result = capture(result, run.workspace_id, self.runs.artifacts_dir(run.workspace_id, run.id))

            run.event_count = result.get("event_count", 0)
            run.ended_at = utc_now()
            run.status = self._final_status(run, result, outcome, failure)
            if result.get("errors"):
                run.error = result["errors"][0]
            run.result = result

            self.runs.save(run)
            self.runs.save_result(run, result)

            reply = (
                getattr(outcome, "reply", "")
                or result.get("reply")
                or result.get("summary")
                or "Done."
            )

            async with self.sessions.lock(session.id):
                self.sessions.append_turn(
                    session.id,
                    Turn(
                        role="assistant",
                        content=reply,
                        run_id=run.id,
                        metadata={
                            "status": run.status,
                            "artifacts": result.get("artifacts", []),
                            "actions": result.get("actions", []),
                        },
                    ),
                    session.workspace_id,
                )

            summarizer.schedule(session.id, self.sessions, session.workspace_id)
            asyncio.create_task(bus.cleanup_later(run.id))

        except Exception:  # noqa: BLE001 - finalisation must not mask the run
            logger.exception("failed to finalise run %s", run.id)

    @staticmethod
    def _final_status(run: Run, result: dict, outcome, failure) -> str:
        if run.status == RUN_CANCELLED:
            return RUN_CANCELLED
        if failure is not None:
            return RUN_FAILED
        status = result.get("status")
        if status in ("completed", "failed", "cancelled", "rejected"):
            return status
        if outcome is not None and getattr(outcome, "status", None) == "paused":
            return RUN_PAUSED
        return RUN_COMPLETED

    # --- control ------------------------------------------------------------

    async def cancel(self, run_id: str) -> bool:
        task = _active_tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    # --- reads --------------------------------------------------------------

    def get_run(self, run_id: str, workspace_id: Optional[str] = None) -> Optional[Run]:
        return self.runs.get(run_id, workspace_id)

    def get_result(self, run_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Persisted result, or a live partial built from the current stream."""
        run = self.runs.get(run_id, workspace_id)
        if run is not None and run.result:
            return run.result

        stored = self.runs.get_result(run_id, workspace_id)
        if stored:
            return stored

        stream = bus.get(run_id)
        events = (
            stream.history(0) if stream is not None
            else self.runs.read_events(run_id, workspace_id)
        )
        if not events:
            return None

        seed = {"run_id": run_id}
        if run is not None:
            seed.update(session_id=run.session_id, objective=run.objective)
        return ResultBuilder(**seed).add_all(events).build()

    def read_events(self, run_id: str, workspace_id: Optional[str] = None, from_seq: int = 0) -> List[Dict[str, Any]]:
        stream = bus.get(run_id)
        if stream is not None:
            events = stream.history(from_seq)
            if events:
                return events
        return self.runs.read_events(run_id, workspace_id, from_seq)


run_service = RunService()

__all__ = ["RunService", "run_service"]
