"""
Anthropic API client for all four frameworks.

Provides synchronous and asynchronous for:
Standard inference (Endpoint 1: /api/inference)
Streaming inference (Endpoint 2: /api/inference/stream)

Sync clients (Anthropic) → Flask, Django
Async clients (AsyncAnthropic) → FastAPI, Tornado

Real and simulated mode use the SAME SDK singletons and call path. When
USE_SIMULATED is True the singletons are only pointed at the local simulated
Messages API (base_url) with a dummy key. Real mode keeps the thesis
constructor arguments (none) and refuses to run unless ALLOW_REAL_API=1.

The singletons are created at server startup (see each app), never inside a
measured request.
"""

import os

from anthropic import Anthropic, AsyncAnthropic

from common.config import (
    ANTHROPIC_MODEL,
    MAX_TOKENS,
    SIMULATED_API_KEY,
    SIMULATED_ENDPOINT_URL,
    SYSTEM_PROMPT,
    TEMPERATURE,
    USE_SIMULATED,
)


# Client singletons created once and reused across requests

_sync_client = None
_async_client = None


def _client_kwargs():
    """Constructor arguments for the SDK clients.

    Real mode: no arguments, identical to the thesis version (dc06cb4).
    Simulated mode: base_url of the local simulator and a dummy key.
    """
    if USE_SIMULATED:
        return {"base_url": SIMULATED_ENDPOINT_URL, "api_key": SIMULATED_API_KEY}
    if os.environ.get("ALLOW_REAL_API") != "1":
        raise RuntimeError(
            "Real Anthropic API mode refused: SIMULATE is not 1 and ALLOW_REAL_API is not 1."
        )
    return {}


def get_sync_client():
    """Return the singleton synchronous Anthropic client."""
    global _sync_client
    if _sync_client is None:
        _sync_client = Anthropic(**_client_kwargs())
    return _sync_client


def get_async_client():
    """Return the singleton asynchronous Anthropic client."""
    global _async_client
    if _async_client is None:
        _async_client = AsyncAnthropic(**_client_kwargs())
    return _async_client



# Synchronous (Flask, Django)


def inference_sync(user_message):
    """Standard inference: send prompt, receive complete response.

    Returns dict with 'response' text and 'usage' metadata.
    """
    client = get_sync_client()
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return {
        "response": message.content[0].text,
        "model": message.model,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    }


def stream_sync(user_message):
    """Streaming inference: yield tokens one at a time.

    Yields individual text chunks as they arrive from the API.
    Used by Flask (generator + yield) and Django (StreamingHttpResponse).
    """
    client = get_sync_client()
    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            yield text



# Asynchronous (FastAPI, Tornado)


async def inference_async(user_message):
    """Async standard inference: send prompt, receive complete response.

    Returns dict with 'response' text and 'usage' metadata.
    """
    client = get_async_client()
    message = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return {
        "response": message.content[0].text,
        "model": message.model,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    }


async def stream_async(user_message):
    """Async streaming inference: yield tokens one at a time.

    Yields individual text chunks as they arrive from the API.
    Used by FastAPI (StreamingResponse) and Tornado (self.write + self.flush).
    """
    client = get_async_client()
    async with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        async for text in stream.text_stream:
            yield text
