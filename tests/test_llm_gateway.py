"""Unit tests for LLM Gateway, worker management, and failover (P7)."""

import time
from unittest.mock import patch
import pytest

from app.llm.workers import (
    load_workers,
    get_public_workers,
    mark_worker_error,
    mark_worker_used,
)
from tests.test_agent_scenarios import test_t6_worker_failover


def test_public_workers_mask_secrets():
    """get_public_workers() masks API keys and sets status based on cooldown."""
    sample_workers = [
        {
            "worker_id": "w1",
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "api_key": "gsk_secretkey12345678",
            "enabled": True,
            "priority": 10,
            "cooldown_until": 0,
        },
        {
            "worker_id": "w2",
            "provider": "groq",
            "model": "openai/gpt-oss-20b",
            "api_key": "gsk_secretkey87654321",
            "enabled": True,
            "priority": 5,
            "cooldown_until": time.time() + 300,
        },
    ]

    with patch("app.llm.workers.load_workers", return_value=sample_workers):
        public = get_public_workers()
        assert len(public) == 2
        # w1 is healthy and highest priority
        assert public[0]["worker_id"] == "w1"
        assert public[0]["status"] == "HEALTHY"
        assert "gsk_secretkey" not in public[0].get("api_key", "")
        assert public[0]["api_key_hint"].startswith("...")

        # w2 is in cooldown
        assert public[1]["worker_id"] == "w2"
        assert public[1]["status"] == "COOLDOWN"


def test_failover_preserves_state():
    """Failover from Worker A to Worker B continues from existing state without duplicating work."""
    test_t6_worker_failover()

