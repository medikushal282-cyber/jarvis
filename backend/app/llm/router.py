import os
import re
import json
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Tuple
from groq import Groq

# Well-known metadata overlays for models when fetched live
KNOWN_METADATA: Dict[str, Dict[str, Any]] = {
    "openai/gpt-oss-120b": {
        "name": "GPT OSS 120B (OpenAI)",
        "badge": "Flagship OSS",
        "context_window": "128k",
        "tags": ["TOOL CALLING", "AGENTIC", "REASONING", "CODER"],
        "description": "OpenAI flagship 120B open-weights model on Groq. Exceptional reasoning, tool-calling, and code architecture.",
        "priority": 100
    },
    "openai/gpt-oss-20b": {
        "name": "GPT OSS 20B (OpenAI)",
        "badge": "Ultra-Fast OSS",
        "context_window": "128k",
        "tags": ["TOOL CALLING", "AGENTIC", "FAST", "CODER"],
        "description": "OpenAI 20B open-weights model on Groq. Blazing fast tool calling, script execution, and live code editing.",
        "priority": 95
    },
    "qwen/qwen3.8-27b": {
        "name": "Qwen 3 (3.8 27B)",
        "badge": "Top Coder",
        "context_window": "32k",
        "tags": ["TOOL CALLING", "AGENTIC", "CODER"],
        "description": "Alibaba Qwen3 architecture on Groq. Highly tuned for autonomous software development and filesystem tasks.",
        "priority": 90
    },
    "groq/compound": {
        "name": "Groq Compound",
        "badge": "Agentic Compound",
        "context_window": "64k",
        "tags": ["TOOL CALLING", "AGENTIC", "ROUTER"],
        "description": "Groq multi-agent compound model optimized for orchestration and complex multi-step reasoning.",
        "priority": 80
    },
    "groq/compound-mini": {
        "name": "Groq Compound Mini",
        "badge": "Fast Compound",
        "context_window": "32k",
        "tags": ["TOOL CALLING", "FAST"],
        "description": "Lightweight compound model for fast tool loops and quick answers.",
        "priority": 75
    },
    "llama-3.3-70b-versatile": {
        "name": "Llama 3.3 70B Versatile",
        "badge": "Powerhouse",
        "context_window": "128k",
        "tags": ["REASONING", "TOOL CALLING", "AGENTIC"],
        "description": "Meta 70B open weights with deep strategic reasoning and high tool-calling reliability.",
        "priority": 85
    },
    "llama-3.1-8b-instant": {
        "name": "Llama 3.1 8B Instant",
        "badge": "Instant",
        "context_window": "128k",
        "tags": ["FAST", "TOOL CALLING"],
        "description": "Sub-second inference loops for quick tool executions.",
        "priority": 70
    },
    "qwen2.5-coder:latest": {
        "name": "Qwen 2.5 Coder (Ollama)",
        "badge": "Local OSS",
        "context_window": "32k",
        "tags": ["LOCAL", "CODER", "TOOL CALLING"],
        "description": "Top-tier open source coding model running completely locally on your machine.",
        "priority": 60
    },
    "deepseek-r1:latest": {
        "name": "DeepSeek R1 (Ollama)",
        "badge": "Reasoning",
        "context_window": "64k",
        "tags": ["LOCAL", "THINKING", "AGENTIC"],
        "description": "Native thinking model with deep mathematical and architectural chain-of-thought.",
        "priority": 55
    },
    "gpt-4o": {
        "name": "GPT-4o",
        "badge": "Flagship",
        "context_window": "128k",
        "tags": ["TOOL CALLING", "AGENTIC", "VISION"],
        "description": "Industry benchmark for complex multi-tool autonomous agency.",
        "priority": 50
    },
    "claude-3-5-sonnet-20241022": {
        "name": "Claude 3.5 Sonnet",
        "badge": "Benchmark",
        "context_window": "200k",
        "tags": ["CODER", "AGENTIC", "REASONING"],
        "description": "State-of-the-art coding and agentic computer-use reasoning.",
        "priority": 50
    }
}

def fetch_live_groq_models() -> List[Dict[str, Any]]:
    """Live fetch models directly from Groq's API."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return []
    
    models = []
    try:
        client = Groq(api_key=api_key)
        resp = client.models.list()
        for m in resp.data:
            mid = m.id
            mid_lower = mid.lower()
            # Filter out non-chat models (audio transcription, moderation guards, etc.)
            if "whisper" in mid_lower or "guard" in mid_lower or "orpheus" in mid_lower:
                continue
            
            meta = KNOWN_METADATA.get(mid, {})
            name = meta.get("name", mid.split("/")[-1].replace("-", " ").title())
            badge = meta.get("badge", "Groq Cloud")
            context = meta.get("context_window", "32k")
            tags = meta.get("tags", ["TOOL CALLING", "AGENTIC"])
            desc = meta.get("description", f"Groq high-speed cloud inference model: {mid}")
            priority = meta.get("priority", 10)

            models.append({
                "id": mid,
                "name": name,
                "provider": "groq",
                "provider_name": "Groq Cloud",
                "context_window": context,
                "badge": badge,
                "tags": tags,
                "description": desc,
                "available": True,
                "status_text": "Live (Connected)",
                "priority": priority
            })
    except Exception as e:
        print(f"Error fetching live Groq models: {e}")
        # Fallback to standard Groq list if network error
        for mid in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]:
            meta = KNOWN_METADATA.get(mid, {})
            models.append({
                "id": mid,
                "name": meta.get("name", mid),
                "provider": "groq",
                "provider_name": "Groq Cloud",
                "context_window": meta.get("context_window", "128k"),
                "badge": meta.get("badge", "Groq"),
                "tags": meta.get("tags", ["TOOL CALLING", "AGENTIC"]),
                "description": meta.get("description", ""),
                "available": True,
                "status_text": "Live (Connected)",
                "priority": meta.get("priority", 10)
            })
    return models

def fetch_live_ollama_models() -> List[Dict[str, Any]]:
    """Live fetch models installed in local Ollama daemon."""
    models = []
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", headers={"User-Agent": "frAIday"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("models", []):
                    m_name = item.get("name", "")
                    meta = KNOWN_METADATA.get(m_name, {})
                    models.append({
                        "id": m_name,
                        "name": meta.get("name", m_name),
                        "provider": "ollama",
                        "provider_name": "Ollama Local OSS",
                        "context_window": meta.get("context_window", "32k"),
                        "badge": "Local OSS",
                        "tags": meta.get("tags", ["LOCAL", "TOOL CALLING"]),
                        "description": meta.get("description", f"Local model installed in Ollama: {m_name}"),
                        "available": True,
                        "status_text": "Local Server Ready",
                        "priority": 40
                    })
    except Exception:
        pass

    # If no local Ollama models were found or Ollama is offline, provide standard placeholders
    if not models:
        for mid in ["qwen2.5-coder:latest", "deepseek-r1:latest", "llama3.2:latest"]:
            meta = KNOWN_METADATA.get(mid, {})
            models.append({
                "id": mid,
                "name": meta.get("name", mid),
                "provider": "ollama",
                "provider_name": "Ollama Local OSS",
                "context_window": meta.get("context_window", "32k"),
                "badge": "Local OSS",
                "tags": meta.get("tags", ["LOCAL", "TOOL CALLING"]),
                "description": meta.get("description", "Local OSS model via Ollama (:11434)"),
                "available": False,
                "status_text": "Ollama Offline (:11434)",
                "priority": 20
            })
    return models

def get_models_catalog(only_enabled: bool = True) -> List[Dict[str, Any]]:
    """
    Dynamically fetches live models across all configured providers (Gemini, Groq, Ollama, OpenAI, Anthropic, OpenRouter),
    filtered by user enable/disable preferences.
    """
    try:
        from app.llm.providers import get_full_models_catalog
        return get_full_models_catalog(only_enabled=only_enabled)
    except Exception as e:
        print(f"Error fetching full models catalog: {e}")
        # Fallback to local Groq catalog
        return fetch_live_groq_models()

def extract_thoughts(raw_text: str) -> Tuple[str, Optional[str]]:
    """Extracts <thought>...</thought> or <think>...</think> from model response."""
    thought_match = re.search(r'<(?:thought|think)>(.*?)</(?:thought|think)>', raw_text, re.DOTALL | re.IGNORECASE)
    if thought_match:
        thought_text = thought_match.group(1).strip()
        cleaned_text = re.sub(r'<(?:thought|think)>.*?</(?:thought|think)>', '', raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
        return cleaned_text, thought_text
    return raw_text.strip(), None

def call_litellm(
    system: str,
    user: str,
    model: str,
    provider: str = "groq",
    tools: Optional[List[Dict[str, Any]]] = None,
    run_id: Optional[str] = None,
    turn_idx: Optional[int] = None,
    worker_id: Optional[str] = None,
    emit: Optional[Any] = None,
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
        if not os.environ.get("GROQ_API_KEY"):
            from app.llm.providers import get_effective_provider_key
            k = get_effective_provider_key("groq")
            if k:
                os.environ["GROQ_API_KEY"] = k
    elif prov in ("gemini", "google"):
        clean_m = model_str
        if clean_m.startswith("models/"):
            clean_m = clean_m[7:]
        if clean_m.startswith("gemini/"):
            clean_m = clean_m[7:]
        model_str = f"gemini/{clean_m}"
        
        if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
            from app.llm.providers import get_effective_provider_key
            k = get_effective_provider_key("gemini")
            if k:
                os.environ["GEMINI_API_KEY"] = k
                os.environ["GOOGLE_API_KEY"] = k
    elif prov == "ollama":
        if not model_str.startswith("ollama/"):
            model_str = f"ollama/{model_str}"
    elif prov == "openai":
        if not model_str.startswith("openai/"):
            model_str = f"openai/{model_str}"
        if not os.environ.get("OPENAI_API_KEY"):
            from app.llm.providers import get_effective_provider_key
            k = get_effective_provider_key("openai")
            if k:
                os.environ["OPENAI_API_KEY"] = k
    elif prov == "anthropic":
        if not model_str.startswith("anthropic/"):
            model_str = f"anthropic/{model_str}"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            from app.llm.providers import get_effective_provider_key
            k = get_effective_provider_key("anthropic")
            if k:
                os.environ["ANTHROPIC_API_KEY"] = k
    elif prov == "openrouter":
        clean_m = model_str[11:] if model_str.startswith("openrouter/") else model_str
        model_str = f"openrouter/{clean_m}"
        if not os.environ.get("OPENROUTER_API_KEY"):
            from app.llm.providers import get_effective_provider_key
            k = get_effective_provider_key("openrouter")
            if k:
                os.environ["OPENROUTER_API_KEY"] = k

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
                    rendered_calls.append(f"<tool_call>\n{json.dumps({'name': fn_name, 'arguments': parsed_args})}\n</tool_call>")

            tool_str = "\n".join(rendered_calls)
            return f"{content}\n{tool_str}".strip() if content else tool_str

        return content
    except Exception as exc:
        err_msg = str(exc).lower()
        if any(k in err_msg for k in ["rate_limit", "429", "too many requests"]):
            rate_limit = True
        if "failed_generation" in err_msg:
            try:
                import re
                match = re.search(r'"failed_generation":\s*"({.*?})"', str(exc))
                if match:
                    raw_json_str = match.group(1).encode().decode('unicode-escape')
                    success = True
                    return f"<tool_call>\n{raw_json_str}\n</tool_call>"
            except Exception:
                pass
        raise exc
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        print(f"LLM_REQUEST: worker_id={worker_id}, provider={prov}, model={model_str}, run_id={run_id}, turn={turn_idx}, prompt_tokens={p_tokens}, completion_tokens={c_tokens}, total_tokens={t_tokens}, duration_ms={duration_ms}, success={success}, rate_limit={rate_limit}")
        
        if emit:
            # Emit live LLM context telemetry
            sys_tok = len(system) // 4
            user_tok = len(user) // 4
            tool_tok = len(str(tools)) // 4 if tools else 0
            
            emit("context_built", {
                "prompt_tokens": p_tokens,
                "completion_tokens": c_tokens,
                "total_tokens": t_tokens,
                "system_tokens_est": sys_tok,
                "user_tokens_est": user_tok,
                "tool_tokens_est": tool_tok,
                "model": model_str,
                "provider": prov,
                "worker_id": worker_id,
                "run_id": run_id,
                "turn": turn_idx,
                "duration_ms": duration_ms,
                "success": success,
                "rate_limit": rate_limit
            })


def call_llm(
    system: str,
    user: str,
    model: str = None,
    provider: str = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    emit: Optional[Any] = None,
    run_id: Optional[str] = None,
    turn_idx: Optional[int] = None,
) -> Tuple[str, Optional[str]]:
    """
    Unified LLM router using LiteLLM to route to Groq, Ollama, OpenAI, or Anthropic.
    Now acts as the LLM Worker Gateway.
    """
    import os as _os
    if model is None:
        model = _os.environ.get("JARVIS_DEFAULT_MODEL", "openai/gpt-oss-20b")
    if provider is None:
        provider = _os.environ.get("JARVIS_DEFAULT_PROVIDER", "groq")

    from app.llm.workers import load_workers, mark_worker_error, mark_worker_used
    import time
    import logging
    logger = logging.getLogger(__name__)

    workers = load_workers()

    def _classify_error(err_msg: str) -> Tuple[bool, bool, bool, int]:
        """Classifies error into (is_high_demand, is_rate_limit, is_fatal_exhausted, suggested_cooldown)."""
        lower = err_msg.lower()
        is_exhausted = ("tokens per day" in lower or "tpd" in lower or "daily quota" in lower)
        if is_exhausted:
            return False, False, True, 0
        
        is_high_demand = any(k in lower for k in [
            "503", "502", "504",
            "high demand", "experiencing high demand",
            "spikes in demand", "service unavailable",
            "temporarily unavailable", "overloaded",
            "model is overloaded", "capacity", "server error"
        ])
        
        is_rate_limit = any(k in lower for k in [
            "429", "rate_limit", "rate limit", "too many requests", "resource_exhausted"
        ])
        
        cooldown = 15
        import re
        try:
            match = re.search(r'try again in (\d+\.?\d*)s', lower)
            if match:
                cooldown = max(cooldown, int(float(match.group(1))) + 3)
        except Exception:
            pass
            
        return is_high_demand, is_rate_limit, False, cooldown

    if not workers:
        # Fallback to standard environment keys if NO workers configured at all
        max_retries = 5
        for attempt in range(max_retries):
            try:
                raw_response = call_litellm(system, user, model, provider, tools=tools, run_id=run_id, turn_idx=turn_idx, emit=emit)
                if attempt > 0 and emit:
                    emit("worker_connected", {"message": "Model reconnected and responded successfully."}, node="agent")
                return extract_thoughts(raw_response)
            except Exception as e:
                err_str = str(e)
                is_high_demand, is_rate_limit, is_fatal, suggested_cooldown = _classify_error(err_str)
                
                if (is_high_demand or is_rate_limit) and not is_fatal and attempt < max_retries - 1:
                    # Progressive backoff for high demand spikes: 4s -> 8s -> 15s -> 25s -> 35s
                    backoffs = [4, 8, 15, 25, 35]
                    cooldown_s = backoffs[min(attempt, len(backoffs) - 1)]
                    if is_rate_limit and suggested_cooldown > cooldown_s:
                        cooldown_s = suggested_cooldown
                    
                    notice = (
                        f"Model '{model}' is currently in high demand (surging traffic). "
                        f"Responses may take slightly longer — automatically retrying in {cooldown_s}s (Attempt {attempt+1}/{max_retries})..."
                    ) if is_high_demand else (
                        f"Rate limit reached on '{model}'. Waiting {cooldown_s}s before retrying (Attempt {attempt+1}/{max_retries})..."
                    )
                    
                    if emit:
                        emit("high_demand", {
                            "message": notice,
                            "attempt": attempt + 1,
                            "max_attempts": max_retries,
                            "cooldown_s": cooldown_s,
                            "model": model,
                            "provider": provider,
                            "is_high_demand": is_high_demand
                        }, node="agent")
                        emit("worker_switching", {"message": notice}, node="agent")
                    
                    import time
                    time.sleep(cooldown_s)
                    continue
                
                raise Exception(f"LLM provider error: {e}")

    # Filter out malformed worker entries (missing required fields) before any processing
    workers = [w for w in workers if w.get("worker_id") and w.get("model") and w.get("provider")]

    MAX_RETRIES = max(len(workers) * 2, 1)
    attempts = 0
    failures = []

    while attempts < MAX_RETRIES:
        now = time.time()
        healthy_workers = [w for w in workers if w.get("enabled", True) and w.get("cooldown_until", 0) <= now]
        healthy_workers.sort(key=lambda x: (-x.get("priority", 0), x.get("last_used_at", 0)))

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
                import asyncio
                # time.sleep is fine since we're in to_thread, but let's just use time.sleep. 
                # The user said "If it uses time.sleep(...) and executes inside async...". 
                # It does not execute inside async, it executes in a thread pool. But let's be safe.
                time.sleep(wait_time + 1)
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
        credential_env = w.get("credential_env")
        if credential_env and credential_env in os.environ:
            api_key = os.environ[credential_env]


        if emit and attempts > 0:
            emit("worker_switching", {"message": f"Switching execution worker to {w_prov} ({w_model})..."}, node="agent")
            emit("worker_selected", {"worker_id": wid}, node="agent")

        try:
            env_key = f"{w_prov.upper()}_API_KEY"
            old_key = os.environ.get(env_key)
            if api_key:
                os.environ[env_key] = api_key

            raw_response = call_litellm(system, user, w_model, w_prov, tools=tools, run_id=run_id, turn_idx=turn_idx, worker_id=wid, emit=emit)

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

            err_str = str(e)
            is_high_demand, is_rate_limit, is_fatal, suggested_cooldown = _classify_error(err_str)
            
            failures.append({
                "worker_id": wid,
                "provider": w_prov,
                "model": w_model,
                "error_type": type(e).__name__,
                "message": str(e),
                "rate_limit": is_rate_limit or is_high_demand
            })

            if is_high_demand or is_rate_limit:
                cooldown_s = suggested_cooldown if suggested_cooldown > 0 else 20
                mark_worker_error(wid, str(e), cooldown_s)
                workers = load_workers()
                if emit:
                    emit("worker_cooldown", {
                        "worker_id": wid,
                        "reason": "high_demand" if is_high_demand else "rate_limit",
                        "cooldown_s": cooldown_s
                    }, node="agent")
            else:
                # For non-rate-limit errors, mark with a cooldown so other workers are tried
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
        
    raise Exception("\n".join(error_lines))