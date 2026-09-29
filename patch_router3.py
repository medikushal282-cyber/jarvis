import re

with open("backend/app/llm/router.py", "r", encoding="utf-8") as f:
    text = f.read()

new_call_llm = '''def call_llm(
    system: str,
    user: str,
    model: str = "openai/gpt-oss-120b",
    provider: str = "groq",
    tools: Optional[List[Dict[str, Any]]] = None,
    emit: Optional[Any] = None,
    run_id: Optional[str] = None,
    turn_idx: Optional[int] = None,
) -> Tuple[str, Optional[str]]:
    """
    Unified LLM router using LiteLLM to route to Groq, Ollama, OpenAI, or Anthropic.
    Now acts as the LLM Worker Gateway.
    """
    from app.llm.workers import load_workers, mark_worker_error, mark_worker_used
    import time
    import logging
    logger = logging.getLogger(__name__)

    workers = load_workers()

    if not workers:
        # Fallback to standard environment keys if NO workers configured at all
        try:
            raw_response = call_litellm(system, user, model, provider, tools=tools, run_id=run_id, turn_idx=turn_idx)
            return extract_thoughts(raw_response)
        except Exception as e:
            raise Exception(f"LLM provider error: {e}")

    MAX_RETRIES = len(workers) * 2 
    attempts = 0
    failures = []

    while attempts < MAX_RETRIES:
        now = time.time()
        healthy_workers = [w for w in workers if w.get("enabled", True) and w.get("cooldown_until", 0) <= now]
        healthy_workers.sort(key=lambda x: x.get("priority", 0), reverse=True)

        if not healthy_workers:
            # If no healthy workers available right now, let's see if any are just in cooldown
            enabled_workers = [w for w in workers if w.get("enabled", True)]
            if not enabled_workers:
                raise Exception("JARVIS couldn't complete task. All configured workers are currently DISABLED.")
                
            # Find the soonest cooldown to expire
            soonest_worker = min(enabled_workers, key=lambda w: w.get("cooldown_until", now + 999))
            wait_time = soonest_worker.get("cooldown_until", now) - now
            
            if 0 < wait_time <= 60:
                if emit:
                    emit("worker_switching", {"message": f"All workers in cooldown. Waiting {int(wait_time)}s for rate limit reset..."}, node="agent")
                logger.info(f"All workers exhausted. Waiting {wait_time}s for retry-after to expire.")
                time.sleep(wait_time + 1)
                attempts += 1
                # Reload workers after sleep
                workers = load_workers()
                continue
            else:
                # Cooldown is too long or something else is wrong
                break

        w = healthy_workers[0]
        wid = w["worker_id"]
        w_model = w["model"]
        w_prov = w["provider"]
        api_key = w.get("api_key")

        if emit and attempts > 0:
            emit("worker_switching", {"message": f"Switching execution worker to {w_prov} ({w_model})..."}, node="agent")
            emit("worker_selected", {"worker_id": wid}, node="agent")

        try:
            env_key = f"{w_prov.upper()}_API_KEY"
            old_key = os.environ.get(env_key)
            if api_key:
                os.environ[env_key] = api_key

            raw_response = call_litellm(system, user, w_model, w_prov, tools=tools, run_id=run_id, turn_idx=turn_idx, worker_id=wid)

            if api_key:
                if old_key is not None:
                    os.environ[env_key] = old_key
                else:
                    del os.environ[env_key]

            mark_worker_used(wid)
            if emit and attempts > 0:
                emit("worker_connected", {"message": f"Worker connected ({wid}) — continuing execution."}, node="agent")
            return extract_thoughts(raw_response)

        except Exception as e:
            attempts += 1
            if api_key:
                if old_key is not None:
                    os.environ[env_key] = old_key
                elif env_key in os.environ:
                    del os.environ[env_key]

            err_str = str(e).lower()
            is_rate_limit = any(k in err_str for k in ["rate_limit", "429", "too many requests"])
            
            failures.append({
                "worker_id": wid,
                "provider": w_prov,
                "model": w_model,
                "error_type": type(e).__name__,
                "message": str(e),
                "rate_limit": is_rate_limit
            })

            if is_rate_limit:
                import re
                cooldown_s = 30
                try:
                    match = re.search(r'try again in (\\d+\\.?\\d*)s', err_str)
                    if match:
                        cooldown_s = int(float(match.group(1))) + 2
                except Exception:
                    pass
                mark_worker_error(wid, str(e), cooldown_s)
                
                workers = load_workers()
                if emit:
                    emit("worker_cooldown", {"worker_id": wid, "reason": "rate_limit", "cooldown_s": cooldown_s}, node="agent")
            else:
                # For non-rate-limit errors, we also mark it as failed with a generic cooldown so we try the next worker
                mark_worker_error(wid, str(e), 60)
                workers = load_workers()
                if emit:
                    emit("worker_failed", {"worker_id": wid, "reason": "execution_failed"}, node="agent")
            continue

    # If we exit the loop, we've failed completely
    if not failures:
        raise Exception("JARVIS couldn't complete task. No workers could be attempted (possibly all disabled or in long cooldown).")
        
    error_lines = ["JARVIS exhausted configured workers. Failures:"]
    for f in failures:
        error_lines.append(f"- Worker {f['worker_id']} ({f['provider']}/{f['model']}) failed. RateLimit: {f['rate_limit']}. Error: {f['error_type']}: {f['message']}")
        
    raise Exception("\\n".join(error_lines))'''

text = re.sub(r'def call_llm\(.*', new_call_llm, text, flags=re.DOTALL)

with open("backend/app/llm/router.py", "w", encoding="utf-8") as f:
    f.write(text)
