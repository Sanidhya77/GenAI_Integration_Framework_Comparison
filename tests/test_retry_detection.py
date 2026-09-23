"""Retry detection for the real-API validation, tested without the real API.

A stub on port 9000 answers every /v1/messages call with 429, so the SDK singleton in a
simulated-mode FastAPI server retries (max_retries = 2, SDK default). With ANTHROPIC_LOG=info the
server log must show the retries and the 429 responses, and scan_server_log must count them.
The positive control uses the real simulator: 0 retries, only 200 responses.
"""
import http.server
import os
import sys
import tempfile
import threading

import requests

import harness

sys.path.insert(0, os.path.join(harness.ROOT, "scripts"))
from run_real_validation import scan_server_log  # noqa: E402


class Always429(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        body = b'{"type":"error","error":{"type":"rate_limit_error","message":"stub"}}'
        self.send_response(429)
        self.send_header("content-type", "application/json")
        self.send_header("retry-after", "0")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def run_fastapi_once(log_path):
    env = harness.sim_env({"ANTHROPIC_LOG": "info"})
    cmd, cwd = harness.SERVER_CMDS["fastapi"]
    server = harness.start(cmd, log_path, env, cwd=cwd)
    try:
        harness.wait_http(harness.SERVER_URL + "/health", timeout=30)
        return requests.post(harness.SERVER_URL + "/api/inference", json={"prompt": "x"}, timeout=60).status_code
    finally:
        harness.stop(server)


def test_429_retries_are_detected():
    stub = http.server.ThreadingHTTPServer(("127.0.0.1", 9000), Always429)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    try:
        log = os.path.join(tempfile.mkdtemp(prefix="retry_"), "server.log")
        status = run_fastapi_once(log)
    finally:
        stub.shutdown()
        stub.server_close()
    scan = scan_server_log(log)
    assert status == 500
    assert scan["retry_lines"] == 2, scan      # max_retries = 2
    assert scan["http_429"] == 3, scan         # first attempt + 2 retries


def test_clean_run_has_no_retries(simulator):
    log = os.path.join(tempfile.mkdtemp(prefix="noretry_"), "server.log")
    assert run_fastapi_once(log) == 200
    scan = scan_server_log(log)
    assert scan["retry_lines"] == 0 and scan["http_429"] == 0 and scan["http_5xx"] == 0, scan
    assert scan["http_status_counts"] == {"200": 1}, scan
