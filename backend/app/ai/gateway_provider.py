"""Internal API gateway provider for AI reasoning.

Sends prompts to a corporate LLM gateway and parses structured JSON responses.
Supports OpenAI-compatible and Anthropic-compatible API formats.
Includes retries, timeouts, and structured output parsing.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from app.ai.output_parser import OutputParserError, parse_ai_response
from app.ai.prompts import SYSTEM_PROMPT
from app.models.ai import AIProviderConfig, AIReasoningResult

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    """Raised when the gateway call fails after all retries."""


def call_gateway(
    prompt: str,
    config: AIProviderConfig,
) -> AIReasoningResult:
    """Send a prompt to the internal API gateway and return parsed results.

    Retries on transient failures (5xx, timeouts, connection errors).
    """
    if not config.gateway_url:
        raise GatewayError("AI gateway URL is not configured")
    if not config.api_token:
        raise GatewayError("AI gateway token is not configured")

    last_error: Exception | None = None

    for attempt in range(1, config.max_retries + 1):
        try:
            raw = _send_request(prompt, config)
            return parse_ai_response(raw, provider="gateway")
        except requests.exceptions.Timeout:
            last_error = GatewayError(
                f"Gateway timeout after {config.timeout}s (attempt {attempt}/{config.max_retries})"
            )
            logger.warning(
                "Gateway timeout (attempt %d/%d)",
                attempt,
                config.max_retries,
                extra={"stage": "ai_reasoning", "event": "gateway_timeout", "error_type": "Timeout"},
            )
        except requests.exceptions.ConnectionError as e:
            last_error = GatewayError(f"Gateway connection error: {e}")
            logger.warning(
                "Gateway connection error (attempt %d/%d): %s",
                attempt,
                config.max_retries,
                e,
                extra={"stage": "ai_reasoning", "event": "gateway_connection_error", "error_type": "ConnectionError"},
            )
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status >= 500:
                last_error = GatewayError(f"Gateway server error {status} (attempt {attempt})")
                logger.warning(
                    "Gateway %d (attempt %d/%d)",
                    status,
                    attempt,
                    config.max_retries,
                    extra={"stage": "ai_reasoning", "event": "gateway_server_error", "error_type": "HTTPError", "status_code": status},
                )
            else:
                # 4xx errors are not retryable
                raise GatewayError(f"Gateway client error {status}: {e}") from e
        except OutputParserError as e:
            # Bad JSON from AI — not retryable
            logger.error(
                "Invalid AI response JSON: %s",
                e,
                extra={"stage": "ai_reasoning", "event": "ai_response_parse_error", "error_type": "OutputParserError"},
            )
            raise GatewayError(f"Failed to parse gateway response: {e}") from e

        # Exponential backoff: 1s, 2s, 4s
        if attempt < config.max_retries:
            backoff = 2 ** (attempt - 1)
            logger.info("Retrying in %ds...", backoff)
            time.sleep(backoff)

    raise last_error or GatewayError("Gateway call failed after all retries")


def _send_request(prompt: str, config: AIProviderConfig) -> str:
    """Send the HTTP request to the gateway and return the raw response text."""
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Content-Type": "application/json",
    }

    if config.api_format == "anthropic":
        return _send_anthropic(prompt, config, headers)
    else:
        return _send_openai(prompt, config, headers)


def _send_openai(prompt: str, config: AIProviderConfig, headers: dict) -> str:
    """OpenAI-compatible chat/completions format."""
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    url = config.gateway_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"

    resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
    resp.raise_for_status()

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _send_anthropic(prompt: str, config: AIProviderConfig, headers: dict) -> str:
    """Anthropic-compatible messages format."""
    headers["anthropic-version"] = "2023-06-01"

    payload = {
        "model": config.model,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    url = config.gateway_url.rstrip("/")
    if not url.endswith("/messages"):
        url = f"{url}/messages"

    resp = requests.post(url, json=payload, headers=headers, timeout=config.timeout)
    resp.raise_for_status()

    data = resp.json()
    return data["content"][0]["text"]
