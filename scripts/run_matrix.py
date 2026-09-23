"""
Orchestrator for the v2 rerun: one server restart per run, simulator only by default.

Per run:
  1. health-check the simulator (started once at the beginning)
  2. start the framework server (recorded command line; stdout/stderr to a per-run log)
  3. wait for /health, send 3 warm-up requests to the endpoint's own URL
  4. resolve the PID that serves requests (Gunicorn: the worker, via the process tree;
     multi-worker arm: the master, monitored as a tree)
  5. start monitoring/resource_monitor_v2.py, run Locust with locust_tests/request_log.py,
     stop the monitor, stop the server
  6. write data_v2/<framework>/<endpoint>/c<N>_run<R>_meta.json

Defaults follow the thesis: -t 60s, 5 runs, rest between runs 3c + 30 s and after a
configuration 3c + 60 s (scripts/run_config.sh). REST_MODE=short uses a fixed 30 s instead.
MULTIWORKER=1 runs the multi-worker arm (flask_mw, django_mw) instead of the main matrix.

Spawn rate: r = c / S_ep users per second (S_ep from simulated_endpoint/calibration_v2.json),
r = c for c < 3; request_log.py spaces first requests at 1 / r (UNIFORM_SPAWN=1).

The run is resumable: runs whose meta.json says "complete" (with all expected files)
are skipped. The script refuses to start if tracked files have uncommitted changes.

Real mode (--mode real) is only for scripts/run_real_validation.sh and requires
ALLOW_REAL_API=1 in the environment.

Usage:
  venv/bin/python scripts/run_matrix.py                 # main matrix, simulator
  MULTIWORKER=1 venv/bin/python scripts/run_matrix.py   # multi-worker arm
  venv/bin/python scripts/run_matrix.py --estimate-only
  venv/bin/python scripts/run_matrix.py --frameworks fastapi --endpoints pipeline \\
      --concurrency 100 --runs 1 --duration 30s --out data_v2_smoke
"""

import argparse
import datetime
import glob
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import time

import psutil
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
HOST = "http://localhost:8000"
SIM_URL = "http://127.0.0.1:9000"
CALIBRATION = os.path.join(ROOT, "simulated_endpoint", "calibration_v2.json")
WARMUP_REQUESTS = 3
MONITOR_LEAD_S = 2  # as in scripts/run_config.sh (sleep 2 before Locust)
PER_RUN_OVERHEAD_S = 8  # server start, health, monitor stop, server stop (estimate)

sys.path.insert(0, ROOT)
from common.config import USER_PROMPT  # noqa: E402

ENDPOINT_URL = {
    "inference": "/api/inference",
    "stream": "/api/inference/stream",
    "pipeline": "/api/pipeline",
}
LOCUST_FILE = {
    "inference": "locust_tests/test_inference.py",
    "stream": "locust_tests/test_stream.py",
    "pipeline": "locust_tests/test_pipeline.py",
}
EXTRA_FILES = {"inference": [], "stream": ["stream_metrics"], "pipeline": ["pipeline_metrics"]}
MAIN_FRAMEWORKS = ["flask", "django", "fastapi", "tornado"]
MW_FRAMEWORKS = ["flask_mw", "django_mw"]
SERVERS = {
    "flask": (["-m", "gunicorn", "-c", "flask_app/gunicorn_config.py", "flask_app.app:app"], ".", "gunicorn"),
    "django": (["-m", "gunicorn", "-c", "gunicorn_config.py", "config.wsgi:application"], "django_app", "gunicorn"),
    "fastapi": (["-m", "uvicorn", "fastapi_app.main:app", "--host", "0.0.0.0", "--port", "8000",
                 "--workers", "1"], ".", "single"),
    "tornado": (["tornado_app/main.py"], ".", "single"),
    "flask_mw": (["-m", "gunicorn", "-c", "flask_app/gunicorn_config_mw.py", "flask_app.app:app"], ".", "tree"),
    "django_mw": (["-m", "gunicorn", "-c", "gunicorn_config_mw.py", "config.wsgi:application"],
                  "django_app", "tree"),
}


# ---------------------------------------------------------------- helpers

def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_service_times():
    with open(CALIBRATION, encoding="utf-8") as f:
        return json.load(f)["values"]["service_time_s"]


def spawn_rate(c, s_ep):
    return float(c) if c < 3 else round(c / s_ep, 4)


def rest_between(c, mode):
    return 30 if mode == "short" else 3 * c + 30


def rest_after_config(c, mode):
    return 30 if mode == "short" else 3 * c + 60


def parse_duration(text):
    text = text.strip()
    units = {"s": 1, "m": 60, "h": 3600}
    return int(float(text[:-1]) * units[text[-1]]) if text[-1] in units else int(text)


def base_env(mode):
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "SIMULATE", "ALLOW_REAL_API")}
    env["PYTHONUNBUFFERED"] = "1"
    if mode == "sim":
        env.pop("ANTHROPIC_API_KEY", None)
        env["SIMULATE"] = "1"
    else:
        env["SIMULATE"] = "0"
        env["ALLOW_REAL_API"] = "1"
    return env


def wait_health(url, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(0.2)
    return None


def port_in_use(port):
    return any(c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN
               for c in psutil.net_connections(kind="tcp"))


def start_proc(argv, cwd, env, log_path):
    log = open(log_path, "w")
    return subprocess.Popen(argv, cwd=os.path.join(ROOT, cwd), env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)


def stop_proc(proc, timeout=35):
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        pass


def resolve_pids(proc, kind, timeout=15.0):
    """Return (monitored_pid, worker_pids, tree_flag)."""
    root = psutil.Process(proc.pid)
    if kind == "single":
        return proc.pid, [proc.pid], False
    deadline = time.time() + timeout
    while time.time() < deadline:
        kids = [p.pid for p in root.children(recursive=False)]
        if kids:
            if kind == "gunicorn":
                if len(kids) != 1:
                    raise RuntimeError(f"expected 1 Gunicorn worker, found {kids}")
                return kids[0], kids, False
            return proc.pid, kids, True
        time.sleep(0.2)
    raise RuntimeError("Gunicorn worker(s) not found")


def warmup(endpoint):
    """3 warm-up requests to the endpoint's own URL; returns per-request (status, seconds)."""
    out = []
    for _ in range(WARMUP_REQUESTS):
        t0 = time.perf_counter()
        r = requests.post(HOST + ENDPOINT_URL[endpoint], json={"prompt": USER_PROMPT},
                          stream=(endpoint == "stream"), timeout=120)
        if endpoint == "stream":
            for _chunk in r.iter_content(chunk_size=None):
                pass
        else:
            _ = r.content
        out.append({"status": r.status_code, "seconds": round(time.perf_counter() - t0, 4)})
    return out


def expected_files(prefix, endpoint):
    names = ["stats", "stats_history", "requests", "inflight", "resources", "locust_meta"]
    names += EXTRA_FILES[endpoint]
    ext = {"locust_meta": "json"}
    return [f"{prefix}_{n}.{ext.get(n, 'csv')}" for n in names]


def run_complete(prefix, endpoint):
    meta = prefix + "_meta.json"
    if not os.path.exists(meta):
        return False
    try:
        with open(meta, encoding="utf-8") as f:
            if json.load(f).get("status") != "complete":
                return False
    except (OSError, ValueError):
        return False
    return all(os.path.exists(p) for p in expected_files(prefix, endpoint))


# ---------------------------------------------------------------- estimate

def estimate(frameworks, endpoints, levels, runs, duration_s, mode, s_ep):
    total = 0.0
    for _fw in frameworks:
        for ep in endpoints:
            for c in levels:
                per_run = PER_RUN_OVERHEAD_S + WARMUP_REQUESTS * s_ep[ep] + MONITOR_LEAD_S + duration_s
                total += len(runs) * per_run
                total += (len(runs) - 1) * rest_between(c, mode) + rest_after_config(c, mode)
    return total


def print_estimates(endpoints, levels, runs, duration_s, s_ep):
    def fmt(s):
        return f"{s / 3600:5.1f} h"
    print("Estimated wall time (runs x (60 s + warm-up + ~10 s overhead) + rests):")
    for label, fws in (("main matrix (4 frameworks)", MAIN_FRAMEWORKS),
                       ("multi-worker arm (2 frameworks)", MW_FRAMEWORKS)):
        t = {m: estimate(fws, endpoints, levels, runs, duration_s, m, s_ep) for m in ("thesis", "short")}
        print(f"  {label:34s} REST_MODE=thesis {fmt(t['thesis'])}   REST_MODE=short {fmt(t['short'])}")
    both = {m: estimate(MAIN_FRAMEWORKS + MW_FRAMEWORKS, endpoints, levels, runs, duration_s, m, s_ep)
            for m in ("thesis", "short")}
    print(f"  {'main + multi-worker':34s} REST_MODE=thesis {fmt(both['thesis'])}   REST_MODE=short {fmt(both['short'])}")


# ---------------------------------------------------------------- main loop

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mw = os.environ.get("MULTIWORKER", "0") == "1"
    ap.add_argument("--frameworks", default=",".join(MW_FRAMEWORKS if mw else MAIN_FRAMEWORKS))
    ap.add_argument("--endpoints", default="inference,stream,pipeline")
    ap.add_argument("--concurrency", default="1,5,10,25,50,100")
    ap.add_argument("--runs", default="1,2,3,4,5")
    ap.add_argument("--duration", default="60s", help="Locust -t value (thesis: 60s)")
    ap.add_argument("--out", default="data_v2")
    ap.add_argument("--mode", choices=["sim", "real"], default="sim")
    ap.add_argument("--monitor-interval", type=float, default=float(os.environ.get("MONITOR_INTERVAL", "0.25")))
    ap.add_argument("--estimate-only", action="store_true")
    a = ap.parse_args()

    frameworks = [x for x in a.frameworks.split(",") if x]
    endpoints = [x for x in a.endpoints.split(",") if x]
    levels = [int(x) for x in a.concurrency.split(",") if x]
    runs = [int(x) for x in a.runs.split(",") if x]
    duration_s = parse_duration(a.duration)
    rest_mode = os.environ.get("REST_MODE", "thesis")
    if rest_mode not in ("thesis", "short"):
        sys.exit("REST_MODE must be 'thesis' or 'short'")
    for fw in frameworks:
        if fw not in SERVERS:
            sys.exit(f"unknown framework {fw}")
    if mw and any(fw not in MW_FRAMEWORKS for fw in frameworks):
        sys.exit("MULTIWORKER=1 runs only flask_mw and django_mw")
    if any(fw in MW_FRAMEWORKS for fw in frameworks) and a.mode != "sim":
        sys.exit("the multi-worker arm is simulator only")

    s_ep = load_service_times()
    print_estimates(["inference", "stream", "pipeline"], [1, 5, 10, 25, 50, 100], [1, 2, 3, 4, 5], 60, s_ep)
    this = estimate(frameworks, endpoints, levels, runs, duration_s, rest_mode, s_ep)
    print(f"This invocation: {len(frameworks) * len(endpoints) * len(levels) * len(runs)} runs, "
          f"about {this / 3600:.2f} h (REST_MODE={rest_mode}, before skipping completed runs)")
    if a.estimate_only:
        return

    if a.mode == "real" and os.environ.get("ALLOW_REAL_API") != "1":
        sys.exit("Real mode refused: set ALLOW_REAL_API=1 (only via scripts/run_real_validation.sh)")

    dirty = sh(["git", "status", "--porcelain", "--untracked-files=no"]).stdout.strip()
    if dirty:
        sys.exit(f"Refusing to start: tracked files have uncommitted changes:\n{dirty}")
    git_sha = sh(["git", "rev-parse", "HEAD"]).stdout.strip()
    cal_sha = sha256_file(CALIBRATION)
    freeze = sh([PY, "-m", "pip", "freeze"]).stdout
    freeze_sha = hashlib.sha256(freeze.encode()).hexdigest()

    out_root = os.path.join(ROOT, a.out)
    os.makedirs(out_root, exist_ok=True)
    if port_in_use(8000):
        sys.exit("Port 8000 is already in use; stop the running server first")

    sim = None
    if a.mode == "sim":
        if port_in_use(9000):
            sys.exit("Port 9000 is already in use; stop the running simulator first")
        sim = start_proc([PY, "simulated_endpoint/simulator.py"], ".", base_env("sim"),
                         os.path.join(out_root, "_simulator.log"))
        health = wait_health(SIM_URL + "/health")
        if not health or health.get("calibration_sha256") != cal_sha:
            stop_proc(sim)
            sys.exit("Simulator failed to start or uses a different calibration file")

    try:
        for fw in frameworks:
            for ep in endpoints:
                for c in levels:
                    ran_any = False
                    for i, r in enumerate(runs):
                        out_dir = os.path.join(out_root, fw, ep)
                        os.makedirs(out_dir, exist_ok=True)
                        prefix = os.path.join(out_dir, f"c{c}_run{r}")
                        if run_complete(prefix, ep):
                            print(f"skip {fw}/{ep}/c{c}/run{r}: complete")
                            continue
                        for stale in glob.glob(prefix + "_*"):
                            os.remove(stale)
                        run_one(fw, ep, c, r, prefix, a, duration_s, s_ep, sim, git_sha, cal_sha,
                                freeze_sha, rest_mode)
                        ran_any = True
                        if i < len(runs) - 1:
                            rest = rest_between(c, rest_mode)
                            print(f"rest {rest}s")
                            time.sleep(rest)
                    if ran_any:
                        rest = rest_after_config(c, rest_mode)
                        print(f"configuration rest {rest}s")
                        time.sleep(rest)
    finally:
        stop_proc(sim)


def run_one(fw, ep, c, r, prefix, a, duration_s, s_ep, sim, git_sha, cal_sha, freeze_sha, rest_mode):
    label = f"{fw}/{ep}/c{c}/run{r}"
    print(f"=== {label} {datetime.datetime.now():%H:%M:%S}")
    meta = {
        "status": "started", "framework": fw, "endpoint": ep, "concurrency": c, "run": r,
        "mode": a.mode, "git_sha": git_sha, "calibration_v2_sha256": cal_sha, "pip_freeze_sha256": freeze_sha,
        "python": platform.python_version(), "platform": platform.platform(),
        "nproc": len(os.sched_getaffinity(0)), "rest_mode": rest_mode, "duration_s": duration_s,
        "monitor_interval_s": a.monitor_interval, "run_start_ts": time.time(),
    }
    vm = psutil.virtual_memory()
    meta["mem_available_mb_at_start"] = round(vm.available / 2**20, 1)
    meta["mem_total_mb"] = round(vm.total / 2**20, 1)
    meta["loadavg_at_start"] = os.getloadavg()

    server = monitor = None
    env = base_env(a.mode)
    try:
        if sim is not None:
            h = wait_health(SIM_URL + "/health", timeout=5)
            if not h or sim.poll() is not None:
                raise RuntimeError("simulator health check failed")
            meta["simulator_pid"] = sim.pid
            meta["simulator_calibration_sha256"] = h.get("calibration_sha256")

        args, cwd, kind = SERVERS[fw]
        argv = [PY] + args
        meta["server_cmd"] = argv
        meta["server_cwd"] = cwd
        meta["server_env"] = {k: env.get(k) for k in ("SIMULATE", "ALLOW_REAL_API") if k in env}
        server = start_proc(argv, cwd, env, prefix + "_server.log")
        meta["server_pid"] = server.pid
        if not wait_health(HOST + "/health"):
            raise RuntimeError("server /health did not respond")
        meta["server_ready_ts"] = time.time()

        meta["warmup"] = warmup(ep)
        if any(w["status"] != 200 for w in meta["warmup"]):
            raise RuntimeError(f"warm-up failed: {meta['warmup']}")

        mon_pid, worker_pids, tree = resolve_pids(server, kind)
        meta.update({"monitored_pid": mon_pid, "worker_pids": worker_pids, "monitor_tree": tree})
        mon_cmd = [PY, "monitoring/resource_monitor_v2.py", "--pid", str(mon_pid),
                   "--output", prefix + "_resources.csv", "--interval", str(a.monitor_interval)]
        if tree:
            mon_cmd.append("--tree")
        meta["monitor_cmd"] = mon_cmd
        monitor = subprocess.Popen(mon_cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(MONITOR_LEAD_S)

        rate = spawn_rate(c, s_ep[ep])
        locust_cmd = [PY, "-m", "locust", "-f", f"{LOCUST_FILE[ep]},locust_tests/request_log.py",
                      "--headless", "-u", str(c), "-r", str(rate), "-t", a.duration,
                      "--host", HOST, "--csv", prefix]
        meta.update({"spawn_rate": rate, "service_time_s": s_ep[ep], "uniform_spawn": True,
                     "locust_cmd": locust_cmd, "locust_start_ts": time.time()})
        lenv = dict(env, UNIFORM_SPAWN="1")
        with open(prefix + "_locust.log", "w") as log:
            rc = subprocess.run(locust_cmd, cwd=ROOT, env=lenv, stdout=log, stderr=subprocess.STDOUT,
                                timeout=duration_s + 120).returncode
        meta["locust_end_ts"] = time.time()
        meta["locust_returncode"] = rc
    finally:
        if monitor is not None and monitor.poll() is None:
            monitor.send_signal(signal.SIGTERM)
            try:
                monitor.wait(10)
            except subprocess.TimeoutExpired:
                monitor.kill()
        stop_proc(server)
        meta["run_end_ts"] = time.time()
        missing = [p for p in expected_files(prefix, ep) if not os.path.exists(p)]
        meta["missing_files"] = [os.path.basename(p) for p in missing]
        if "locust_returncode" in meta and not missing:
            meta["status"] = "complete"
        with open(prefix + "_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print(f"    {label}: {meta['status']}" + (f", missing {meta['missing_files']}" if missing else ""))


if __name__ == "__main__":
    main()
