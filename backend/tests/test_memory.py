import os
import json
import pytest
import shutil
import tempfile
from typing import Dict, Any

from app.memory.context_builder import ContextBuilder
from app.memory.hindsight.client import HindsightClient
from app.memory.hindsight.adapter import HindsightAdapter
from app.memory.okf.manager import OKFManager
from app.memory.reflection import MemoryReflector
from app.memory.extractor import MemoryExtractor

@pytest.fixture
def temp_memory_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)

@pytest.fixture
def memory_components(temp_memory_dir):
    hindsight_client = HindsightClient(storage_dir=os.path.join(temp_memory_dir, "hindsight"))
    hindsight_adapter = HindsightAdapter(client=hindsight_client)
    okf_manager = OKFManager(storage_dir=os.path.join(temp_memory_dir, "okf"))
    context_builder = ContextBuilder(hindsight=hindsight_adapter, okf=okf_manager)
    reflector = MemoryReflector(hindsight=hindsight_adapter, okf=okf_manager)
    return hindsight_adapter, okf_manager, context_builder, reflector

# A. EXPERIENCE STORAGE & B. SEMANTIC RECALL
def test_experience_storage_and_recall(memory_components):
    h_adapter, okf, builder, _ = memory_components
    
    # Store experience
    h_adapter.record_execution_experience(
        user_id="user_1",
        objective="Create a compact technical report",
        summary="Task: Create a compact technical report\nOutcome: SUCCESS\nProduced Artifacts: report.pdf",
        status="success"
    )
    
    # Semantic recall
    recalled = h_adapter.recall_relevant_experiences(
        user_id="user_1",
        objective="Generate a technical report",
        limit=5
    )
    
    assert len(recalled) == 1
    assert "report.pdf" in recalled[0]["content"]

# C. RELEVANCE & D. USER SCOPING
def test_scoping_and_relevance(memory_components):
    h_adapter, okf, builder, _ = memory_components
    
    h_adapter.record_execution_experience("user_A", "Make a cake", "Task: cake\nOutcome: SUCCESS", "success")
    h_adapter.record_execution_experience("user_B", "Make a cake", "Task: cake for B\nOutcome: SUCCESS", "success")
    
    # User A should not see User B's cake
    recalled = h_adapter.recall_relevant_experiences("user_A", "Make a cake")
    assert len(recalled) == 1
    assert "cake for B" not in recalled[0]["content"]

# E. PROJECT SCOPING
def test_project_scoping(memory_components):
    h_adapter, okf, builder, _ = memory_components
    
    okf.update_project_knowledge("user_1", "proj_1", "overview", "Project 1 uses FastAPI")
    okf.update_project_knowledge("user_1", "proj_2", "overview", "Project 2 uses Django")
    
    context = builder.build_context("user_1", "Fix bug", project_id="proj_1")
    assert "FastAPI" in context["project_knowledge"]
    assert "Django" not in context["project_knowledge"]

# K & L. HINDSIGHT / OKF GRACEFUL FAILURE
def test_graceful_failure(memory_components, monkeypatch):
    h_adapter, okf, builder, _ = memory_components
    
    # Simulate DB failure
    def mock_fail(*args, **kwargs):
        raise Exception("DB Connection Lost")
        
    monkeypatch.setattr(okf, "get_user_knowledge", mock_fail)
    monkeypatch.setattr(h_adapter, "recall_relevant_experiences", mock_fail)
    
    # Should not raise exception
    context = builder.build_context("user_1", "Do something")
    assert context["user_preferences"] == ""
    assert context["relevant_experiences"] == []

# J. TOKEN BUDGET TRUNCATION
def test_token_budget(memory_components):
    h_adapter, okf, builder, _ = memory_components
    
    okf.update_user_knowledge("user_1", "preferences", "A" * 5000) # 5000 chars
    
    # Max tokens = 100 -> ~400 chars
    context = builder.build_context("user_1", "Do something", max_tokens=100)
    
    prefs = context["user_preferences"]
    assert len(prefs) <= 450 # 400 + length of "...[TRUNCATED]"
    assert prefs.endswith("...[TRUNCATED]")

# M. SENSITIVE DATA REDACTION
def test_sensitive_data_redaction():
    state = {
        "status": "success",
        "error": "Failed to authenticate with token Bearer abcdefghijklmnopqrstuvwxyz123456",
        "tool_calls": [
            {
                "status": "failed",
                "tool": "login",
                "reason": "API_KEY=gsk_secretkey1234567890 was rejected"
            }
        ]
    }
    
    summary = MemoryExtractor.extract_experience("Use token Bearer abcdefghijklmnopqrstuvwxyz123456", state)
    assert "abcdefghijklmnopqrstuvwxyz123456" not in summary
    assert "Bearer [REDACTED]" in summary
    assert "gsk_secretkey1234567890" not in summary
    assert "API_KEY=[REDACTED]" in summary

# H & I. KNOWLEDGE PROMOTION (Reflection)
def test_reflection_promotion(memory_components, monkeypatch):
    h_adapter, okf, builder, reflector = memory_components
    
    # Mock call_llm to simulate LLM returning a JSON array of facts
    def mock_call_llm(system, user, model, provider):
        return '["User prefers PDF output"]', None
        
    monkeypatch.setattr("app.memory.reflection.call_llm", mock_call_llm)
    
    # Record some experiences
    h_adapter.record_execution_experience("user_1", "Generate report", "User requested PDF format", "success")
    h_adapter.record_execution_experience("user_1", "Generate report 2", "User again requested PDF", "success")
    
    # Trigger reflection
    reflector.reflect("user_1", "Generate report")
    
    # Verify OKF was updated
    prefs = okf.get_user_knowledge("user_1", "preferences").get("content", "")
    assert "User prefers PDF output" in prefs
