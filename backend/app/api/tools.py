import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException

from app.tools.registry import get_tool_registry

router = APIRouter(prefix="/tools", tags=["tools"])

PREFS_FILE = Path(__file__).parent.parent.parent / "data" / "tool_preferences.json"

def _load_prefs() -> Dict[str, Any]:
    if not PREFS_FILE.exists():
        return {"enabled_tools": {}, "enabled_categories": {}}
    try:
        with open(PREFS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"enabled_tools": {}, "enabled_categories": {}}

def _save_prefs(prefs: Dict[str, Any]):
    PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PREFS_FILE, "w") as f:
        json.dump(prefs, f, indent=2)

def get_enabled_tool_names() -> set[str]:
    prefs = _load_prefs()
    registry = get_tool_registry()
    enabled_names = set()
    for tool in registry.list_tools():
        cat = getattr(tool, "category", None) or "general"
        cat_enabled = prefs.get("enabled_categories", {}).get(cat, True)
        tool_enabled = prefs.get("enabled_tools", {}).get(tool.name, True)
        
        if cat_enabled and tool_enabled:
            enabled_names.add(tool.name)
    return enabled_names

@router.get("")
async def list_tools():
    """List all registered tools with metadata."""
    registry = get_tool_registry()
    prefs = _load_prefs()
    
    tools = []
    for t in registry.list_tools():
        cat = getattr(t, "category", None) or "general"
        cat_enabled = prefs.get("enabled_categories", {}).get(cat, True)
        tool_enabled = prefs.get("enabled_tools", {}).get(t.name, True)
        is_enabled = cat_enabled and tool_enabled
        
        tools.append({
            "name": t.name,
            "description": getattr(t, "description", ""),
            "category": cat,
            "risk": getattr(t, "risk", "medium"),
            "permissions": getattr(t, "required_permissions", []),
            "parameters": getattr(t, "parameters", {}),
            "enabled": is_enabled,
            "explicitly_disabled": prefs.get("enabled_tools", {}).get(t.name) is False
        })
    return {"tools": tools}

@router.post("/{tool_name}/toggle")
async def toggle_tool(tool_name: str, enabled: bool):
    """Enable or disable a specific tool."""
    registry = get_tool_registry()
    if not registry.get_tool(tool_name):
        raise HTTPException(status_code=404, detail="Tool not found")
        
    prefs = _load_prefs()
    if "enabled_tools" not in prefs:
        prefs["enabled_tools"] = {}
    prefs["enabled_tools"][tool_name] = enabled
    _save_prefs(prefs)
    return {"status": "success", "tool": tool_name, "enabled": enabled}

@router.get("/categories")
async def list_categories():
    """List all tool categories and their enabled status."""
    registry = get_tool_registry()
    prefs = _load_prefs()
    
    categories = set()
    for t in registry.list_tools():
        categories.add(getattr(t, "category", None) or "general")
        
    return {
        "categories": [
            {
                "name": cat,
                "enabled": prefs.get("enabled_categories", {}).get(cat, True)
            }
            for cat in sorted(categories)
        ]
    }

@router.post("/categories/{category_name}/toggle")
async def toggle_category(category_name: str, enabled: bool):
    """Enable or disable all tools in a category."""
    prefs = _load_prefs()
    if "enabled_categories" not in prefs:
        prefs["enabled_categories"] = {}
    prefs["enabled_categories"][category_name] = enabled
    _save_prefs(prefs)
    return {"status": "success", "category": category_name, "enabled": enabled}
