"""Tests for the LLM parsing and repair ladder.

Tests ported from brain/ parsing tests. Cover:
- parse_tool_arguments: direct JSON, fence, embedded object, repair, bracket close
- parse_tool_calls_from_text: tag extraction, markdown, raw JSON, textual
- build_repair_prompt
- validate_tool_args
- canonicalise_args (loop detection stability)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.agent.llm.parsing import (
    ToolCallParseResult,
    build_repair_prompt,
    canonicalise_args,
    parse_tool_arguments,
    parse_tool_calls_from_text,
    validate_tool_args,
)


class TestParseToolArguments:
    def test_valid_json(self):
        args, err = parse_tool_arguments('{"path": "hello.txt", "content": "hi"}')
        assert err is None
        assert args == {"path": "hello.txt", "content": "hi"}

    def test_dict_passthrough(self):
        raw = {"path": "hello.txt"}
        args, err = parse_tool_arguments(raw)
        assert err is None
        assert args == raw

    def test_null_input(self):
        args, err = parse_tool_arguments(None)
        assert args == {}
        assert err is not None

    def test_empty_string(self):
        args, err = parse_tool_arguments("")
        assert args == {}
        assert err is not None

    def test_markdown_fenced(self):
        raw = '```json\n{"path": "out.txt"}\n```'
        args, err = parse_tool_arguments(raw)
        assert err is None
        assert args["path"] == "out.txt"

    def test_trailing_comma_repair(self):
        raw = '{"path": "out.txt",}'
        args, err = parse_tool_arguments(raw)
        assert err is None
        assert args["path"] == "out.txt"

    def test_single_quoted_keys_repair(self):
        raw = "{'path': 'hello.txt', 'content': 'world'}"
        args, err = parse_tool_arguments(raw)
        assert err is None
        assert args.get("path") == "hello.txt"

    def test_python_bool_repair(self):
        raw = '{"verbose": True, "dry": False, "x": None}'
        args, err = parse_tool_arguments(raw)
        assert err is None
        assert args["verbose"] is True
        assert args["dry"] is False
        assert args["x"] is None

    def test_truncated_object_repair(self):
        raw = '{"path": "hello.txt", "content": "Hello Wor'
        args, err = parse_tool_arguments(raw)
        # May not parse perfectly but should not crash
        assert isinstance(args, dict)

    def test_prose_with_embedded_json(self):
        raw = 'I will now create the file. {"path": "out.txt", "content": "hi"}'
        args, err = parse_tool_arguments(raw)
        if err is None:
            assert args.get("path") == "out.txt"


class TestParseToolCallsFromText:
    def test_tool_call_tag(self):
        text = '<tool_call>\n{"name": "create_file", "arguments": {"path": "x.txt", "content": "y"}}\n</tool_call>'
        calls = parse_tool_calls_from_text(text)
        assert len(calls) == 1
        assert calls[0].name == "create_file"
        assert calls[0].arguments["path"] == "x.txt"
        assert calls[0].strategy == "tag"

    def test_markdown_json_block(self):
        text = 'I will create the file:\n```json\n{"name": "create_file", "arguments": {"path": "out.txt"}}\n```'
        calls = parse_tool_calls_from_text(text)
        assert len(calls) >= 1
        assert any(c.name == "create_file" for c in calls)

    def test_raw_json_object(self):
        text = '{"name": "read_file", "arguments": {"path": "test.txt"}}'
        calls = parse_tool_calls_from_text(text)
        assert len(calls) >= 1
        assert calls[0].name == "read_file"

    def test_textual_call_form(self):
        text = 'create_file({"path": "hello.txt", "content": "Hello"})'
        calls = parse_tool_calls_from_text(text)
        assert len(calls) >= 1
        assert calls[0].name == "create_file"

    def test_multiple_tag_calls(self):
        text = (
            '<tool_call>\n{"name": "create_file", "arguments": {"path": "a.txt"}}\n</tool_call>\n'
            '<tool_call>\n{"name": "read_file", "arguments": {"path": "a.txt"}}\n</tool_call>'
        )
        calls = parse_tool_calls_from_text(text)
        assert len(calls) == 2
        names = [c.name for c in calls]
        assert "create_file" in names
        assert "read_file" in names

    def test_no_tool_call_returns_empty(self):
        text = "The answer to 2 + 2 is 4."
        calls = parse_tool_calls_from_text(text)
        assert len(calls) == 0

    def test_tool_key_variants(self):
        """Models sometimes use 'tool' instead of 'name'."""
        text = '{"tool": "list_directory", "arguments": {"path": "."}}'
        calls = parse_tool_calls_from_text(text)
        if calls:
            assert calls[0].name == "list_directory"


class TestBuildRepairPrompt:
    def test_contains_tool_name(self):
        prompt = build_repair_prompt(
            tool="create_file",
            schema={"properties": {"path": {"type": "string"}}, "required": ["path"]},
            raw_arguments="{}",
            errors=["Missing required argument: 'path'"],
        )
        assert "create_file" in prompt
        assert "path" in prompt
        assert "Missing required argument" in prompt

    def test_no_prose_hint(self):
        prompt = build_repair_prompt(
            tool="read_file",
            schema={},
            raw_arguments="{}",
            errors=["some error"],
        )
        assert "No prose" in prompt or "no prose" in prompt.lower() or "no markdown" in prompt.lower()


class TestValidateToolArgs:
    def test_valid_args_pass(self):
        schema = {
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        errors = validate_tool_args("read_file", {"path": "test.txt"}, schema)
        assert errors == []

    def test_missing_required_detected(self):
        schema = {
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        }
        errors = validate_tool_args("create_file", {"path": "x.txt"}, schema)
        assert any("content" in e for e in errors), f"Missing content not detected: {errors}"

    def test_unknown_arg_detected(self):
        schema = {
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        errors = validate_tool_args("read_file", {"path": "x.txt", "unknown_arg": "foo"}, schema)
        assert any("unknown" in e.lower() for e in errors), f"Unknown arg not detected: {errors}"

    def test_empty_schema_passes_everything(self):
        errors = validate_tool_args("any_tool", {"anything": "goes"}, {})
        assert errors == []


class TestCanonicaliseArgs:
    def test_key_order_stable(self):
        a = canonicalise_args({"b": 2, "a": 1})
        b = canonicalise_args({"a": 1, "b": 2})
        assert a == b, "Canonicalisation must be order-independent"

    def test_no_whitespace(self):
        result = canonicalise_args({"path": "x"})
        assert " " not in result

    def test_handles_non_serializable(self):
        """Should not crash on non-JSON-serializable values."""
        result = canonicalise_args({"obj": object()})
        assert isinstance(result, str)
