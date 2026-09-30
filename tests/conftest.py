import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SIMULATE"] = "1"
for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ALLOW_REAL_API"):
    os.environ.pop(k, None)

import harness  # noqa: E402


@pytest.fixture(scope="module")
def simulator():
    tmp = tempfile.mkdtemp(prefix="simtest_")
    req_log = os.path.join(tmp, "requests.jsonl")
    proc = harness.start([harness.PY, "simulated_endpoint/simulator.py"], os.path.join(tmp, "sim.log"),
                         harness.sim_env({"SIM_REQUEST_LOG": req_log}))
    try:
        health = harness.wait_http(harness.SIM_URL + "/health")
        yield {"health": health, "request_log": req_log}
    finally:
        harness.stop(proc)
