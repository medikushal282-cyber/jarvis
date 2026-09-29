import pytest
import time
import json
import os
from unittest.mock import patch, MagicMock

from app.llm.router import call_llm
from app.llm.workers import load_workers, mark_worker_error

@pytest.fixture
def fake_workers():
    # Setup some fake workers
    w = [
        {"worker_id": "w1", "provider": "groq", "model": "fake/model-1", "enabled": True},
        {"worker_id": "w2", "provider": "groq", "model": "fake/model-2", "enabled": True},
    ]
    return w

def test_router_normal_request(fake_workers):
    with patch("app.llm.workers.load_workers", return_value=fake_workers):
        with patch("app.llm.router.call_litellm", return_value="Success response"):
            with patch("app.llm.workers.mark_worker_used") as mock_used:
                response, _ = call_llm(system="sys", user="user")
                assert "Success response" in response
                mock_used.assert_called_with("w1")

def test_router_worker_a_429_then_worker_b(fake_workers):
    with patch("app.llm.workers.load_workers", side_effect=[
        fake_workers, # initial load
        [{"worker_id": "w1", "provider": "groq", "model": "fake/model-1", "enabled": True, "cooldown_until": time.time() + 30},
         {"worker_id": "w2", "provider": "groq", "model": "fake/model-2", "enabled": True}], # reloaded after 429
    ]):
        class RateLimitError(Exception):
            pass
        
        # litellm will fail first time, succeed second time
        mock_litellm = MagicMock(side_effect=[RateLimitError("429 rate_limit try again in 10s"), "Worker B Success"])
        with patch("app.llm.router.call_litellm", mock_litellm):
            with patch("app.llm.workers.mark_worker_error") as mock_err:
                response, _ = call_llm(system="sys", user="user")
                assert "Worker B Success" in response
                # Ensure mark_worker_error was called with cooldown_s=12 (10+2)
                mock_err.assert_called_with("w1", "429 rate_limit try again in 10s", 12)

def test_router_worker_a_timeout_then_worker_b(fake_workers):
    with patch("app.llm.workers.load_workers", side_effect=[
        fake_workers,
        [{"worker_id": "w1", "provider": "groq", "model": "fake/model-1", "enabled": True, "cooldown_until": time.time() + 60},
         {"worker_id": "w2", "provider": "groq", "model": "fake/model-2", "enabled": True}],
    ]):
        mock_litellm = MagicMock(side_effect=[Exception("connection timeout"), "Worker B Success"])
        with patch("app.llm.router.call_litellm", mock_litellm):
            with patch("app.llm.workers.mark_worker_error") as mock_err:
                response, _ = call_llm(system="sys", user="user")
                assert "Worker B Success" in response
                # standard timeout gives 60s cooldown usually or treated as rate limit
                mock_err.assert_called()

def test_router_respect_retry_after(fake_workers):
    # Only 1 worker available
    single_worker = [{"worker_id": "w1", "provider": "groq", "model": "fake", "enabled": True}]
    
    with patch("app.llm.workers.load_workers", side_effect=[
        single_worker, # initial
        [{"worker_id": "w1", "provider": "groq", "model": "fake", "enabled": True, "cooldown_until": time.time() + 1}], # wait 1 sec
        [{"worker_id": "w1", "provider": "groq", "model": "fake", "enabled": True, "cooldown_until": 0}], # recovered
    ]):
        mock_litellm = MagicMock(side_effect=[Exception("429 rate_limit"), "Recovered Success"])
        with patch("app.llm.router.call_litellm", mock_litellm):
            with patch("app.llm.router.time.sleep") as mock_sleep:
                response, _ = call_llm(system="sys", user="user")
                assert "Recovered Success" in response
                assert mock_sleep.called

def test_router_no_healthy_workers_clean_failure(fake_workers):
    # All workers immediately fail with hard error
    with patch("app.llm.workers.load_workers", side_effect=[
        fake_workers,
        [{"worker_id": "w1", "cooldown_until": time.time() + 60}, {"worker_id": "w2", "cooldown_until": 0}],
        [{"worker_id": "w1", "cooldown_until": time.time() + 60}, {"worker_id": "w2", "cooldown_until": time.time() + 60}],
    ]):
        mock_litellm = MagicMock(side_effect=[Exception("hard crash"), Exception("hard crash")])
        with patch("app.llm.router.call_litellm", mock_litellm):
            with pytest.raises(Exception, match="unavailable"):
                call_llm(system="sys", user="user")

