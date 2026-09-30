"""OpenAI Responses API continuation support for the local tuning console."""

from __future__ import annotations

from collections.abc import Mapping
import json
import time
from typing import Any


def run_response_continuation(
    response_id: str,
    message: str,
    *,
    model: str | None = None,
    instructions: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Retrieve a stored response and branch it with one user turn.

    This powers the developer-only response tuning page.  The branch uses the
    Responses API's ``previous_response_id`` state rather than replaying the
    parent conversation in the browser or application process.

    Args:
        response_id: Stored OpenAI response that supplies prior state.
        message: New user input for the branch.
        model: Optional model override; the parent's model is used otherwise.
        instructions: Optional replacement instructions for the new response.
        temperature: Optional sampling temperature.
        max_output_tokens: Optional output-token cap.

    Returns:
        A browser-safe record of the retrieved parent, request, response, and
        diagnostics.  API failures are represented in this record so prompt
        tuning users can inspect them without losing the parent details.
    """
    from openai import OpenAI

    client = OpenAI()
    started_at = time.perf_counter()
    try:
        prior_response = client.responses.retrieve(response_id)
    except Exception as error:  # noqa: BLE001 - API diagnostics belong in the console.
        return failure_result(
            response_id,
            elapsed_ms(started_at),
            "retrieve",
            error,
        )

    prior = api_value(prior_response)
    input_items, input_items_error = retrieve_input_items(client, response_id)
    selected_model = model or getattr(prior_response, "model", None)
    if not selected_model:
        return {
            "ok": False,
            "prior_response": prior,
            "prior_input_items": input_items,
            "prior_input_items_error": input_items_error,
            "request": None,
            "response": None,
            "latency_ms": elapsed_ms(started_at),
            "error": {
                "stage": "prepare",
                "type": "ValueError",
                "message": "The referenced response does not include a model; enter a model override.",
            },
        }

    request: dict[str, Any] = {
        "model": selected_model,
        "previous_response_id": response_id,
        "input": [{"role": "user", "content": message}],
        # A tuning branch needs to remain retrievable for follow-up experiments.
        "store": True,
    }
    if instructions is not None:
        request["instructions"] = instructions
    if temperature is not None:
        request["temperature"] = temperature
    if max_output_tokens is not None:
        request["max_output_tokens"] = max_output_tokens

    try:
        response = client.responses.create(**request)
    except Exception as error:  # noqa: BLE001 - surface remote validation to the UI.
        return {
            "ok": False,
            "prior_response": prior,
            "prior_input_items": input_items,
            "prior_input_items_error": input_items_error,
            "request": request,
            "response": None,
            "latency_ms": elapsed_ms(started_at),
            "error": api_error("create", error),
        }

    response_data = api_value(response)
    return {
        "ok": True,
        "prior_response": prior,
        "prior_input_items": input_items,
        "prior_input_items_error": input_items_error,
        "request": request,
        "response_id": getattr(response, "id", None),
        "assistant_output": getattr(response, "output_text", ""),
        "output_items": response_data.get("output", []),
        "usage": response_data.get("usage"),
        "response": response_data,
        "latency_ms": elapsed_ms(started_at),
        "error": None,
    }


def retrieve_input_items(client: Any, response_id: str) -> tuple[Any, str | None]:
    """List stored parent input items when the installed API supports it.

    The parent response record does not always contain its original input.
    This optional inspection call improves debugging while never preventing a
    valid continuation when input-item retrieval is unavailable.
    """
    try:
        input_items = client.responses.input_items.list(
            response_id,
            limit=100,
            order="asc",
        )
        data = api_value(input_items)
        return data.get("data", data), None
    except Exception as error:  # noqa: BLE001 - retrieval is diagnostic only.
        return None, f"{type(error).__name__}: {error}"


def api_value(value: Any) -> dict[str, Any]:
    """Convert SDK objects into JSON-compatible dictionaries for the browser."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    return json.loads(json.dumps(value, default=str))


def elapsed_ms(started_at: float) -> int:
    """Return rounded elapsed time for a tuning request."""
    return round((time.perf_counter() - started_at) * 1000)


def api_error(stage: str, error: Exception) -> dict[str, str]:
    """Return concise API failure diagnostics without exposing credentials."""
    return {
        "stage": stage,
        "type": type(error).__name__,
        "message": str(error),
    }


def failure_result(
    response_id: str,
    latency_ms: int,
    stage: str,
    error: Exception,
) -> dict[str, Any]:
    """Build the result shape used when parent retrieval fails."""
    return {
        "ok": False,
        "prior_response_id": response_id,
        "prior_response": None,
        "prior_input_items": None,
        "prior_input_items_error": None,
        "request": None,
        "response": None,
        "latency_ms": latency_ms,
        "error": api_error(stage, error),
    }
