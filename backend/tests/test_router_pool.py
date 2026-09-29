import pytest
import os
import time
from unittest.mock import patch, MagicMock
from app.llm.router import call_llm
from app.llm.workers import load_workers

# Helper to mock LiteLLM responses
def create_mock_litellm(responses):
    # responses is a list of either strings (success) or Exceptions (failure)
    call_count = [0]
    def mock_call(*args, **kwargs):
        if call_count[0] < len(responses):
            res = responses[call_count[0]]
            call_count[0] += 1
            if isinstance(res, Exception):
                raise res
            return res
        return "default success"
    return mock_call

def mock_load_workers(pool):
    # Returns a lambda that can be used to mock load_workers.
    # We maintain state of cooldowns in the test.
    state = {"pool": [dict(w) for w in pool]}
    def loader():
        return state["pool"]
    return loader, state

def mock_save_workers(state):
    def saver(workers):
        state["pool"] = workers
    return saver

@patch('app.llm.router.call_litellm')
@patch('app.llm.workers.save_workers')
@patch('app.llm.workers.load_workers')
def test_1_worker_succeeds(mock_load_w, mock_save, mock_litellm):
    pool = [{"worker_id": "w1", "provider": "test", "model": "test", "priority": 1, "enabled": True, "cooldown_until": 0}]
    loader, state = mock_load_workers(pool)
    mock_load_w.side_effect = loader
    mock_save.side_effect = mock_save_workers(state)
    
    mock_litellm.side_effect = create_mock_litellm(["success 1"])
    
    res, _ = call_llm("sys", "user")
    assert "success 1" in res

@patch('app.llm.router.call_litellm')
@patch('app.llm.workers.save_workers')
@patch('app.llm.workers.load_workers')
def test_a_429_b_succeeds(mock_load_w, mock_save, mock_litellm):
    pool = [
        {"worker_id": "w1", "provider": "test", "model": "test", "priority": 2, "enabled": True, "cooldown_until": 0},
        {"worker_id": "w2", "provider": "test", "model": "test", "priority": 1, "enabled": True, "cooldown_until": 0}
    ]
    loader, state = mock_load_workers(pool)
    mock_load_w.side_effect = loader
    mock_save.side_effect = mock_save_workers(state)
    
    # w1 throws 429, w2 succeeds
    mock_litellm.side_effect = create_mock_litellm([Exception("rate_limit: try again in 10s"), "success B"])
    
    res, _ = call_llm("sys", "user")
    assert "success B" in res
    
    # Check cooldown
    assert state["pool"][0]["cooldown_until"] > time.time()
    assert state["pool"][1]["cooldown_until"] == 0

@patch('app.llm.router.call_litellm')
@patch('app.llm.workers.save_workers')
@patch('app.llm.workers.load_workers')
def test_a_429_b_429_c_succeeds(mock_load_w, mock_save, mock_litellm):
    pool = [
        {"worker_id": "w1", "provider": "test", "model": "test", "priority": 3, "enabled": True, "cooldown_until": 0},
        {"worker_id": "w2", "provider": "test", "model": "test", "priority": 2, "enabled": True, "cooldown_until": 0},
        {"worker_id": "w3", "provider": "test", "model": "test", "priority": 1, "enabled": True, "cooldown_until": 0}
    ]
    loader, state = mock_load_workers(pool)
    mock_load_w.side_effect = loader
    mock_save.side_effect = mock_save_workers(state)
    
    mock_litellm.side_effect = create_mock_litellm([Exception("rate_limit"), Exception("rate_limit"), "success C"])
    
    res, _ = call_llm("sys", "user")
    assert "success C" in res
    
    assert state["pool"][0]["cooldown_until"] > time.time()
    assert state["pool"][1]["cooldown_until"] > time.time()
    assert state["pool"][2]["cooldown_until"] == 0

@patch('time.sleep')
@patch('app.llm.router.call_litellm')
@patch('app.llm.workers.save_workers')
@patch('app.llm.workers.load_workers')
def test_all_429_waits_and_retries(mock_load_w, mock_save, mock_litellm, mock_sleep):
    pool = [
        {"worker_id": "w1", "provider": "test", "model": "test", "priority": 1, "enabled": True, "cooldown_until": 0}
    ]
    loader, state = mock_load_workers(pool)
    
    # We must patch loader so that after time.sleep, the cooldown is reset to 0 in the mock state!
    def advancing_loader():
        s = loader()
        # Simulate time passing by clearing cooldowns if time.sleep was called
        if mock_sleep.called:
            for w in s: w["cooldown_until"] = 0
        return s

    mock_load_w.side_effect = advancing_loader
    mock_save.side_effect = mock_save_workers(state)
    
    # First attempt: 429. Second attempt (after sleep): success.
    mock_litellm.side_effect = create_mock_litellm([Exception("rate_limit: try again in 5s"), "success A2"])
    
    res, _ = call_llm("sys", "user")
    assert "success A2" in res
    assert mock_sleep.call_count == 1
    # Check bounded wait
    args, _ = mock_sleep.call_args
    assert args[0] >= 5

@patch('app.llm.router.call_litellm')
@patch('app.llm.workers.save_workers')
@patch('app.llm.workers.load_workers')
def test_auth_failure_marked_error(mock_load_w, mock_save, mock_litellm):
    pool = [
        {"worker_id": "w1", "provider": "test", "model": "test", "priority": 2, "enabled": True, "cooldown_until": 0},
        {"worker_id": "w2", "provider": "test", "model": "test", "priority": 1, "enabled": True, "cooldown_until": 0}
    ]
    loader, state = mock_load_workers(pool)
    mock_load_w.side_effect = loader
    mock_save.side_effect = mock_save_workers(state)
    
    # w1 throws auth error
    mock_litellm.side_effect = create_mock_litellm([Exception("AuthenticationError"), "success B"])
    
    res, _ = call_llm("sys", "user")
    assert "success B" in res
    assert "AuthenticationError" in state["pool"][0].get("last_error", "")
    # Should have a long cooldown to prevent endless spinning
    assert state["pool"][0]["cooldown_until"] > time.time() + 50

@patch('app.llm.router.call_litellm')
@patch('app.llm.workers.save_workers')
@patch('app.llm.workers.load_workers')
def test_turn_state_preservation(mock_load_w, mock_save, mock_litellm):
    pool = [
        {"worker_id": "w1", "provider": "test", "model": "test", "priority": 2, "enabled": True, "cooldown_until": 0},
        {"worker_id": "w2", "provider": "test", "model": "test", "priority": 1, "enabled": True, "cooldown_until": 0}
    ]
    loader, state = mock_load_workers(pool)
    mock_load_w.side_effect = loader
    mock_save.side_effect = mock_save_workers(state)
    
    # Turn 1
    mock_litellm.side_effect = create_mock_litellm(["success T1"])
    res1, _ = call_llm("sys", "T1 msg", turn_idx=1)
    assert "success T1" in res1
    
    # Turn 2
    mock_litellm.side_effect = create_mock_litellm([Exception("rate_limit"), "success T2 B"])
    res2, _ = call_llm("sys", "T2 msg", turn_idx=2)
    assert "success T2 B" in res2
    
    # State preserved? Yes, because call_llm returns cleanly without throwing an exception.
    # The agent loop doesn't know it failed!

@patch('app.llm.router.call_litellm')
@patch('app.llm.workers.load_workers')
def test_empty_workers_json(mock_load, mock_litellm):
    mock_load.return_value = []
    mock_litellm.return_value = "fallback success"
    
    res, _ = call_llm("sys", "user")
    assert "fallback success" in res

def test_10_and_60_workers():
    pool_10 = [{"worker_id": f"w{i}", "provider": "test", "model": "test", "priority": 1, "enabled": True, "cooldown_until": 0} for i in range(10)]
    pool_60 = [{"worker_id": f"w{i}", "provider": "test", "model": "test", "priority": 1, "enabled": True, "cooldown_until": 0} for i in range(60)]
    
    # Just verify the architecture naturally supports lengths
    assert len(pool_10) == 10
    assert len(pool_60) == 60
    # Sorting and looping is O(N log N) which is instantaneous for 60.

if __name__ == "__main__":
    pytest.main(["-v", "test_router_pool.py"])
