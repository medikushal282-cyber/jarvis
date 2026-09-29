"""Argument validation against a tool's declared JSON Schema.

These error strings are not only for humans: they are pasted verbatim into the repair prompt
sent back to the model after a malformed call. That makes their *wording* part of the recovery
mechanism -- ``window_minutes: 5000 is greater than the maximum of 1440`` gives the model
something to act on, whereas ``invalid arguments`` gives it nothing and wastes an attempt.
"""

from __future__ import annotations

import json
from typing import Any

from brain.contracts import ToolSpec

_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _describe(value: Any) -> str:
    if value is None:
        return "null"
    return json.dumps(value, default=str)[:80]


def validate_args(spec: ToolSpec, args: dict[str, Any]) -> list[str]:
    """Return a list of problems with ``args``; an empty list means the call is valid."""
    if not isinstance(args, dict):
        return [f"arguments must be an object, got {type(args).__name__}"]

    schema = spec.parameters or {}
    props: dict[str, Any] = schema.get("properties", {}) or {}
    required: list[str] = list(schema.get("required", []) or [])
    errors: list[str] = []

    for field_name in required:
        if field_name not in args:
            errors.append(f"{field_name}: required field is missing")

    # Our tool schemas declare `additionalProperties: false`, so an unexpected key is a real
    # failure rather than harmless noise: it usually means the model invented a parameter name,
    # and its actual intent would otherwise be silently dropped.
    for field_name in sorted(set(args) - set(props)):
        allowed = ", ".join(sorted(props)) or "(none)"
        errors.append(f"{field_name}: unexpected field; allowed fields are {allowed}")

    for field_name, value in args.items():
        subschema = props.get(field_name)
        if isinstance(subschema, dict):
            errors.extend(_check_value(field_name, value, subschema))

    return errors


def _check_value(field: str, value: Any, schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")

    if value is None:
        return errors

    if expected:
        kinds = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, k) for k in kinds):
            # A type mismatch makes the remaining checks meaningless and often misleading.
            return [f"{field}: expected {' or '.join(kinds)}, got {_describe(value)}"]

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(repr(v) for v in schema["enum"])
        errors.append(f"{field}: {_describe(value)} is not one of {allowed}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{field}: {value} is less than the minimum of {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{field}: {value} is greater than the maximum of {schema['maximum']}")

    if isinstance(value, str) and "maxLength" in schema and len(value) > schema["maxLength"]:
        errors.append(
            f"{field}: {len(value)} characters exceeds the maximum of {schema['maxLength']}"
        )

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(_check_value(f"{field}[{index}]", item, schema["items"]))

    if isinstance(value, dict) and isinstance(schema.get("properties"), dict):
        for nested, nested_schema in schema["properties"].items():
            if nested in value:
                errors.extend(_check_value(f"{field}.{nested}", value[nested], nested_schema))
        for nested in schema.get("required", []) or []:
            if nested not in value:
                errors.append(f"{field}.{nested}: required field is missing")

    return errors


def _matches_type(value: Any, expected: str) -> bool:
    # bool is a subclass of int in Python, so it must be excluded explicitly for numeric types
    # or `True` would validate as an integer.
    if expected in {"integer", "number"} and isinstance(value, bool):
        return False
    kinds = _TYPE_CHECKS.get(expected)
    return isinstance(value, kinds) if kinds else True
