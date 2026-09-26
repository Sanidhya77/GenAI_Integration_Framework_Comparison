"""
Orchestrator for the v2 rerun: one server restart per run, simulator only by default.

Per run:
  1. health-check the simulator (started once at the beginning)
  2. start the framework server (recorded command line; stdout/stderr to a per-run log)
  3. wait for /health, send 3 warm-up requests to the endpoint's own URL
  4. resolve the PID that serves requests (Gunicorn: the worker, via the process tree;
     multi-worker arm: the master, monitored as a tree)
  5. start monitoring/resource_monitor_v2.py on the server and (simulator mode) a second one
     on the simulator (<prefix>_sim_monitor.csv), run Locust with locust_tests/request_log.py,
     stop the monitors, stop the server
  6. write data_v2/<framework>/<endpoint>/c<N>_run<R>_meta.json

Clock. Every window marker, deadline and cross-process time is time.monotonic()
(*_mono keys); *_ts keys are wall-clock labels. meta.json records (wall, monotonic) anchor
pairs at run start and end.
  - Clock-step guard: both monitors record time.time() - time.monotonic() per sample. If
    that offset (with the two anchors) varies by more than 20 ms within a run, meta.json gets
    clock_step_detected: true and clock_step_ms.
  - Time-sync preflight: refuses to start (and aborts before a run) if systemd-timesyncd,
    chronyd or ntp is active, unless ALLOW_TIMESYNC=1; records their state, the kernel
    clocksource and apt-daily(-upgrade).timer (warning only) in meta.json.
  - Host clock rate (scripts/hostclock.py): one Windows-host clock sample right before
    Locust starts, one at the midpoint of the Locust run and one right after it stops;
    clock_rate_ratio, clock_rate_uncertainty, half ratios, clock_rate_unstable and
    clock_rate_off_nominal go to meta.json (null on failure; never aborts a run).
  - --redo-clock-steps treats runs with clock_step_detected, clock_rate_unstable or
    clock_rate_off_nominal as incomplete, so they are deleted and redone.

Idle memory: idle_rss_mb and idle_uss_mb = median of the monitor samples in the 2 s lead
before Locust starts; idle_drift = true if either differs by more than 2 MB from the first
complete run of the same configuration (recorded, never aborts).

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
import csv
import datetime
import glob
import hashlib
import json
import os
import platform
import re
import signal
import statistics
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
TIMESYNC_SERVICES = ("systemd-timesyncd", "chronyd", "ntp")
APT_TIMERS = ("apt-daily.timer", "apt-daily-upgrade.timer")
CLOCKSOURCE = "/sys/devices/system/clocksource/clocksource0/current_clocksource"
CLOCK_STEP_THRESHOLD_MS = 20.0
IDLE_DRIFT_MB = 2.0
ACTIVE_STATES = ("active", "activating", "reloading", "deactivating")

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common.config import USER_PROMPT  # noqa: E402
import hostclock  # noqa: E402

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
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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


def expected_files(prefix, endpoint, mode="sim"):
    names = ["stats", "stats_history", "requests", "inflight", "resources", "locust_meta"]
    names += EXTRA_FILES[endpoint]
    if mode == "sim":
        names.append("sim_monitor")
    ext = {"locust_meta": "json"}
    return [f"{prefix}_{n}.{ext.get(n, 'csv')}" for n in names]


CLOCK_FLAGS = ("clock_step_detected", "clock_rate_unstable", "clock_rate_off_nominal")


def clock_flagged(meta):
    """Names of the clock flags set in a run's meta (empty list if none)."""
    return [k for k in CLOCK_FLAGS if meta.get(k) is True]


def run_complete(prefix, endpoint, mode="sim", redo_clock_steps=False):
    meta = prefix + "_meta.json"
    if not os.path.exists(meta):
        return False
    try:
        with open(meta, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return False
    if m.get("status") != "complete":
        return False
    if redo_clock_steps and clock_flagged(m):
        return False
    return all(os.path.exists(p) for p in expected_files(prefix, endpoint, mode))


# ---------------------------------------------------------------- clock and idle checks

def anchor():
    """(wall, monotonic) pair; the wall clock is read between two monotonic reads."""
    m0 = time.monotonic()
    w = time.time()
    m1 = time.monotonic()
    return {"wall": w, "mono": (m0 + m1) / 2}


def _systemctl_state(unit):
    try:
        r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"error: {e}"


def clock_preflight():
    """State of time-sync services, the kernel clocksource and apt timers."""
    try:
        with open(CLOCKSOURCE, encoding="utf-8") as f:
            source = f.read().strip()
    except OSError as e:
        source = f"error: {e}"
    return {"timesync_state": {u: _systemctl_state(u) for u in TIMESYNC_SERVICES},
            "clocksource": source,
            "apt_timers": {u: _systemctl_state(u) for u in APT_TIMERS},
            "allow_timesync": os.environ.get("ALLOW_TIMESYNC") == "1"}


def timesync_problem(state):
    """Reason to refuse, or None. Unknown states (systemctl missing) also refuse."""
    if state["allow_timesync"]:
        return None
    bad = {u: v for u, v in state["timesync_state"].items()
           if v in ACTIVE_STATES or v.startswith("error")}
    if bad:
        return (f"time-sync service state {bad}: a running NTP client steps and slews the clock "
                "(PAPER_CONTEXT §13). Stop it, or set ALLOW_TIMESYNC=1 to override.")
    return None


def apt_warning(state):
    act = [u for u, v in state["apt_timers"].items() if v in ACTIVE_STATES]
    return f"WARNING: {', '.join(act)} active (background apt runs may disturb a run)" if act else None


def detect_clock_step(offsets, threshold_ms=CLOCK_STEP_THRESHOLD_MS):
    """(detected, step_ms) for a sequence of wall - monotonic offsets in seconds.

    step_ms = max - min of the offsets; detected when it exceeds threshold_ms."""
    vals = [o for o in offsets if o is not None]
    if len(vals) < 2:
        return False, 0.0
    step_ms = (max(vals) - min(vals)) * 1000
    return step_ms > threshold_ms, step_ms


def monitor_offsets(path):
    rows = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            rows = [float(r["wall_minus_mono_s"]) for r in csv.DictReader(f)]
    return rows


def idle_memory(resources_path, locust_start_mono, lead_s=MONITOR_LEAD_S):
    """Median RSS and USS of the samples in [locust_start - lead, locust_start)."""
    rss, uss = [], []
    with open(resources_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if locust_start_mono - lead_s <= float(r["mono"]) < locust_start_mono:
                rss.append(float(r["rss_mb"]))
                uss.append(float(r["uss_mb"]))
    if not rss:
        return None, None, 0
    return statistics.median(rss), statistics.median(uss), len(rss)


def idle_reference(prefix, run):
    """(run, idle_rss_mb, idle_uss_mb) of the lowest-numbered complete run of this configuration."""
    base = re.sub(r"_run\d+$", "", prefix)
    best = None
    for path in glob.glob(base + "_run*_meta.json"):
        try:
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if m.get("status") != "complete" or m.get("run") == run or m.get("idle_rss_mb") is None:
            continue
        if best is None or m["run"] < best[0]:
            best = (m["run"], m["idle_rss_mb"], m["idle_uss_mb"])
    return best


def proc_cpu_s(pid):
    try:
        t = psutil.Process(pid).cpu_times()
        return t.user + t.system
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


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
    ap.add_argument("--redo-clock-steps", action="store_true",
                    help="treat runs with clock_step_detected, clock_rate_unstable or clock_rate_off_nominal "
                         "as incomplete (delete and redo them)")
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
    clock_state = clock_preflight()
    problem = timesync_problem(clock_state)
    if problem:
        sys.exit(f"Refusing to start: {problem}")
    print(f"clock preflight: {clock_state}")
    if apt_warning(clock_state):
        print(apt_warning(clock_state))
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
                        if run_complete(prefix, ep, a.mode, a.redo_clock_steps):
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
    start_anchor = anchor()
    meta = {
        "status": "started", "framework": fw, "endpoint": ep, "concurrency": c, "run": r,
        "mode": a.mode, "git_sha": git_sha, "calibration_v2_sha256": cal_sha, "pip_freeze_sha256": freeze_sha,
        "python": platform.python_version(), "platform": platform.platform(),
        "nproc": len(os.sched_getaffinity(0)), "rest_mode": rest_mode, "duration_s": duration_s,
        "monitor_interval_s": a.monitor_interval, "run_start_ts": start_anchor["wall"],
        "run_start_mono": start_anchor["mono"], "anchor_start": start_anchor,
    }
    vm = psutil.virtual_memory()
    meta["mem_available_mb_at_start"] = round(vm.available / 2**20, 1)
    meta["mem_total_mb"] = round(vm.total / 2**20, 1)
    meta["loadavg_at_start"] = os.getloadavg()
    clock_state = clock_preflight()
    meta.update(clock_state)
    if apt_warning(clock_state):
        print("    " + apt_warning(clock_state))

    server = monitor = sim_monitor = None
    samples = {"start": None, "mid": None, "end": None}
    cpu_marks = {}
    env = base_env(a.mode)
    try:
        problem = timesync_problem(clock_state)
        if problem:
            raise RuntimeError(problem)
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
        meta["server_ready_mono"] = time.monotonic()

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
        if sim is not None:
            sim_cmd = [PY, "monitoring/resource_monitor_v2.py", "--pid", str(sim.pid),
                       "--output", prefix + "_sim_monitor.csv", "--interval", str(a.monitor_interval)]
            meta["sim_monitor_cmd"] = sim_cmd
            sim_monitor = subprocess.Popen(sim_cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(MONITOR_LEAD_S)

        rate = spawn_rate(c, s_ep[ep])
        locust_cmd = [PY, "-m", "locust", "-f", f"{LOCUST_FILE[ep]},locust_tests/request_log.py",
                      "--headless", "-u", str(c), "-r", str(rate), "-t", a.duration,
                      "--host", HOST, "--csv", prefix]
        lenv = dict(env, UNIFORM_SPAWN="1")
        samples["start"] = hostclock.sample()
        cpu_marks["start"] = {k: proc_cpu_s(p.pid) for k, p in (("monitor", monitor), ("sim_monitor", sim_monitor))
                              if p is not None}
        meta.update({"spawn_rate": rate, "service_time_s": s_ep[ep], "uniform_spawn": True,
                     "locust_cmd": locust_cmd, "locust_start_ts": time.time(), "locust_start_mono": time.monotonic()})
        with open(prefix + "_locust.log", "w") as log:
            locust = subprocess.Popen(locust_cmd, cwd=ROOT, env=lenv, stdout=log, stderr=subprocess.STDOUT)
            deadline = meta["locust_start_mono"] + duration_s + 120
            try:
                try:  # sleep until the midpoint of the Locust run (returns early if Locust exits)
                    locust.wait(max(0.0, meta["locust_start_mono"] + duration_s / 2 - time.monotonic()))
                except subprocess.TimeoutExpired:
                    samples["mid"] = hostclock.sample()
                rc = locust.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                locust.kill()
                locust.wait()
                raise
        meta["locust_end_ts"] = time.time()
        meta["locust_end_mono"] = time.monotonic()
        cpu_marks["end"] = {k: proc_cpu_s(p.pid) for k, p in (("monitor", monitor), ("sim_monitor", sim_monitor))
                            if p is not None}
        samples["end"] = hostclock.sample()
        meta["locust_returncode"] = rc
    finally:
        for p in (monitor, sim_monitor):
            if p is not None and p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
        stop_proc(server)
        end_anchor = anchor()
        meta["run_end_ts"] = end_anchor["wall"]
        meta["run_end_mono"] = end_anchor["mono"]
        meta["anchor_end"] = end_anchor
        finish_meta(meta, prefix, r, samples, cpu_marks, start_anchor, end_anchor)
        missing = [p for p in expected_files(prefix, ep, a.mode) if not os.path.exists(p)]
        meta["missing_files"] = [os.path.basename(p) for p in missing]
        if "locust_returncode" in meta and not missing:
            meta["status"] = "complete"
        with open(prefix + "_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        flags = clock_flagged(meta)
        print(f"    {label}: {meta['status']}" + (f", missing {meta['missing_files']}" if missing else "")
              + f", clock_rate_ratio {meta.get('clock_rate_ratio')}, clock_step_ms {meta.get('clock_step_ms')}"
              + (f", CLOCK FLAGS {flags}" if flags else "")
              + (f", IDLE DRIFT {meta.get('idle_rss_diff_mb')} / {meta.get('idle_uss_diff_mb')} MB"
                 if meta.get("idle_drift") else ""))


def finish_meta(meta, prefix, run, samples, cpu_marks, start_anchor, end_anchor):
    """Clock step, clock rate, monitor CPU and idle memory. Each part records null on failure."""
    offs = [start_anchor["wall"] - start_anchor["mono"], end_anchor["wall"] - end_anchor["mono"]]
    try:
        offs += monitor_offsets(prefix + "_resources.csv") + monitor_offsets(prefix + "_sim_monitor.csv")
        detected, step_ms = detect_clock_step(offs)
        meta["clock_step_detected"], meta["clock_step_ms"] = detected, round(step_ms, 3)
        meta["clock_offset_samples"] = len(offs)
    except Exception as e:  # noqa: BLE001
        meta["clock_step_detected"] = meta["clock_step_ms"] = None
        meta["clock_step_error"] = repr(e)

    meta["clock_sample_start"], meta["clock_sample_mid"], meta["clock_sample_end"] = (
        samples["start"], samples["mid"], samples["end"])
    meta.update(hostclock.rate(samples["start"], samples["mid"], samples["end"]))

    window = (meta.get("locust_end_mono") or 0) - (meta.get("locust_start_mono") or 0)
    for k in ("monitor", "sim_monitor"):
        s0, s1 = cpu_marks.get("start", {}).get(k), cpu_marks.get("end", {}).get(k)
        meta[f"{k}_cpu_pct"] = (round((s1 - s0) / window * 100, 3)
                                if s0 is not None and s1 is not None and window > 0 else None)

    meta["idle_rss_mb"] = meta["idle_uss_mb"] = meta["idle_drift"] = None
    try:
        if meta.get("locust_start_mono") is not None:
            rss, uss, n = idle_memory(prefix + "_resources.csv", meta["locust_start_mono"])
            meta["idle_rss_mb"], meta["idle_uss_mb"], meta["idle_samples"] = rss, uss, n
            ref = idle_reference(prefix, run)
            if rss is not None:
                if ref is None:
                    meta["idle_reference_run"], meta["idle_rss_diff_mb"], meta["idle_uss_diff_mb"] = run, 0.0, 0.0
                else:
                    meta["idle_reference_run"] = ref[0]
                    meta["idle_rss_diff_mb"] = round(rss - ref[1], 3)
                    meta["idle_uss_diff_mb"] = round(uss - ref[2], 3)
                meta["idle_drift"] = (abs(meta["idle_rss_diff_mb"]) > IDLE_DRIFT_MB
                                      or abs(meta["idle_uss_diff_mb"]) > IDLE_DRIFT_MB)
    except Exception as e:  # noqa: BLE001
        meta["idle_error"] = repr(e)


if __name__ == "__main__":
    main()
