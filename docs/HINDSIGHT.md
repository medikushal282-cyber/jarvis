# Hindsight Memory Integration

Hindsight is JARVIS's lifelong episodic memory and knowledge extraction engine. It operates alongside the Agent Core but is fully decoupled via the `AgentMemoryBridge`.

## 1. Configuration
- Setting the environment variable `HINDSIGHT_URL` enables remote memory integration using the REST API of the Hindsight service.
- If not configured or unreachable, the system gracefully degrades to a mock local JSON database (`backend/data/hindsight_mock/hindsight_db.json`), ensuring JARVIS can always boot and execute.

## 2. Component Layout
- **Hindsight Client/Adapter**: `backend/app/memory/hindsight/client.py` and `adapter.py`
- **Memory API Surface**: `backend/app/memory/api.py` (the clean orchestrator boundary)
- **Agent Bridge**: `backend/app/agent/memory_bridge.py` (which injects memory capabilities into the autonomous loop without exposing storage specifics).

## 3. Recall Lifecycle
**Where:** Before the ReAct loop starts in `backend/app/agent/brain.py` (`JarvisBrain.run()`).
**How:**
1. The brain calls `self.memory.recall(user_id, objective, ...)`
2. The memory builder requests similar past episodes from Hindsight and retrieves active OKF preferences.
3. This is injected as a string `memory_context` containing `user_knowledge`, `project_knowledge`, and `relevant_experiences`.

## 4. Retain Lifecycle (Experience Extraction)
**Where:** After the ReAct loop completes or fails in `JarvisBrain.run()`.
**How:**
1. The execution result is retrieved via `run_service.get_result(request.run_id)` (fetching the complete trace of tool calls, errors, and created artifacts).
2. `self.memory.record()` formats this into an `execution_state` dictionary.
3. `MemoryExtractor.extract_experience` summarizes the state and redacts potential secrets (`api_key`, `Bearer`, `sk-`).
4. The client issues a `POST /experience` to Hindsight.

## 5. Reflection & Durable Knowledge (OKF)
**Where:** Triggered asynchronously via `memory_bridge.py` right after an experience is successfully retained.
**How:**
1. `MemoryReflector.reflect()` surveys the user's latest 10 experiences.
2. An LLM request determines if there are explicit statements ("I prefer compact reports") or strong inferred trends.
3. **Promotion Rules**: A fact is only promoted to the durable OKF database (`user_preferences`) if:
   - `confidence_score >= 80`
   - AND `evidence_count >= 2` (or it is an `explicit_preference` which requires `evidence_count >= 1`).
   - AND it contains no detected secrets.

## 6. Failure Degradation
Memory operations MUST NOT disrupt actual execution. If `Hindsight` is offline or the LLM reflector fails (e.g., due to rate limits), the exception is swallowed by `logger.debug` in `memory_bridge.py`.

## 7. Verifying Memory Persistence
To prove persistence across isolated interactions:
1. Turn 1: "I prefer compact technical reports. Create a report about this project." (Explicit preference observed and retained).
2. Turn 2: "Create another report."
3. Hindsight recall intercepts Turn 2, matching the user ID and automatically pushing the `compact technical reports` rule into the prompt without requiring user restatement.
