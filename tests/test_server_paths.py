"""T2, T3, T4 per framework, simulator only.

T4: single-request timing at c = 1 per endpoint vs calibration; Stage 2 about 50 ms.
T3: framework SSE events carry plain-text tokens, token count = calibrated chunk count,
    and the done event is recognised by the Locust parser (same logic as test_stream.py).
T2: after warm-up, 50 requests (mixed endpoints, concurrent) construct 0 SDK/httpx clients.

Per-framework results are appended to $V2_TEST_REPORT (JSON lines) if set.
"""
import concurrent.futures
import json
import os
import tempfile
import time

import pytest
import requests

import harness
from common.config import USER_PROMPT

URLS = {"inference": "/api/inference", "stream": "/api/inference/stream", "pipeline": "/api/pipeline"}
FRAMEWORKS = ["flask", "django", "fastapi", "tornado"]


def parse_stream(resp, t0):
    """Same event handling as locust_tests/test_stream.py, plus raw token capture."""
    tokens, ttft, done, buffer = [], None, False, ""
    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
        buffer += chunk
        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            event = event.strip()
            if event.startswith("data: "):
                data = json.loads(event[6:])
                if data.get("done"):
                    done = True
                    continue
                if ttft is None:
                    ttft = time.perf_counter() - t0
                tokens.append(data["token"])
    return tokens, ttft, done


def one(endpoint):
    t0 = time.perf_counter()
    r = requests.post(harness.SERVER_URL + URLS[endpoint], json={"prompt": USER_PROMPT},
                      stream=(endpoint == "stream"), timeout=120)
    assert r.status_code == 200
    if endpoint == "stream":
        tokens, ttft, done = parse_stream(r, t0)
        return {"total": time.perf_counter() - t0, "tokens": tokens, "ttft": ttft, "done": done}
    body = r.json()
    return {"total": time.perf_counter() - t0, "body": body}


@pytest.mark.parametrize("fw", FRAMEWORKS)
def test_server_paths(simulator, fw):
    cal = simulator["health"]["calibration"]
    S = cal["service_time_s"]
    tmp = tempfile.mkdtemp(prefix=f"t2_{fw}_")
    clog = os.path.join(tmp, "constructions.jsonl")
    env = harness.sim_env({"PYTHONPATH": os.path.join(harness.ROOT, "tests", "instrument"),
                           "CONSTRUCTION_LOG": clog})
    cmd, cwd = harness.SERVER_CMDS[fw]
    server = harness.start(cmd, os.path.join(tmp, "server.log"), env, cwd=cwd)
    report = {"framework": fw}
    try:
        harness.wait_http(harness.SERVER_URL + "/health", timeout=30)
        for ep in URLS:                      # 3 warm-up requests per endpoint
            for _ in range(3):
                one(ep)
        with open(clog) as f:
            startup = [json.loads(l) for l in f]
        report["constructions_at_startup_and_warmup"] = sorted({(c["cls"]) for c in startup})
        t_after_warmup = time.time()

        # T4: sequential single requests (c = 1)
        timing = {}
        inf = [one("inference")["total"] for _ in range(3)]
        timing["inference_minus_S_ms"] = round((min(inf) - S["inference"]) * 1000, 1)
        st = [one("stream") for _ in range(3)]
        timing["stream_ttft_minus_first_delay_ms"] = round(
            (min(x["ttft"] for x in st) - cal["stream_first_chunk_delay_s"]) * 1000, 1)
        timing["stream_total_minus_S_ms"] = round((min(x["total"] for x in st) - S["stream"]) * 1000, 1)
        pl = [one("pipeline") for _ in range(3)]
        stg = [x["body"]["stage_timings"] for x in pl]
        timing["pipeline_minus_S_ms"] = round((min(x["total"] for x in pl) - S["pipeline"]) * 1000, 1)
        timing["stage2_ms"] = sorted(s["stage2_context_retrieval_ms"] for s in stg)
        timing["stage3_minus_delay_ms"] = round(min(s["stage3_augmented_inference_ms"] for s in stg)
                                                - cal["pipeline_delay_s"] * 1000, 1)
        report["t4"] = timing
        assert 0 <= timing["inference_minus_S_ms"] < 30
        assert 0 <= timing["stream_ttft_minus_first_delay_ms"] < 30
        assert 0 <= timing["stream_total_minus_S_ms"] < 30
        assert 0 <= timing["pipeline_minus_S_ms"] < 30
        assert all(50 <= v < 53 for v in timing["stage2_ms"])
        assert 0 <= timing["stage3_minus_delay_ms"] < 20

        # T3: framing parity
        for x in st:
            assert x["done"], "done event not recognised by the Locust parser logic"
            assert len(x["tokens"]) == cal["stream_chunk_count"]
            for tok in x["tokens"]:
                assert isinstance(tok, str)
                with pytest.raises(ValueError):
                    json.loads(tok)          # plain text, not nested JSON
            assert len("".join(x["tokens"]).encode()) == cal["inference_text_bytes"]
        report["t3"] = {"token_counts": [len(x["tokens"]) for x in st], "done_recognised": True,
                        "first_token_sample": st[0]["tokens"][0]}

        # T2: 50 requests after warm-up, mixed endpoints, 25 concurrent
        eps = [list(URLS)[i % 3] for i in range(50)]
        with concurrent.futures.ThreadPoolExecutor(25) as ex:
            list(ex.map(one, eps))
        with open(clog) as f:
            after = [json.loads(l) for l in f if json.loads(l)["ts"] > t_after_warmup]
        report["t2"] = {"requests": 50 + 9, "constructions_after_warmup": len(after)}
        assert len(after) == 0, after
    finally:
        harness.stop(server)
        if os.environ.get("V2_TEST_REPORT"):
            with open(os.environ["V2_TEST_REPORT"], "a") as f:
                f.write(json.dumps(report) + "\n")
