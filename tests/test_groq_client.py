"""Offline tests for the Groq client."""
import json
import pytest
from brain.providers.llm.groq import GroqClient
from brain.contracts import LLMRequest, ParseStrategy
import httpx

class FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        
    def json(self):
        return self._json
        
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("Error", request=None, response=self)

class FakeTransport(httpx.BaseTransport):
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        
    def handle_request(self, request):
        self.calls.append(request)
        if not self.responses:
            return httpx.Response(200, json={})
        resp = self.responses.pop(0)
        return httpx.Response(resp.status_code, json=resp.json())

def test_groq_client_success():
    transport = FakeTransport([
        FakeResponse(200, {
            "choices": [{
                "message": {
                    "content": "Success response"
                },
                "finish_reason": "stop"
            }]
        })
    ])
    client = GroqClient({"api_key": "test_key"}, _client=httpx.Client(transport=transport))
    resp = client.complete(LLMRequest(messages=()))
    assert resp.content == "Success response"
    assert resp.finish_reason.name == "STOP"

def test_groq_client_429_retry():
    transport = FakeTransport([
        FakeResponse(429, {}),
        FakeResponse(200, {
            "choices": [{
                "message": {"content": "Finally succeeded"},
                "finish_reason": "stop"
            }]
        })
    ])
    client = GroqClient({"api_key": "test_key"}, _client=httpx.Client(transport=transport))
    resp = client.complete(LLMRequest(messages=()))
    assert resp.content == "Finally succeeded"
    assert len(transport.calls) == 2

def test_groq_client_tool_call():
    transport = FakeTransport([
        FakeResponse(200, {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "test_tool",
                            "arguments": '{"arg": "val"}'
                        }
                    }]
                },
                "finish_reason": "tool_calls"
            }]
        })
    ])
    client = GroqClient({"api_key": "test_key"}, _client=httpx.Client(transport=transport))
    resp = client.complete(LLMRequest(messages=()))
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "test_tool"
    assert resp.tool_calls[0].arguments == {"arg": "val"}

def test_groq_client_malformed_json_args():
    transport = FakeTransport([
        FakeResponse(200, {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "test_tool",
                            "arguments": '{"arg": "val'
                        }
                    }]
                },
                "finish_reason": "tool_calls"
            }]
        })
    ])
    client = GroqClient({"api_key": "test_key"}, _client=httpx.Client(transport=transport))
    resp = client.complete(LLMRequest(messages=()))
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].arguments == {} # Unparsed
    assert not resp.tool_calls[0].is_parsed

def test_groq_client_finish_reason_length():
    transport = FakeTransport([
        FakeResponse(200, {
            "choices": [{
                "message": {"content": "Truncated content"},
                "finish_reason": "length"
            }]
        })
    ])
    client = GroqClient({"api_key": "test_key"}, _client=httpx.Client(transport=transport))
    resp = client.complete(LLMRequest(messages=()))
    assert resp.finish_reason.name == "LENGTH"
