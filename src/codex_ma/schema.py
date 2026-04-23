from __future__ import annotations

from pathlib import Path
from typing import Any
import json


class SchemaValidationError(ValueError):
    pass


def load_schema(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate(instance: Any, schema: dict[str, Any]) -> None:
    _validate_node(instance, schema, "$", schema)


def _resolve_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema["$ref"]
    if not ref.startswith("#/"):
        raise SchemaValidationError(f"Unsupported $ref: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    if not isinstance(node, dict):
        raise SchemaValidationError(f"Invalid $ref target: {ref}")
    return node


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    raise SchemaValidationError(f"Unsupported schema type: {expected}")


def _validate_node(instance: Any, schema: dict[str, Any], path: str, root: dict[str, Any]) -> None:
    if "$ref" in schema:
        resolved = _resolve_ref(schema, root)
        _validate_node(instance, resolved, path, root)
        return
    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaValidationError(f"{path}: expected one of {schema['enum']}, got {instance!r}")
    if "type" in schema:
        expected_types = schema["type"]
        if isinstance(expected_types, str):
            expected_types = [expected_types]
        if not any(_type_matches(instance, expected) for expected in expected_types):
            raise SchemaValidationError(f"{path}: expected type {expected_types}, got {type(instance).__name__}")
    if "minimum" in schema and isinstance(instance, (int, float)) and instance < schema["minimum"]:
        raise SchemaValidationError(f"{path}: expected minimum {schema['minimum']}, got {instance}")
    if isinstance(instance, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                raise SchemaValidationError(f"{path}: missing required key {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties", True) is False:
            unknown = [key for key in instance if key not in properties]
            if unknown:
                raise SchemaValidationError(f"{path}: unexpected keys {unknown}")
        for key, value in instance.items():
            if key in properties:
                _validate_node(value, properties[key], f"{path}.{key}", root)
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            _validate_node(item, schema["items"], f"{path}[{index}]", root)
