"""JSON schema derivation for plain Python tool functions."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from copy import deepcopy
from typing import Annotated, Any, Literal, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel
from pydantic.fields import FieldInfo

UnionType = type(str | int)


def schema_for_type(annotation: Any) -> dict[str, Any]:
    if annotation in (inspect.Signature.empty, Any):
        return {}
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        schema = schema_for_type(args[0])
        for metadata in args[1:]:
            if not isinstance(metadata, FieldInfo):
                continue
            if metadata.description:
                schema["description"] = metadata.description
            if metadata.examples:
                schema["examples"] = list(metadata.examples)
            if (minimum := getattr(metadata, "ge", None)) is not None:
                schema["minimum"] = minimum
            if (maximum := getattr(metadata, "le", None)) is not None:
                schema["maximum"] = maximum
        return schema
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is type(None):
        return {"type": "null"}
    if origin in (Union, UnionType):
        return {"anyOf": [schema_for_type(arg) for arg in args]}
    if origin is Literal:
        values = list(args)
        schema = {"enum": values}
        if values:
            if all(isinstance(value, str) for value in values):
                schema["type"] = "string"
            elif all(isinstance(value, bool) for value in values):
                schema["type"] = "boolean"
            elif all(isinstance(value, int) for value in values):
                schema["type"] = "integer"
            elif all(isinstance(value, (int, float)) for value in values):
                schema["type"] = "number"
        return schema
    if origin in (list, tuple, set):
        return {
            "type": "array",
            "items": schema_for_type(args[0] if args else Any),
        }
    if origin is dict:
        return {"type": "object"}
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return annotation.model_json_schema()
    return {}


def input_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:  # noqa: BLE001 - unresolved refs should not hide the tool.
        hints = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        schema = schema_for_type(hints.get(name, parameter.annotation))
        if parameter.default is inspect.Signature.empty:
            required.append(name)
        else:
            schema = {**schema, "default": parameter.default}
        properties[name] = schema
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


def invocation_schema(strict_schema: dict[str, Any]) -> dict[str, Any]:
    """Restore backend omission semantics hidden by an SDK strict schema.

    The Agents SDK marks every object property as required for OpenAI strict
    structured outputs, even when its Pydantic invocation model applies a
    Python default. The Explorer calls that invocation model directly, so its
    form needs the ordinary JSON Schema meaning of ``required`` instead.

    Args:
        strict_schema: Model-facing JSON Schema emitted by the Agents SDK.

    Returns:
        A recursive copy whose required lists exclude defaulted and nullable
        properties while preserving every validation constraint.
    """

    schema = deepcopy(strict_schema)
    for container_name in ("$defs", "definitions", "properties"):
        container = schema.get(container_name)
        if isinstance(container, dict):
            schema[container_name] = {
                name: invocation_schema(value)
                for name, value in container.items()
            }

    items = schema.get("items")
    if isinstance(items, dict):
        schema["items"] = invocation_schema(items)
    for variants_name in ("anyOf", "oneOf", "allOf"):
        variants = schema.get(variants_name)
        if isinstance(variants, list):
            schema[variants_name] = [
                invocation_schema(variant)
                if isinstance(variant, dict)
                else variant
                for variant in variants
            ]

    properties = schema.get("properties")
    required = schema.get("required")
    if isinstance(properties, dict) and isinstance(required, list):
        required = [
            name
            for name in required
            if name not in properties
            or (
                "default" not in properties[name]
                and not any(
                    isinstance(variant, dict) and variant.get("type") == "null"
                    for variant in properties[name].get("anyOf", [])
                )
            )
        ]
        if required:
            schema["required"] = required
        else:
            schema.pop("required", None)

    return schema


def output_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:  # noqa: BLE001
        hints = {}
    return schema_for_type(
        hints.get("return", inspect.signature(fn).return_annotation)
    )


__all__ = ["input_schema", "invocation_schema", "output_schema", "schema_for_type"]
