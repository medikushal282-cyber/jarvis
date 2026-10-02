import os
import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
KEYS_FILE = os.path.join(DATA_DIR, "provider_keys.json")
PREFERENCES_FILE = os.path.join(DATA_DIR, "model_preferences.json")
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".env")

PROVIDERS_CONFIG: Dict[str, Dict[str, Any]] = {
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "company": "Google AI Studio",
        "env_var": "GEMINI_API_KEY",
        "alt_env_vars": ["GOOGLE_API_KEY"],
        "docs_url": "https://aistudio.google.com/app/apikey",
        "description": "Google Gemini flagship reasoning and multimodal models (Gemini 2.5 Pro, 2.5 Flash, 2.0 Flash, 1.5 Pro).",
        "badge": "Google",
        "default_models": [
            {
                "id": "gemini/gemini-2.5-pro",
                "name": "Gemini 2.5 Pro",
                "context_window": "2M",
                "badge": "Flagship Thinking",
                "tags": ["THINKING", "REASONING", "AGENTIC", "CODER", "2M CONTEXT"],
                "description": "Google state-of-the-art multimodal reasoning model with ultra-long 2M context window.",
                "priority": 98
            },
            {
                "id": "gemini/gemini-2.5-flash",
                "name": "Gemini 2.5 Flash",
                "context_window": "1M",
                "badge": "Fast Thinking",
                "tags": ["FAST", "AGENTIC", "TOOL CALLING", "1M CONTEXT"],
                "description": "Next-gen lightweight multimodal model with high speed and strong agentic tool performance.",
                "priority": 94
            },
            {
                "id": "gemini/gemini-2.0-flash",
                "name": "Gemini 2.0 Flash",
                "context_window": "1M",
                "badge": "Ultra-Fast",
                "tags": ["FAST", "TOOL CALLING", "AGENTIC"],
                "description": "High-throughput, sub-second latency model optimized for tool use and high concurrency.",
                "priority": 92
            },
            {
                "id": "gemini/gemini-1.5-pro",
                "name": "Gemini 1.5 Pro",
                "context_window": "2M",
                "badge": "Deep Analysis",
                "tags": ["REASONING", "2M CONTEXT", "CODER"],
                "description": "Mid-tier powerhouse with 2M token context for massive codebase and document understanding.",
                "priority": 85
            },
            {
                "id": "gemini/gemini-1.5-flash",
                "name": "Gemini 1.5 Flash",
                "context_window": "1M",
                "badge": "Efficient",
                "tags": ["FAST", "EFFICIENT"],
                "description": "Fast and versatile multimodal model for general agent tasks.",
                "priority": 80
            }
        ]
    },
    "groq": {
        "id": "groq",
        "name": "Groq Cloud",
        "company": "Groq",
        "env_var": "GROQ_API_KEY",
        "alt_env_vars": [],
        "docs_url": "https://console.groq.com/keys",
        "description": "Ultra-fast LPU inference for OpenAI OSS, Qwen 3, and Meta Llama models.",
        "badge": "Groq LPU",
        "default_models": []
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "company": "OpenAI",
        "env_var": "OPENAI_API_KEY",
        "alt_env_vars": [],
        "docs_url": "https://platform.openai.com/api-keys",
        "description": "OpenAI GPT-4o, GPT-4o Mini, and reasoning models.",
        "badge": "OpenAI",
        "default_models": [
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o",
                "context_window": "128k",
                "badge": "Flagship",
                "tags": ["TOOL CALLING", "AGENTIC", "VISION"],
                "description": "Industry benchmark for complex multi-tool autonomous agency.",
                "priority": 88
            },
            {
                "id": "openai/gpt-4o-mini",
                "name": "GPT-4o Mini",
                "context_window": "128k",
                "badge": "Fast",
                "tags": ["TOOL CALLING", "EFFICIENT"],
                "description": "Cost-effective, low latency tool calling and code generation.",
                "priority": 82
            },
            {
                "id": "openai/o3-mini",
                "name": "o3-mini",
                "context_window": "200k",
                "badge": "Reasoning",
                "tags": ["REASONING", "CODER", "MATH"],
                "description": "Specialized reasoning model for high-difficulty coding and logic puzzles.",
                "priority": 86
            }
        ]
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic",
        "company": "Anthropic",
        "env_var": "ANTHROPIC_API_KEY",
        "alt_env_vars": [],
        "docs_url": "https://console.anthropic.com/settings/keys",
        "description": "Claude 3.5 Sonnet and Haiku models with advanced reasoning and tool use.",
        "badge": "Anthropic",
        "default_models": [
            {
                "id": "anthropic/claude-3-5-sonnet-20241022",
                "name": "Claude 3.5 Sonnet",
                "context_window": "200k",
                "badge": "Top Coder",
                "tags": ["CODER", "AGENTIC", "REASONING"],
                "description": "State-of-the-art coding and agentic computer-use reasoning.",
                "priority": 90
            },
            {
                "id": "anthropic/claude-3-5-haiku-20241022",
                "name": "Claude 3.5 Haiku",
                "context_window": "200k",
                "badge": "Fast",
                "tags": ["FAST", "TOOL CALLING"],
                "description": "High-speed intelligence with strong tool calling and syntax comprehension.",
                "priority": 84
            }
        ]
    },
    "openrouter": {
        "id": "openrouter",
        "name": "OpenRouter",
        "company": "OpenRouter",
        "env_var": "OPENROUTER_API_KEY",
        "alt_env_vars": [],
        "docs_url": "https://openrouter.ai/keys",
        "description": "Unified API gateway connecting 200+ AI models across multiple providers.",
        "badge": "OpenRouter",
        "default_models": [
            {
                "id": "openrouter/anthropic/claude-3.5-sonnet",
                "name": "Claude 3.5 Sonnet (OpenRouter)",
                "context_window": "200k",
                "badge": "Benchmark",
                "tags": ["ROUTER", "CODER"],
                "description": "Claude 3.5 Sonnet routed via OpenRouter.",
                "priority": 75
            },
            {
                "id": "openrouter/deepseek/deepseek-r1",
                "name": "DeepSeek R1 (OpenRouter)",
                "context_window": "64k",
                "badge": "Reasoning",
                "tags": ["THINKING", "OPENROUTER"],
                "description": "DeepSeek R1 reasoning model routed via OpenRouter.",
                "priority": 74
            }
        ]
    },
    "ollama": {
        "id": "ollama",
        "name": "Ollama (Local OSS)",
        "company": "Local",
        "env_var": "",
        "alt_env_vars": [],
        "docs_url": "https://ollama.com",
        "description": "Local offline open-source models running on your hardware via Ollama.",
        "badge": "Local OSS",
        "default_models": []
    }
}


# --- Storage Helpers ---

def load_stored_keys() -> Dict[str, str]:
    if not os.path.exists(KEYS_FILE):
        return {}
    try:
        with open(KEYS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_stored_keys(keys: Dict[str, str]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2)

def update_env_file(key_name: str, key_val: Optional[str]) -> None:
    """Safely updates or removes a key in the backend .env file."""
    lines = []
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r") as f:
                lines = f.readlines()
        except Exception:
            lines = []

    updated = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key_name}="):
            if key_val is not None:
                new_lines.append(f"{key_name}={key_val}\n")
            updated = True
        else:
            new_lines.append(line)

    if not updated and key_val is not None:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key_name}={key_val}\n")

    try:
        with open(ENV_FILE, "w") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"Warning: Could not update .env file: {e}")

def sync_keys_to_environment() -> None:
    """Loads stored keys into os.environ on startup."""
    keys = load_stored_keys()
    for prov_id, api_key in keys.items():
        if not api_key:
            continue
        cfg = PROVIDERS_CONFIG.get(prov_id)
        if cfg and cfg["env_var"]:
            os.environ[cfg["env_var"]] = api_key
            for alt in cfg.get("alt_env_vars", []):
                os.environ[alt] = api_key

# Sync immediately on module load
sync_keys_to_environment()


# --- Model Preferences Storage ---

def load_model_preferences() -> Dict[str, Any]:
    if not os.path.exists(PREFERENCES_FILE):
        return {"enabled_models": [], "disabled_models": []}
    try:
        with open(PREFERENCES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"enabled_models": [], "disabled_models": []}

def save_model_preferences(prefs: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PREFERENCES_FILE, "w") as f:
        json.dump(prefs, f, indent=2)

def is_model_enabled(model_id: str, default_if_unspecified: bool = True) -> bool:
    prefs = load_model_preferences()
    enabled = set(prefs.get("enabled_models", []))
    disabled = set(prefs.get("disabled_models", []))
    if model_id in disabled:
        return False
    if model_id in enabled:
        return True
    return default_if_unspecified

def set_model_enabled(model_id: str, enabled: bool) -> None:
    prefs = load_model_preferences()
    enabled_set = set(prefs.get("enabled_models", []))
    disabled_set = set(prefs.get("disabled_models", []))

    if enabled:
        enabled_set.add(model_id)
        disabled_set.discard(model_id)
    else:
        disabled_set.add(model_id)
        enabled_set.discard(model_id)

    prefs["enabled_models"] = sorted(list(enabled_set))
    prefs["disabled_models"] = sorted(list(disabled_set))
    save_model_preferences(prefs)


# --- Provider Status & Key Management ---

def get_effective_provider_key(provider_id: str) -> Optional[str]:
    cfg = PROVIDERS_CONFIG.get(provider_id)
    if not cfg:
        return None
    
    # 1. Stored keys
    stored = load_stored_keys().get(provider_id)
    if stored:
        return stored
    
    # 2. Environment variables
    if cfg["env_var"] and os.environ.get(cfg["env_var"]):
        return os.environ.get(cfg["env_var"])
    
    for alt in cfg.get("alt_env_vars", []):
        if os.environ.get(alt):
            return os.environ.get(alt)
            
    return None

def get_provider_key_hint(provider_id: str) -> str:
    key = get_effective_provider_key(provider_id)
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"

def save_provider_api_key(provider_id: str, api_key: str) -> Dict[str, Any]:
    prov = provider_id.lower().strip()
    if prov not in PROVIDERS_CONFIG:
        raise ValueError(f"Unknown provider '{prov}'")

    cfg = PROVIDERS_CONFIG[prov]
    clean_key = api_key.strip()
    
    # Update stored keys
    stored = load_stored_keys()
    stored[prov] = clean_key
    save_stored_keys(stored)

    # Update os.environ
    if cfg["env_var"]:
        os.environ[cfg["env_var"]] = clean_key
        for alt in cfg.get("alt_env_vars", []):
            os.environ[alt] = clean_key
        update_env_file(cfg["env_var"], clean_key)

    # Auto-enable default models for this provider if not explicitly disabled
    discovered = discover_provider_models(prov, clean_key)
    for m in discovered.get("models", []):
        mid = m["id"]
        # Enable by default if never touched
        prefs = load_model_preferences()
        if mid not in prefs.get("disabled_models", []):
            set_model_enabled(mid, True)

    return {
        "success": True,
        "provider": prov,
        "configured": True,
        "key_hint": get_provider_key_hint(prov),
        "models_found": len(discovered.get("models", [])),
        "message": f"Successfully configured {cfg['name']} API key"
    }

def delete_provider_api_key(provider_id: str) -> Dict[str, Any]:
    prov = provider_id.lower().strip()
    if prov not in PROVIDERS_CONFIG:
        raise ValueError(f"Unknown provider '{prov}'")

    cfg = PROVIDERS_CONFIG[prov]
    
    stored = load_stored_keys()
    if prov in stored:
        del stored[prov]
        save_stored_keys(stored)

    if cfg["env_var"]:
        os.environ.pop(cfg["env_var"], None)
        for alt in cfg.get("alt_env_vars", []):
            os.environ.pop(alt, None)
        update_env_file(cfg["env_var"], None)

    return {
        "success": True,
        "provider": prov,
        "configured": False,
        "key_hint": "",
        "message": f"Removed API key for {cfg['name']}"
    }


# --- Live Model Discovery ---

def discover_gemini_models(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    key = api_key or get_effective_provider_key("gemini")
    if not key:
        # Return fallback defaults marked as unconfigured
        return [
            {
                **m,
                "provider": "gemini",
                "provider_name": "Google Gemini",
                "available": False,
                "status_text": "Needs GEMINI_API_KEY",
                "enabled": is_model_enabled(m["id"], default_if_unspecified=True)
            }
            for m in PROVIDERS_CONFIG["gemini"]["default_models"]
        ]

    models: List[Dict[str, Any]] = []
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-Agent"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                known_defaults = {m["id"]: m for m in PROVIDERS_CONFIG["gemini"]["default_models"]}
                
                for item in data.get("models", []):
                    name_raw = item.get("name", "") # e.g. "models/gemini-2.5-pro" or "models/gemini-2.0-flash"
                    methods = item.get("supportedGenerationMethods", [])
                    if "generateContent" not in methods:
                        continue
                    
                    m_id_clean = name_raw.replace("models/", "")
                    full_id = f"gemini/{m_id_clean}"

                    # Skip internal/legacy experimental embedding variants
                    if "embedding" in m_id_clean or "aqa" in m_id_clean:
                        continue

                    display_name = item.get("displayName") or m_id_clean.replace("-", " ").title()
                    desc = item.get("description") or f"Google Gemini model: {display_name}"
                    
                    input_limit = item.get("inputTokenLimit", 1000000)
                    if input_limit >= 2000000:
                        ctx = "2M"
                    elif input_limit >= 1000000:
                        ctx = "1M"
                    elif input_limit >= 128000:
                        ctx = "128k"
                    else:
                        ctx = f"{input_limit // 1000}k"

                    tags = ["GOOGLE", "AGENTIC", "MULTIMODAL"]
                    if "thinking" in desc.lower() or "pro" in m_id_clean:
                        tags.append("REASONING")
                    if "flash" in m_id_clean:
                        tags.append("FAST")

                    meta = known_defaults.get(full_id, {})
                    priority = meta.get("priority", 70)
                    badge = meta.get("badge", "Google AI")

                    models.append({
                        "id": full_id,
                        "name": display_name,
                        "provider": "gemini",
                        "provider_name": "Google Gemini",
                        "context_window": ctx,
                        "badge": badge,
                        "tags": tags,
                        "description": desc,
                        "available": True,
                        "status_text": "Live (Connected)",
                        "priority": priority,
                        "enabled": is_model_enabled(full_id, default_if_unspecified=True)
                    })
    except Exception as e:
        print(f"Error querying Google Gemini API: {e}")
        # Fallback to curated default list with connection status
        for m in PROVIDERS_CONFIG["gemini"]["default_models"]:
            models.append({
                **m,
                "provider": "gemini",
                "provider_name": "Google Gemini",
                "available": True,
                "status_text": "Configured (Cached)",
                "enabled": is_model_enabled(m["id"], default_if_unspecified=True)
            })

    # Sort descending by priority
    models.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return models


def discover_groq_models(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    from app.llm.router import fetch_live_groq_models, KNOWN_METADATA
    key = api_key or get_effective_provider_key("groq")
    
    models = []
    if key:
        old_k = os.environ.get("GROQ_API_KEY")
        try:
            os.environ["GROQ_API_KEY"] = key
            live_models = fetch_live_groq_models()
            for m in live_models:
                m["enabled"] = is_model_enabled(m["id"], default_if_unspecified=True)
                models.append(m)
        finally:
            if old_k is not None:
                os.environ["GROQ_API_KEY"] = old_k
            elif "GROQ_API_KEY" in os.environ and not api_key:
                pass

    if not models:
        for mid in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile"]:
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
                "available": bool(key),
                "status_text": "Ready" if key else "Needs GROQ_API_KEY",
                "priority": meta.get("priority", 50),
                "enabled": is_model_enabled(mid, default_if_unspecified=True)
            })
    return models


def discover_openai_models(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    key = api_key or get_effective_provider_key("openai")
    models = []
    for m in PROVIDERS_CONFIG["openai"]["default_models"]:
        models.append({
            **m,
            "provider": "openai",
            "provider_name": "OpenAI",
            "available": bool(key),
            "status_text": "Ready" if key else "Needs OPENAI_API_KEY",
            "enabled": is_model_enabled(m["id"], default_if_unspecified=True)
        })
    return models


def discover_anthropic_models(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    key = api_key or get_effective_provider_key("anthropic")
    models = []
    for m in PROVIDERS_CONFIG["anthropic"]["default_models"]:
        models.append({
            **m,
            "provider": "anthropic",
            "provider_name": "Anthropic",
            "available": bool(key),
            "status_text": "Ready" if key else "Needs ANTHROPIC_API_KEY",
            "enabled": is_model_enabled(m["id"], default_if_unspecified=True)
        })
    return models


def discover_openrouter_models(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    key = api_key or get_effective_provider_key("openrouter")
    models = []
    if key:
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {key}", "User-Agent": "JARVIS-Agent"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    for item in data.get("data", [])[:15]: # Top 15
                        mid = f"openrouter/{item.get('id')}"
                        name = item.get("name") or item.get("id")
                        ctx = f"{item.get('context_length', 32000) // 1000}k"
                        models.append({
                            "id": mid,
                            "name": name,
                            "provider": "openrouter",
                            "provider_name": "OpenRouter",
                            "context_window": ctx,
                            "badge": "OpenRouter",
                            "tags": ["OPENROUTER", "AGENTIC"],
                            "description": item.get("description") or f"Model on OpenRouter: {name}",
                            "available": True,
                            "status_text": "Live (Connected)",
                            "priority": 60,
                            "enabled": is_model_enabled(mid, default_if_unspecified=True)
                        })
        except Exception as e:
            print(f"Error fetching OpenRouter models: {e}")

    if not models:
        for m in PROVIDERS_CONFIG["openrouter"]["default_models"]:
            models.append({
                **m,
                "provider": "openrouter",
                "provider_name": "OpenRouter",
                "available": bool(key),
                "status_text": "Ready" if key else "Needs OPENROUTER_API_KEY",
                "enabled": is_model_enabled(m["id"], default_if_unspecified=True)
            })
    return models


def discover_ollama_models() -> List[Dict[str, Any]]:
    from app.llm.router import fetch_live_ollama_models
    live = fetch_live_ollama_models()
    for m in live:
        m["enabled"] = is_model_enabled(m["id"], default_if_unspecified=True)
    return live


def discover_provider_models(provider_id: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    prov = provider_id.lower().strip()
    if prov == "gemini" or prov == "google":
        models = discover_gemini_models(api_key)
    elif prov == "groq":
        models = discover_groq_models(api_key)
    elif prov == "openai":
        models = discover_openai_models(api_key)
    elif prov == "anthropic":
        models = discover_anthropic_models(api_key)
    elif prov == "openrouter":
        models = discover_openrouter_models(api_key)
    elif prov == "ollama":
        models = discover_ollama_models()
    else:
        models = []

    return {
        "provider": prov,
        "models": models,
        "count": len(models)
    }


def get_all_providers_status() -> List[Dict[str, Any]]:
    result = []
    for prov_id, cfg in PROVIDERS_CONFIG.items():
        key = get_effective_provider_key(prov_id)
        configured = bool(key) if prov_id != "ollama" else True
        key_hint = get_provider_key_hint(prov_id)

        # Discover model count and enabled count
        models_data = discover_provider_models(prov_id, key)
        models_list = models_data.get("models", [])
        enabled_count = sum(1 for m in models_list if m.get("enabled", False))

        status = "unconfigured"
        if prov_id == "ollama":
            status = "connected" if any(m.get("available") for m in models_list) else "offline"
        elif configured:
            status = "connected"

        result.append({
            "id": prov_id,
            "name": cfg["name"],
            "company": cfg["company"],
            "env_var": cfg["env_var"],
            "docs_url": cfg["docs_url"],
            "description": cfg["description"],
            "badge": cfg["badge"],
            "configured": configured,
            "key_hint": key_hint,
            "status": status,
            "models_count": len(models_list),
            "enabled_models_count": enabled_count,
            "models": models_list
        })
    return result


def get_full_models_catalog(only_enabled: bool = True) -> List[Dict[str, Any]]:
    """
    Unified catalog of all models across all configured providers.
    If only_enabled=True, returns only the models that the user has selected.
    """
    catalog: List[Dict[str, Any]] = []
    
    # 1. Gemini
    catalog.extend(discover_gemini_models())
    # 2. Groq
    catalog.extend(discover_groq_models())
    # 3. Ollama
    catalog.extend(discover_ollama_models())
    # 4. OpenAI
    catalog.extend(discover_openai_models())
    # 5. Anthropic
    catalog.extend(discover_anthropic_models())
    # 6. OpenRouter
    catalog.extend(discover_openrouter_models())

    if only_enabled:
        catalog = [m for m in catalog if m.get("enabled", True) and m.get("available", True)]

    # Sort descending by priority
    catalog.sort(key=lambda x: (
        not x.get("available", False), # Available first
        -x.get("priority", 0)           # Higher priority first
    ))

    return catalog
