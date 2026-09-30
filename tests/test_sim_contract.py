"""T1: the anthropic SDK (sync and async, stream and non-stream) against the simulator.

Asserts text, chunk count, usage, stop reason, clean termination, timing, and that the
request parameters are exactly the thesis parameters from common/config.py.
"""
import asyncio
import json
import time

import pytest

from common import anthropic_client as ac
from common.config import ANTHROPIC_MODEL, MAX_TOKENS, SYSTEM_PROMPT, TEMPERATURE, USER_PROMPT
from common.pipeline_service import _build_augmented_prompt
from common.retrieval import _search

PIPE_PROMPT = _build_augmented_prompt(USER_PROMPT, _search(USER_PROMPT))
TOL = 0.08  # s, timing tolerance for single uncontended calls


def cal(sim):
    return sim["health"]["calibration"]


def last_request(sim):
    with open(sim["request_log"]) as f:
        return json.loads(f.readlines()[-1])


def assert_thesis_params(body, prompt, stream):
    assert body["model"] == ANTHROPIC_MODEL
    assert body["max_tokens"] == MAX_TOKENS
    assert body["temperature"] == TEMPERATURE
    assert body["system"] == SYSTEM_PROMPT
    assert body["messages"] == [{"role": "user", "content": prompt}]
    assert bool(body.get("stream")) is stream


def test_clients_point_at_simulator():
    c, a = ac.get_sync_client(), ac.get_async_client()
    assert str(c.base_url).startswith("http://127.0.0.1:9000")
    assert str(a.base_url).startswith("http://127.0.0.1:9000")
    assert c.max_retries == 2 and a.max_retries == 2  # SDK defaults, as in the thesis


@pytest.mark.parametrize("prompt,kind", [(USER_PROMPT, "inference"), (PIPE_PROMPT, "pipeline")])
def test_sync_non_stream(simulator, prompt, kind):
    t0 = time.perf_counter()
    r = ac.inference_sync(prompt)
    dt = time.perf_counter() - t0
    c = cal(simulator)
    assert len(r["response"].encode()) == c[f"{kind}_text_bytes"]
    assert r["model"] == ANTHROPIC_MODEL
    assert r["usage"] == {"input_tokens": c[f"{kind}_input_tokens"], "output_tokens": c["output_tokens"]}
    assert abs(dt - c[f"{kind}_delay_s"]) < TOL, dt
    assert_thesis_params(last_request(simulator), prompt, False)


def test_sync_stream(simulator):
    c = cal(simulator)
    t0 = time.perf_counter(); times = []
    chunks = []
    for text in ac.stream_sync(USER_PROMPT):
        times.append(time.perf_counter() - t0); chunks.append(text)
    assert len(chunks) == c["stream_chunk_count"]
    assert len("".join(chunks).encode()) == c["inference_text_bytes"]
    assert abs(times[0] - c["stream_first_chunk_delay_s"]) < TOL
    assert abs(times[-1] - c["service_time_s"]["stream"]) < TOL
    assert_thesis_params(last_request(simulator), USER_PROMPT, True)
    # final message: usage and stop reason via the SDK accumulator, clean termination
    with ac.get_sync_client().messages.stream(model=ANTHROPIC_MODEL, max_tokens=MAX_TOKENS,
                                              messages=[{"role": "user", "content": "x"}]) as s:
        final = s.get_final_message()
    assert final.usage.output_tokens == c["output_tokens"]
    assert final.stop_reason == c["stop_reason"]
    assert final.content[0].text == "".join(chunks)


def test_async_non_stream_and_stream(simulator):
    c = cal(simulator)

    async def run():
        r = await ac.inference_async(USER_PROMPT)
        chunks = [t async for t in ac.stream_async(USER_PROMPT)]
        async with ac.get_async_client().messages.stream(
                model=ANTHROPIC_MODEL, max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": "x"}]) as s:
            final = await s.get_final_message()
        return r, chunks, final

    r, chunks, final = asyncio.run(run())
    assert len(r["response"].encode()) == c["inference_text_bytes"]
    assert r["usage"]["output_tokens"] == c["output_tokens"]
    assert len(chunks) == c["stream_chunk_count"]
    assert "".join(chunks) == final.content[0].text
    assert final.stop_reason == c["stop_reason"]
    assert final.usage.input_tokens == c["inference_input_tokens"]


def test_real_mode_refused_without_flag(monkeypatch):
    monkeypatch.setattr(ac, "USE_SIMULATED", False)
    monkeypatch.setattr(ac, "_sync_client", None)
    monkeypatch.setattr(ac, "_async_client", None)
    monkeypatch.delenv("ALLOW_REAL_API", raising=False)
    with pytest.raises(RuntimeError):
        ac.get_sync_client()
    with pytest.raises(RuntimeError):
        ac.get_async_client()
