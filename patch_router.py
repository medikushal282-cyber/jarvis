import os
import re

with open("backend/app/llm/router.py", "r", encoding="utf-8") as f:
    text = f.read()

litellm_new = """def call_litellm(
    system: str,
    user: str,
    model: str,
    provider: str = "groq",
    tools: Optional[List[Dict[str, Any]]] = None,
    run_id: Optional[str] = None,
    turn_idx: Optional[int] = None,
    worker_id: Optional[str] = None,
) -> str:
    import litellm
    import logging
    import time
    logger = logging.getLogger(__name__)

    prov = (provider or "groq").lower()
    model_str = model or "openai/gpt-oss-120b"

    if prov == "groq":
        if not model_str.startswith("groq/"):
            model_str = f"groq/{model_str}"
    elif prov == "ollama":
        if not model_str.startswith("ollama/"):
            model_str = f"ollama/{model_str}"
    elif prov == "openai":
        if not model_str.startswith("openai/"):
            model_str = f"openai/{model_str}"
    elif prov == "anthropic":
        if not model_str.startswith("anthropic/"):
            model_str = f"anthropic/{model_str}"

    kwargs: Dict[str, Any] = {
        "model": model_str,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    start_time = time.time()
    success = False
    rate_limit = False
    p_tokens = 0
    c_tokens = 0
    t_tokens = 0

    try:
        response = litellm.completion(**kwargs)
        success = True

        usage = getattr(response, "usage", None)
        if usage:
            p_tokens = getattr(usage, "prompt_tokens", 0)
            c_tokens = getattr(usage, "completion_tokens", 0)
            t_tokens = getattr(usage, "total_tokens", 0)

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)
        content = message.content or ""

        if tool_calls:
            rendered_calls = []
            for tc in tool_calls:
                fn = getattr(tc, "function", None)
                if fn:
                    fn_name = getattr(fn, "name", "")
                    fn_args = getattr(fn, "arguments", "{}")
                    try:
                        parsed_args = json.loads(fn_args) if isinstance(fn_args, str) else fn_args
                    except Exception:
                        parsed_args = {"raw": str(fn_args)}
                    rendered_calls.append(f"<tool_call>\\n{json.dumps({'name': fn_name, 'arguments': parsed_args})}\\n</tool_call>")

            tool_str = "\\n".join(rendered_calls)
            return f"{content}\\n{tool_str}".strip() if content else tool_str

        return content
    except Exception as exc:
        err_msg = str(exc).lower()
        if any(k in err_msg for k in ["rate_limit", "429", "timeout", "connection", "overloaded", "groqexception"]):
            rate_limit = True
        if "failed_generation" in err_msg:
            try:
                import re
                match = re.search(r'"failed_generation":\\s*"({.*?})"', str(exc))
                if match:
                    raw_json_str = match.group(1).encode().decode('unicode-escape')
                    success = True
                    return f"<tool_call>\\n{raw_json_str}\\n</tool_call>"
            except Exception:
                pass
        raise exc
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "LLM_REQUEST: worker_id=%s, provider=%s, model=%s, run_id=%s, turn=%s, "
            "prompt_tokens=%s, completion_tokens=%s, total_tokens=%s, duration_ms=%s, "
            "success=%s, rate_limit=%s",
            worker_id, prov, model_str, run_id, turn_idx,
            p_tokens, c_tokens, t_tokens, duration_ms,
            success, rate_limit
        )"""

call_llm_new = """def call_llm(
    system: str,
    user: str,
    model: str = "openai/gpt-oss-120b",
    provider: str = "groq",
    tools: Optional[List[Dict[str, Any]]] = None,
    emit: Optional[Any] = None,
    run_id: Optional[str] = None,
    turn_idx: Optional[int] = None,
) -> Tuple[str, Optional[str]]:
    \"\"\"
    Unified LLM router using LiteLLM to route to Groq, Ollama, OpenAI, or Anthropic.
    Now acts as the LLM Worker Gateway.
    \"\"\"
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

    # Maximum number of retry attempts per run iteration to prevent infinite loops
    MAX_RETRIES = len(workers) * 2 
    attempts = 0
    
    last_err = None

    while attempts < MAX_RETRIES:
        now = time.time()
        healthy_workers = [w for w in workers if w.get("enabled", True) and w.get("cooldown_until", 0) <= now]
        healthy_workers.sort(key=lambda x: x.get("priority", 0), reverse=True)

        if not healthy_workers:
            # If we exhausted all healthy workers, check if it was due to a rate limit and if we can wait.
            if last_err:
                err_str = str(last_err).lower()
                if any(k in err_str for k in ["rate_limit", "429", "timeout", "connection", "overloaded", "groqexception"]):
                    # Find the soonest cooldown to expire
                    soonest_worker = min(workers, key=lambda w: w.get("cooldown_until", now + 999))
                    wait_time = soonest_worker.get("cooldown_until", now) - now
                    if 0 < wait_time <= 60:
                        if emit:
                            emit("worker_switching", {"message": f"All workers in cooldown. Waiting {int(wait_time)}s for rate limit reset..."}, node="agent")
                        logger.info(f"All workers exhausted. Waiting {wait_time}s for retry-after to expire.")
                        time.sleep(wait_time + 1)
                        attempts += 1
                        continue # Try again after waiting
            
            # If we couldn't wait or no rate limit error triggered this
            raise Exception("JARVIS couldn't complete this task because all configured execution workers are currently unavailable or rate-limited.")

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
            last_err = e
            if api_key:
                if old_key is not None:
                    os.environ[env_key] = old_key
                elif env_key in os.environ:
                    del os.environ[env_key]

            err_str = str(e).lower()
            if any(k in err_str for k in ["rate_limit", "429", "timeout", "connection", "overloaded", "groqexception"]):
                import re
                cooldown_s = 30
                try:
                    match = re.search(r'try again in (\\d+\\.?\\d*)s', err_str)
                    if match:
                        cooldown_s = int(float(match.group(1))) + 2
                except Exception:
                    pass
                mark_worker_error(wid, str(e), cooldown_s)
                
                # Reload workers so loop sees updated cooldown
                workers = load_workers()
                
                if emit:
                    emit("worker_cooldown", {"worker_id": wid, "reason": "rate_limit", "cooldown_s": cooldown_s}, node="agent")
            else:
                mark_worker_error(wid, str(e), 60)
                workers = load_workers()
                if emit:
                    emit("worker_failed", {"worker_id": wid, "reason": "execution_failed"}, node="agent")
            continue

    raise Exception("JARVIS exhausted retry limit across configured workers.")"""

# Replace call_litellm
text = text[:text.find("def call_litellm")] + litellm_new + "\n\n\n" + call_llm_new

with open("backend/app/llm/router.py", "w", encoding="utf-8") as f:
    f.write(text)
