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

def get_models_catalog() -> List[Dict[str, Any]]:
    """
    Dynamically fetches live models from Groq and Ollama,
    and sorts them so GPT OSS 120B, GPT OSS 20B, and Qwen3 are prominently at the top.
    """
    catalog = []

    # 1. Fetch live Groq models
    groq_models = fetch_live_groq_models()
    catalog.extend(groq_models)

    # 2. Fetch live Ollama models
    ollama_models = fetch_live_ollama_models()
    catalog.extend(ollama_models)

    # 3. Add OpenAI & Anthropic models
    openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    catalog.append({
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "openai",
        "provider_name": "OpenAI",
        "context_window": "128k",
        "badge": "Flagship",
        "tags": ["TOOL CALLING", "AGENTIC", "VISION"],
        "description": "Industry benchmark for complex multi-tool autonomous agency.",
        "available": openai_key,
        "status_text": "Ready" if openai_key else "Needs OPENAI_API_KEY",
        "priority": 30
    })
    catalog.append({
        "id": "gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider": "openai",
        "provider_name": "OpenAI",
        "context_window": "128k",
        "badge": "Fast",
        "tags": ["TOOL CALLING", "EFFICIENT"],
        "description": "Cost-effective, low latency tool calling and code generation.",
        "available": openai_key,
        "status_text": "Ready" if openai_key else "Needs OPENAI_API_KEY",
        "priority": 25
    })

    anthropic_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    catalog.append({
        "id": "claude-3-5-sonnet-20241022",
        "name": "Claude 3.5 Sonnet",
        "provider": "anthropic",
        "provider_name": "Anthropic",
        "context_window": "200k",
        "badge": "Benchmark",
        "tags": ["CODER", "AGENTIC", "REASONING"],
        "description": "State-of-the-art coding and agentic computer-use reasoning.",
        "available": anthropic_key,
        "status_text": "Ready" if anthropic_key else "Needs ANTHROPIC_API_KEY",
        "priority": 30
    })

    # Sort descending by priority so gpt-oss-120b, gpt-oss-20b, and qwen3 are at the very top!
    catalog.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return catalog

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
) -> str:
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

    try:
        if prov == "groq":
            try:
                groq_model = model_str.replace("groq/", "")
                client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
                groq_kwargs: Dict[str, Any] = {
                    "model": groq_model,
                    "messages": kwargs["messages"],
                }
                if tools:
                    groq_kwargs["tools"] = tools
                    groq_kwargs["tool_choice"] = "auto"
                response = client.chat.completions.create(**groq_kwargs)
            except Exception as groq_err:
                try:
                    import litellm
                    response = litellm.completion(**kwargs)
                except Exception:
                    raise groq_err
        else:
            import litellm
            response = litellm.completion(**kwargs)

        
        usage = getattr(response, "usage", None)
        if usage:
            p_tokens = getattr(usage, "prompt_tokens", 0)
            c_tokens = getattr(usage, "completion_tokens", 0)
            t_tokens = getattr(usage, "total_tokens", 0)
            print(f"[TOKEN USAGE] Model: {model_str} | Prompt: {p_tokens} | Completion: {c_tokens} | Total: {t_tokens}")

        message = response.choices[0].message
        
        # Check for native function / tool calls
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
        # Handle Groq's failed_generation if model generated a tool format string
        err_msg = str(exc)
        if "failed_generation" in err_msg:
            try:
                match = re.search(r'"failed_generation":\s*"({.*?})"', err_msg)
                if match:
                    raw_json_str = match.group(1).encode().decode('unicode-escape')
                    return f"<tool_call>\n{raw_json_str}\n</tool_call>"
            except Exception:
                pass
        raise exc


def call_llm(
    system: str,
    user: str,
    model: str = "openai/gpt-oss-120b",
    provider: str = "groq",
    tools: Optional[List[Dict[str, Any]]] = None,
    emit: Optional[Any] = None,
) -> Tuple[str, Optional[str]]:
    """
    Unified LLM router using LiteLLM to route to Groq, Ollama, OpenAI, or Anthropic.
    Now acts as the LLM Worker Gateway.
    """
    from app.llm.workers import load_workers, mark_worker_error, mark_worker_used
    import time
    
    workers = load_workers()
    now = time.time()
    
    healthy_workers = [w for w in workers if w.get("enabled", True) and w.get("cooldown_until", 0) <= now]
    healthy_workers.sort(key=lambda x: x.get("priority", 0), reverse=True)
    
    if not healthy_workers:
        # Fallback to standard environment keys if NO workers configured at all
        if not workers:
            try:
                raw_response = call_litellm(system, user, model, provider, tools=tools)
                return extract_thoughts(raw_response)
            except Exception as e:
                raise Exception(f"LLM provider error: {e}")
        else:
            raise Exception("JARVIS couldn't complete this task because all configured execution workers are currently unavailable.")
            
    last_err = None
    for w in healthy_workers:
        wid = w["worker_id"]
        w_model = w["model"]
        w_prov = w["provider"]
        api_key = w.get("api_key")
        
        if emit:
            emit("worker_switching", {"message": f"Switching execution worker to {w_prov} ({w_model})..."}, node="agent")
            
        try:
            env_key = f"{w_prov.upper()}_API_KEY"
            old_key = os.environ.get(env_key)
            if api_key:
                os.environ[env_key] = api_key
                
            raw_response = call_litellm(system, user, w_model, w_prov, tools=tools)
            
            if api_key:
                if old_key is not None:
                    os.environ[env_key] = old_key
                else:
                    del os.environ[env_key]
                
            mark_worker_used(wid)
            if emit:
                emit("worker_connected", {"message": "Worker connected — continuing."}, node="agent")
            return extract_thoughts(raw_response)
            
        except Exception as e:
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
                    match = re.search(r'try again in (\d+\.?\d*)s', err_str)
                    if match:
                        cooldown_s = int(float(match.group(1))) + 2
                except Exception:
                    pass
                mark_worker_error(wid, str(e), cooldown_s)
                if emit:
                    emit("worker_cooldown", {"worker_id": wid, "reason": "rate_limit", "cooldown_s": cooldown_s}, node="agent")
            else:
                mark_worker_error(wid, str(e), 60)
                if emit:
                    emit("worker_failed", {"worker_id": wid, "reason": "execution_failed"}, node="agent")
            continue
            
    raise Exception("JARVIS couldn't complete this task because all configured execution workers are currently unavailable.")

