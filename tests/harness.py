"""Process helpers shared by the v2 tests (simulator only, never the real API)."""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SIM_URL = "http://127.0.0.1:9000"
SERVER_URL = "http://127.0.0.1:8000"


def sim_env(extra=None):
    """Environment for every process in the tests: simulated mode, no real key."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ALLOW_REAL_API")}
    env["SIMULATE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env.update(extra or {})
    return env


def wait_http(url, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return json.loads(r.read() or b"{}")
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"timeout waiting for {url}")


def start(cmd, log_path, env, cwd=ROOT):
    log = open(log_path, "w")
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)


def stop(proc, timeout=10):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


SERVER_CMDS = {
    "flask": ([PY, "-m", "gunicorn", "-c", "flask_app/gunicorn_config.py", "flask_app.app:app"], ROOT),
    "django": ([PY, "-m", "gunicorn", "-c", "gunicorn_config.py", "config.wsgi:application"],
               os.path.join(ROOT, "django_app")),
    "fastapi": ([PY, "-m", "uvicorn", "fastapi_app.main:app", "--host", "0.0.0.0", "--port", "8000",
                 "--workers", "1"], ROOT),
    "tornado": ([PY, "tornado_app/main.py"], ROOT),
}
