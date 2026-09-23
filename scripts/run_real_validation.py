"""
Real-API validation driver (v2). Spends money; run only via scripts/run_real_validation.sh.

Phases (PHASE env var, default A):
  A    FastAPI /api/inference: c = 1 anchor (3 runs), then c = 25 (3 runs)
  B    FastAPI /api/inference/stream: c = 1 anchor (3 runs), then c = 25 (3 runs)
  all  A then B
The c = 1 anchor runs the same day, immediately before the c = 25 block, so API latency
drift since April 2026 can be separated from concurrency effects.

Each run uses scripts/run_matrix.py:run_one unchanged (60 s, server restart, 3 warm-up
requests to the endpoint's own URL, 250 ms monitor, per-request log); output goes to
data_v2_real/.

Hidden retries. Real mode keeps the SDK defaults (max_retries = 2), so a 429 or 5xx would be
retried silently and show up as latency. Client arguments are not changed; instead the SDK's
own logging is enabled with ANTHROPIC_LOG=info (anthropic/_utils/_logs.py), which logs
  - every retry at INFO:  "Retrying request to <url> in <s> seconds"  (_base_client.py:1161 sync, :1801 async)
  - every HTTP response at INFO via httpx:  'HTTP Request: POST <url> "HTTP/1.1 <code> <reason>"'
Server stdout and stderr go to <prefix>_server.log. After each run the log is scanned; a run
with any retry line, 429 or 5xx response is marked "invalid" in its meta.json and the script
stops.

Guards: refuses without ALLOW_REAL_API=1; refuses if run_matrix.py, another validation, a
benchmark server or the simulator is running (or ports 8000/9000 are busy); refuses a dirty
tracked tree; prints expected requests and cost per phase and in total ($1 / $5 per MTok,
33 input + 256 output tokens per request, warm-ups included) and refuses if the total exceeds
BUDGET_USD (default 5.00); asks for a typed "yes"; prints cumulative estimated spend after
each run. Complete runs are skipped (resume); an existing invalid run blocks the phase until
its files are removed.

Usage (through the wrapper):
  ALLOW_REAL_API=1 PHASE=A ./scripts/run_real_validation.sh
  venv/bin/python scripts/run_real_validation.py --plan-only   # prints the plan, no API contact
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys
import time

import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_matrix as rm  # noqa: E402

ROOT = rm.ROOT
OUT = "data_v2_real"
FRAMEWORK = "fastapi"
PHASES = {"A": "inference", "B": "stream"}
LEVELS = [1, 25]
RUNS = [1, 2, 3]
DURATION = "60s"
PRICE_IN, PRICE_OUT = 1.00, 5.00  # USD per million tokens, Claude Haiku 4.5 list price
TOKENS_IN, TOKENS_OUT = 33, 256
RETRY_RE = re.compile(r"Retrying request to")
HTTP_RE = re.compile(r'HTTP Request: \S+ (\S+) "HTTP/[\d.]+ (\d{3})')
BENCH_PATTERNS = ("run_matrix.py", "run_real_validation.py", "flask_app", "django_app", "config.wsgi",
                  "fastapi_app.main", "tornado_app/main.py", "simulated_endpoint/simulator.py")


def cost_per_request():
    return (TOKENS_IN * PRICE_IN + TOKENS_OUT * PRICE_OUT) / 1e6


def expected_requests(c, s_ep, duration_s):
    """Completions in a closed loop plus the c requests in flight at stop plus warm-ups."""
    return c / s_ep * duration_s + c + rm.WARMUP_REQUESTS


def plan(phases, s_ep, duration_s):
    rows, total = [], 0.0
    for ph in phases:
        ep = PHASES[ph]
        n = sum(len(RUNS) * expected_requests(c, s_ep[ep], duration_s) for c in LEVELS)
        rows.append((ph, ep, n, n * cost_per_request()))
        total += n
    return rows, total, total * cost_per_request()


def print_plan(phases, s_ep, duration_s, budget):
    rows, total_n, total_usd = plan(phases, s_ep, duration_s)
    print(f"Real-API validation plan (model claude-haiku-4-5-20251001, ${PRICE_IN:.2f} in / ${PRICE_OUT:.2f} out "
          f"per MTok, {TOKENS_IN} in + {TOKENS_OUT} out tokens per request):")
    for ph, ep, n, usd in rows:
        per_min = 25 / s_ep[ep] * 60
        print(f"  PHASE {ph} ({FRAMEWORK} {ep}): c = 1 x {len(RUNS)} runs, then c = 25 x {len(RUNS)} runs, "
              f"{duration_s} s each: about {n:.0f} requests, about ${usd:.2f}")
        print(f"      at c = 25: about {per_min:.0f} requests/min and {per_min * TOKENS_OUT:.0f} output tokens/min "
              f"must fit the account's rate limits")
    print(f"  TOTAL: about {total_n:.0f} requests, about ${total_usd:.2f} (BUDGET_USD = {budget:.2f})")
    return total_usd


def other_benchmark_processes():
    me = os.getpid()
    found = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        if p.info["pid"] in (me, os.getppid()):
            continue
        cmd = " ".join(p.info["cmdline"] or [])
        if any(pat in cmd for pat in BENCH_PATTERNS):
            found.append(f"{p.info['pid']}: {cmd[:120]}")
    return found


def scan_server_log(path):
    retries, codes = 0, {}
    with open(path, errors="replace") as f:
        for line in f:
            if RETRY_RE.search(line):
                retries += 1
            m = HTTP_RE.search(line)
            if m:
                codes[m.group(2)] = codes.get(m.group(2), 0) + 1
    n429 = codes.get("429", 0)
    n5xx = sum(v for k, v in codes.items() if k.startswith("5"))
    return {"retry_lines": retries, "http_status_counts": codes, "http_429": n429, "http_5xx": n5xx,
            "http_responses_logged": sum(codes.values())}


def requests_sent(prefix):
    with open(prefix + "_requests.csv", newline="") as f:
        done = sum(1 for _ in csv.DictReader(f))
    with open(prefix + "_inflight.csv", newline="") as f:
        inflight = sum(1 for _ in csv.DictReader(f))
    return done + inflight + rm.WARMUP_REQUESTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-only", action="store_true", help="print the plan and budget, then exit")
    a = ap.parse_args()

    phase = os.environ.get("PHASE", "A").upper()
    if phase not in ("A", "B", "ALL"):
        sys.exit("PHASE must be A, B or all")
    phases = ["A", "B"] if phase == "ALL" else [phase]
    budget = float(os.environ.get("BUDGET_USD", "5.00"))
    rest_mode = os.environ.get("REST_MODE", "thesis")
    duration_s = rm.parse_duration(DURATION)
    s_ep = rm.load_service_times()

    total_usd = print_plan(phases, s_ep, duration_s, budget)
    if a.plan_only:
        return
    if total_usd > budget:
        sys.exit(f"Refusing to run: estimated ${total_usd:.2f} exceeds BUDGET_USD={budget:.2f}.")
    others = other_benchmark_processes()
    if others or rm.port_in_use(8000) or rm.port_in_use(9000):
        sys.exit("Refusing to run: benchmark processes or ports 8000/9000 in use:\n  " + "\n  ".join(others))
    if os.environ.get("ALLOW_REAL_API") != "1":
        sys.exit("Refusing to run: set ALLOW_REAL_API=1 (use scripts/run_real_validation.sh).")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set (export $(cat .env | xargs) first).")
    dirty = rm.sh(["git", "status", "--porcelain", "--untracked-files=no"]).stdout.strip()
    if dirty:
        sys.exit(f"Refusing to start: tracked files have uncommitted changes:\n{dirty}")
    for ph in phases:
        for meta in glob.glob(os.path.join(ROOT, OUT, FRAMEWORK, PHASES[ph], "*_meta.json")):
            if json.load(open(meta)).get("status") == "invalid":
                sys.exit(f"Refusing to run: {os.path.relpath(meta, ROOT)} is marked invalid; inspect and remove "
                         "that run's files first.")

    if input("Type yes to call the real Anthropic API: ").strip() != "yes":
        sys.exit("Aborted.")

    os.environ["ANTHROPIC_LOG"] = "info"  # inherited by the server through run_matrix.base_env
    git_sha = rm.sh(["git", "rev-parse", "HEAD"]).stdout.strip()
    cal_sha = rm.sha256_file(rm.CALIBRATION)
    freeze_sha = hashlib.sha256(rm.sh([rm.PY, "-m", "pip", "freeze"]).stdout.encode()).hexdigest()
    args = argparse.Namespace(mode="real", monitor_interval=0.25, duration=DURATION)
    spent_n = 0

    for ph in phases:
        ep = PHASES[ph]
        print(f"##### PHASE {ph}: {FRAMEWORK} {ep}")
        for c in LEVELS:
            ran = False
            for i, r in enumerate(RUNS):
                out_dir = os.path.join(ROOT, OUT, FRAMEWORK, ep)
                os.makedirs(out_dir, exist_ok=True)
                prefix = os.path.join(out_dir, f"c{c}_run{r}")
                if rm.run_complete(prefix, ep):
                    print(f"skip {ep}/c{c}/run{r}: complete")
                    continue
                for stale in glob.glob(prefix + "_*"):
                    os.remove(stale)
                try:
                    rm.run_one(FRAMEWORK, ep, c, r, prefix, args, duration_s, s_ep, None, git_sha, cal_sha,
                               freeze_sha, rest_mode)
                finally:
                    meta_path = prefix + "_meta.json"
                    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {"status": "started"}
                    scan = scan_server_log(prefix + "_server.log") if os.path.exists(prefix + "_server.log") else {}
                    meta["anthropic_log"] = "info"
                    meta["retry_scan"] = scan
                    meta["phase"] = ph
                    bad = scan.get("retry_lines", 0) or scan.get("http_429", 0) or scan.get("http_5xx", 0)
                    if bad:
                        meta["status"] = "invalid"
                        meta["invalid_reason"] = (f"{scan['retry_lines']} retry lines, {scan['http_429']} x 429, "
                                                  f"{scan['http_5xx']} x 5xx in server log")
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2)
                    if os.path.exists(prefix + "_requests.csv") and os.path.exists(prefix + "_inflight.csv"):
                        spent_n += requests_sent(prefix)
                    else:
                        spent_n += rm.WARMUP_REQUESTS
                    print(f"    retry scan: {scan}")
                    print(f"    cumulative estimated spend: {spent_n} requests, "
                          f"${spent_n * cost_per_request():.2f} of planned ${total_usd:.2f}")
                if bad:
                    sys.exit(f"STOP: {ep}/c{c}/run{r} marked invalid ({meta['invalid_reason']}).")
                if meta.get("status") != "complete":
                    sys.exit(f"STOP: {ep}/c{c}/run{r} did not complete; see its meta.json and logs.")
                ran = True
                if i < len(RUNS) - 1:
                    rest = rm.rest_between(c, rest_mode)
                    print(f"rest {rest}s")
                    time.sleep(rest)
            if ran and not (ph == phases[-1] and c == LEVELS[-1]):
                rest = rm.rest_after_config(c, rest_mode)
                print(f"configuration rest {rest}s")
                time.sleep(rest)
    print(f"Done. Estimated spend: {spent_n} requests, ${spent_n * cost_per_request():.2f}. "
          f"Next: venv/bin/python scripts/validate_real_v2.py --phase {phase.lower()}")


if __name__ == "__main__":
    main()
