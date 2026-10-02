from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.llm.providers import (
    get_all_providers_status,
    save_provider_api_key,
    delete_provider_api_key,
    discover_provider_models,
    get_full_models_catalog,
    set_model_enabled,
    is_model_enabled,
    load_model_preferences,
    save_model_preferences
)

router = APIRouter(prefix="/providers", tags=["Providers & Keys"])

class KeySaveRequest(BaseModel):
    api_key: str

class ModelToggleRequest(BaseModel):
    model_id: str
    enabled: bool

class ProviderToggleRequest(BaseModel):
    enabled: bool


@router.get("")
@router.get("/")
def list_providers():
    """Returns list of all supported providers, their configured status, masked key hints, and models count."""
    return {"providers": get_all_providers_status()}


@router.post("/{provider}/key")
def set_provider_key(provider: str, data: KeySaveRequest):
    """Saves and tests an API key for a provider (e.g. Gemini, Groq, OpenAI, Anthropic, OpenRouter)."""
    try:
        result = save_provider_api_key(provider, data.api_key)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save key: {str(e)}")


@router.delete("/{provider}/key")
def remove_provider_key(provider: str):
    """Deletes the stored API key for a provider."""
    try:
        result = delete_provider_api_key(provider)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete key: {str(e)}")


@router.get("/{provider}/models")
def get_provider_models(provider: str):
    """Fetches live models for a specific provider."""
    data = discover_provider_models(provider)
    return data


@router.post("/{provider}/toggle-all")
def toggle_all_provider_models(provider: str, data: ProviderToggleRequest):
    """Enables or disables all models for a specific provider."""
    discovered = discover_provider_models(provider)
    models = discovered.get("models", [])
    for m in models:
        set_model_enabled(m["id"], data.enabled)
    return {
        "success": True,
        "provider": provider,
        "enabled": data.enabled,
        "affected_models": len(models)
    }


# Models Router (for /api/models endpoints)
models_router = APIRouter(prefix="/models", tags=["Models"])

@models_router.get("")
@models_router.get("/")
def list_active_models():
    """Returns only the currently enabled and active models for the Model Selector."""
    return {"models": get_full_models_catalog(only_enabled=True)}


@models_router.get("/all")
def list_all_models_with_status():
    """Returns all available models across all providers with their enabled/disabled state."""
    return {"models": get_full_models_catalog(only_enabled=False)}


@models_router.post("/toggle")
def toggle_single_model(data: ModelToggleRequest):
    """Enables or disables a specific model for use in JARVIS."""
    set_model_enabled(data.model_id, data.enabled)
    return {
        "success": True,
        "model_id": data.model_id,
        "enabled": data.enabled
    }
