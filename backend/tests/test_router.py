import pytest
from unittest.mock import patch, MagicMock

from app.llm.router import call_llm

@pytest.fixture
def mock_load_workers():
    with patch("app.llm.workers.load_workers") as m:
        yield m

@pytest.fixture
def mock_call_litellm():
    with patch("app.llm.router.call_litellm") as m:
        yield m

@pytest.fixture
def mock_mark_worker_error():
    with patch("app.llm.workers.mark_worker_error") as m:
        yield m

@pytest.fixture
def mock_mark_worker_used():
    with patch("app.llm.workers.mark_worker_used") as m:
        yield m

@pytest.fixture
def mock_extract_thoughts():
    with patch("app.llm.router.extract_thoughts") as m:
        yield m

def test_router_worker_a_429_then_worker_b(mock_load_workers, mock_call_litellm, mock_extract_thoughts, mock_mark_worker_error, mock_mark_worker_used):
    worker_a = {"worker_id": "A", "model": "m-a", "provider": "p-a"}
    worker_b = {"worker_id": "B", "model": "m-b", "provider": "p-b"}
    
    mock_load_workers.side_effect = [
        [worker_a, worker_b], # Initial
        [worker_b], # After A is marked error, we assume load_workers returns only B or A is skipped
        [worker_b],
        [worker_b],
        [worker_b],
        [worker_b]
    ]
    
    mock_call_litellm.side_effect = [
        Exception("rate_limit reached for worker A"),
        MagicMock()
    ]
    
    mock_extract_thoughts.return_value = MagicMock(text="success from B")
    
    res = call_llm("sys", "usr", emit=lambda *args, **kwargs: None)
    assert res.text == "success from B"
    assert mock_call_litellm.call_count == 2
    mock_mark_worker_error.assert_called_once_with("A", "rate_limit reached for worker A", 30)

@patch("time.sleep")
def test_router_respect_retry_after(mock_sleep, mock_load_workers, mock_call_litellm, mock_extract_thoughts, mock_mark_worker_error, mock_mark_worker_used):
    worker_a = {"worker_id": "A", "model": "m-a", "provider": "p-a"}
    mock_load_workers.side_effect = [
        [worker_a],
        [worker_a],
        [worker_a],
        [worker_a],
        [worker_a],
        [worker_a]
    ]
    
    mock_call_litellm.side_effect = [
        Exception("Rate limit reached. Please try again in 12.5s."),
        MagicMock()
    ]
    
    mock_extract_thoughts.return_value = MagicMock(text="success from A")
    
    res = call_llm("sys", "usr", emit=lambda *args, **kwargs: None)
    assert res.text == "success from A"
    
    # 12.5 + 2 = 14
    mock_mark_worker_error.assert_called_once_with("A", "Rate limit reached. Please try again in 12.5s.", 14)

def test_router_no_healthy_workers_clean_failure(mock_load_workers):
    # No healthy workers initially should just use fallback, but let's say they fail
    worker_a = {"worker_id": "A", "model": "m-a", "provider": "p-a", "status": "cooldown", "cooldown_until": 9999999999}
    mock_load_workers.return_value = [worker_a]
    
    with pytest.raises(Exception, match="JARVIS couldn't complete task. No workers could be attempted"):
        call_llm("sys", "usr")
