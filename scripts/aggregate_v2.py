"""
Aggregation for the v2 rerun (data_v2/ -> results_v2/). The thesis aggregation,
scripts/aggregate_data.py, is unchanged.

One rule for every metric: compute the value per run, then report the median over
runs with the run-to-run spread (min, max, number of runs).

Clock. Every window, age and rate uses the time.monotonic() columns written since v2-freeze
(requests.csv start_mono/end_mono, locust_meta first_user_start_mono/stop_mono,
inflight issued_mono, monitor mono). Data without them is refused (exit with the path):
wall-clock windows are biased by clock steps (PAPER_CONTEXT §13). Durations measured
in-process (perf_counter: latency, TTFT, TPOT, stages) are used as logged.

Windows (t0 = first user start, stop = Locust test_stopping, both monotonic):
  steady  [t0 + 2 S_ep, stop]   throughput, consistency ratio, per-second completions
  loaded  [t0, stop]            error rate, stream CSR, pipeline completion, CPU
  all rows                      latency, TTFT, TPOT and stage percentiles (as before)

Per framework, endpoint, concurrency and run:
  throughput      Locust Requests/s (continuity with the thesis) and, from the per-request
                  log, fixed-window throughput (completions ending in the steady window /
                  its length) and completion rate (n - 1) / (last - first completion)
  ceiling         async: c / S_ep; single sync worker: 1 / S_ep;
                  multi-worker: min(c, workers) / S_ep; share reported for both estimators
  consistency     closed_system_consistency = mean latency x completion rate / c
                  mean latency: successful requests ending in the steady window (s);
                  completion rate X: as above (count / window if fewer than 2 completions).
                  In a closed loop with zero think time and N = c users, Little's law gives
                  N = X x R, so the ratio is 1 when the log is consistent. It replaces the
                  former Little's-law ratio and R = N/X check, which were one identity.
  response law    R = N / X (estimate, used for censored sync latency), derived queue wait
                  R - service and derived TTFT = wait + uncontended TTFT (stream)
  latency         p50, p90, p95, p99, mean of client-side latency (successful requests);
                  p99 omitted when n < 100 (applies to every p99 below)
  errors          error_rate_pct = failed / (succeeded + failed) over requests finished in
                  the loaded window; failures_by_type counts them by exception class or
                  "HTTP n"; in-flight at stop reported separately (inflight_at_stop)
  stream CSR      stream_csr_pct over streams finished in the loaded window; see STREAM_RULE.
                  _stream_metrics.csv row i is paired with SSE row i of _requests.csv (both are
                  appended in the same greenlet without a yield); every pair must have
                  total_time_ms == response_time_ms and token_count == response_length,
                  otherwise the script stops
  pipeline PCR    pipeline_completion_pct over requests finished in the loaded window:
                  HTTP 200 and all four stage timings present (requests.csv stages_logged = 4)
  stream          TTFT, TPOT p50 / p95 / p99 over streams with done seen; token count
  pipeline        Stages 1 to 4 and server-side E2E p50 / p95 / p99 (within one execution
                  model only); client-side E2E = client latency (for cross-model comparison)
  censoring       in-flight at stop, censoring fraction inflight / (completions + inflight);
                  late in-flight = in-flight older than the observed p95; percentiles flagged
                  censored when late in-flight >= 1 % of completions
  stability       min_1s_completion_ratio = fewest completions in any full 1 s bin of the
                  steady window / completion rate (not meaningful when X << 1 req/s)
  resources       CPU mean over the loaded window, CPU ms per completed request, idle
                  RSS/USS from meta.json (median of the 2 s pre-Locust lead), idle drift,
                  peak, growth = peak - idle; simulator CPU mean and p95 over the loaded
                  window and its peak USS (_sim_monitor.csv); the monitors' own CPU
  clock           clock_rate_ratio (guest monotonic / Windows host, scripts/hostclock.py),
                  its uncertainty and half-run stability, clock_step_detected / _ms

Per configuration: median, min, max, n of every metric; clock_rate_ratio mean and spread;
idle RSS/USS spread (max - min); failures_by_type summed over runs.

--clock-correct additionally writes *_clockcorrected.csv: every duration (every *_ms metric
except cpu_ms_per_request and clock_step_ms, plus window_s) is divided by the run's
clock_rate_ratio and every rate (Locust RPS, throughputs, ceiling) multiplied by it. CPU %
and CPU ms are CPU time (not the guest clock rate) and are not corrected; shares and
ratios are unchanged. Runs
without a ratio are copied unchanged with clock_correction = "unavailable". The default
files are uncorrected (clock_correction = "uncorrected").

Usage:
  venv/bin/python scripts/aggregate_v2.py [--data data_v2] [--out results_v2] [--clock-correct]
  venv/bin/python scripts/aggregate_v2.py --data data_v2 --list-clock-steps
"""

import argparse
import collections
import csv
import glob
import json
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIBRATION = os.path.join(ROOT, "simulated_endpoint", "calibration_v2.json")
SYNC_SINGLE = {"flask", "django"}
MULTI = {"flask_mw", "django_mw"}
LATE_INFLIGHT_THRESHOLD = 0.01
STREAM_RULE = ("stream connection success = HTTP 200 AND {n} content chunks AND done event seen "
               "(test_stream.py raises on a non-200 status before reading the body, so done seen implies 200; "
               "a stream failing any condition counts as failed)")
PCR_RULE = "pipeline completion = HTTP 200 AND all 4 stage timings present in the response (stages_logged = 4)"
CLOCK_FLAGS = ("clock_step_detected", "clock_rate_unstable", "clock_rate_off_nominal")
RATE_KEYS = ("locust_rps", "throughput_fixed_window", "throughput_completion_rate", "ceiling_rps")
UNCORRECTED_MS = ("cpu_ms_per_request", "clock_step_ms")


class DataError(SystemExit):
    pass


def read_csv(path):
    """(fieldnames, rows); ([], []) if the file does not exist."""
    if not os.path.exists(path):
        return [], []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = list(r)
        return r.fieldnames or [], rows


def require(fields, needed, path):
    missing = [k for k in needed if k not in fields]
    if missing:
        raise DataError(f"{path}: missing monotonic column(s) {missing}. The data predates v2-freeze; "
                        "windows must not use the wall clock. Re-run with the current harness.")


def fnum(v):
    return None if v in (None, "", "None", "N/A") else float(v)


def pct(values, p):
    """Linear-interpolated percentile of raw values (p in 0..100)."""
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def pcts(m, name, values):
    """name_p50_ms, name_p95_ms, name_p99_ms (p99 only if n >= 100)."""
    m[f"{name}_p50_ms"] = pct(values, 50)
    m[f"{name}_p95_ms"] = pct(values, 95)
    m[f"{name}_p99_ms"] = pct(values, 99) if len(values) >= 100 else None


def med(values):
    v = [x for x in values if x is not None]
    return statistics.median(v) if v else None


def model_of(fw):
    if fw in MULTI:
        return "sync_multi"
    return "sync_single" if fw in SYNC_SINGLE else "async"


def ceiling(fw, c, s_ep, workers):
    if fw in SYNC_SINGLE:
        return 1 / s_ep
    if fw in MULTI:
        return min(c, workers) / s_ep
    return c / s_ep


def failure_type(exception):
    text = exception or ""
    m = re.search(r"HTTP (\d{3})", text)
    if m:
        return f"HTTP {m.group(1)}"
    if "empty answer" in text:
        return "empty answer"
    if "Invalid JSON" in text:
        return "invalid JSON"
    m = re.match(r"\s*([A-Za-z_][\w.]*)\(", text)
    return m.group(1) if m else (text[:40] or "unknown")


def join_stream(prefix, req):
    """[(requests row, stream_metrics row)] for SSE rows, verified pair by pair."""
    path = prefix + "_stream_metrics.csv"
    _f, sm = read_csv(path)
    sse = [r for r in req if r["request_type"] == "SSE"]
    if len(sse) != len(sm):
        raise DataError(f"{path}: {len(sm)} stream rows vs {len(sse)} SSE rows in _requests.csv; cannot pair")
    for i, (r, s) in enumerate(zip(sse, sm)):
        if float(s["total_time_ms"]) != float(r["response_time_ms"]) or int(s["token_count"]) != int(
                r["response_length"]):
            raise DataError(f"{path}: row {i} does not match _requests.csv (total {s['total_time_ms']} vs "
                            f"{r['response_time_ms']}, tokens {s['token_count']} vs {r['response_length']})")
    return list(zip(sse, sm))


def monitor_window(path, t0, stop):
    """(fieldnames, rows, [(mono, cpu) in (t0, stop]], cpu seconds in the window)."""
    fields, rows = read_csv(path)
    if rows:
        require(fields, ["mono"], path)
    loaded, cpu_s, prev = [], 0.0, None
    for r in rows:
        ts, cpu = float(r["mono"]), float(r["cpu_percent"])
        if prev is not None and t0 <= ts <= stop:
            loaded.append(cpu)
            cpu_s += cpu / 100 * (ts - prev)
        prev = ts
    return rows, loaded, cpu_s


def run_metrics(prefix, fw, ep, c, s_ep, cal, meta):
    lmeta = json.load(open(prefix + "_locust_meta.json"))
    if lmeta.get("first_user_start_mono") is None or lmeta.get("stop_mono") is None:
        raise DataError(f"{prefix}_locust_meta.json: no first_user_start_mono / stop_mono (data predates "
                        "v2-freeze). Re-run with the current harness.")
    fields, req = read_csv(prefix + "_requests.csv")
    require(fields, ["start_mono", "end_mono", "http_status", "stages_logged"], prefix + "_requests.csv")
    ok = [r for r in req if r["success"] == "True"]
    lat_all = [float(r["response_time_ms"]) for r in ok]
    t0, stop = lmeta["first_user_start_mono"], lmeta["stop_mono"]
    w_lo, w_hi = t0 + 2 * s_ep, stop
    in_win = [r for r in ok if w_lo <= float(r["end_mono"]) <= w_hi]
    lat_win = [float(r["response_time_ms"]) for r in in_win]
    x_fixed = len(in_win) / (w_hi - w_lo) if w_hi > w_lo else None

    m = {"framework": fw, "endpoint": ep, "concurrency": c, "run": meta["run"], "model": model_of(fw),
         "service_time_s": s_ep, "completions": len(ok), "failures": len(req) - len(ok),
         "window_s": round(w_hi - w_lo, 3)}

    _sf, stats = read_csv(prefix + "_stats.csv")
    stats = [r for r in stats if r["Name"] == "Aggregated"]
    m["locust_rps"] = fnum(stats[0]["Requests/s"]) if stats else None
    m["throughput_fixed_window"] = x_fixed
    workers = len(meta.get("worker_pids", [])) or 1
    m["workers"] = workers
    m["ceiling_rps"] = ceiling(fw, c, s_ep, workers)
    m["share_of_ceiling"] = x_fixed / m["ceiling_rps"] if x_fixed is not None else None
    ends = sorted(float(r["end_mono"]) for r in in_win)
    x_rate = (len(ends) - 1) / (ends[-1] - ends[0]) if len(ends) >= 2 and ends[-1] > ends[0] else None
    m["throughput_completion_rate"] = x_rate
    m["share_of_ceiling_completion_rate"] = x_rate / m["ceiling_rps"] if x_rate is not None else None

    x_ss = x_rate if x_rate is not None else x_fixed
    mean_win = statistics.mean(lat_win) / 1000 if lat_win else None
    m["closed_system_consistency"] = mean_win * x_ss / c if (mean_win and x_ss) else None

    n_bins = int(w_hi - w_lo) if w_hi > w_lo else 0
    if n_bins and x_ss:
        counts = [0] * n_bins
        for e in ends:
            b = int(e - w_lo)
            if b < n_bins:
                counts[b] += 1
        m["min_1s_completions"] = min(counts)
        m["min_1s_completion_ratio"] = min(counts) / x_ss
    else:
        m["min_1s_completions"] = m["min_1s_completion_ratio"] = None

    m["latency_p50_ms"] = pct(lat_all, 50)
    m["latency_p90_ms"] = pct(lat_all, 90)
    m["latency_p95_ms"] = pct(lat_all, 95)
    m["latency_p99_ms"] = pct(lat_all, 99) if len(lat_all) >= 100 else None
    m["latency_mean_ms"] = statistics.mean(lat_all) if lat_all else None

    finished = [r for r in req if t0 <= float(r["end_mono"]) <= stop]
    failed = [r for r in finished if r["success"] != "True"]
    m["finished_loaded"] = len(finished)
    m["error_rate_pct"] = len(failed) / len(finished) * 100 if finished else None
    m["failures_by_type"] = json.dumps(dict(sorted(collections.Counter(
        failure_type(r["exception"]) for r in failed).items())))

    ifields, inflight = read_csv(prefix + "_inflight.csv")
    if inflight:
        require(ifields, ["issued_mono"], prefix + "_inflight.csv")
    ages = [float(r["age_at_stop_s"]) * 1000 for r in inflight]
    m["inflight_at_stop"] = len(inflight)
    m["censoring_fraction"] = len(inflight) / (len(ok) + len(inflight)) if (ok or inflight) else None
    p95 = m["latency_p95_ms"]
    late = sum(1 for a in ages if p95 is not None and a > p95)
    m["late_inflight"] = late
    m["max_inflight_age_ms"] = max(ages) if ages else None
    m["percentiles_censored"] = bool(ok) and late / len(ok) >= LATE_INFLIGHT_THRESHOLD

    # Interactive response time law, zero think time (estimate, not a check)
    m["response_law_R_ms"] = c / x_ss * 1000 if x_ss else None
    if fw in SYNC_SINGLE and x_ss:
        service_ms = 1000 / x_ss
    elif fw in MULTI and x_ss:
        service_ms = min(c, workers) / x_ss * 1000
    else:
        service_ms = s_ep * 1000
    m["derived_queue_wait_ms"] = (max(0.0, m["response_law_R_ms"] - service_ms)
                                  if m["response_law_R_ms"] is not None else None)

    if ep == "stream":
        pairs = join_stream(prefix, req)
        chunks = int(cal["stream_chunk_count"])
        loaded_pairs = [(r, s) for r, s in pairs if t0 <= float(r["end_mono"]) <= stop]
        good = [1 for r, s in loaded_pairs
                if s["success"] == "True" and int(s["token_count"]) == chunks
                and str(r["http_status"]) in ("", "200")]
        m["stream_finished_loaded"] = len(loaded_pairs)
        m["stream_csr_pct"] = len(good) / len(loaded_pairs) * 100 if loaded_pairs else None
        sm = [s for _r, s in pairs if s["success"] == "True"]
        pcts(m, "ttft", [v for v in (fnum(s["ttft_ms"]) for s in sm) if v is not None])
        pcts(m, "tpot", [v for v in (fnum(s["tpot_ms"]) for s in sm) if v is not None])
        m["token_count_p50"] = med([fnum(s["token_count"]) for s in sm])
        m["token_count_min"] = min((int(s["token_count"]) for s in sm), default=None)
        m["token_count_max"] = max((int(s["token_count"]) for s in sm), default=None)
        m["chunks_ok_pct"] = (sum(1 for s in sm if int(s["token_count"]) == chunks) / len(sm) * 100) if sm else None
    if ep == "pipeline":
        m["pipeline_completion_pct"] = (sum(1 for r in finished if str(r["http_status"]) == "200"
                                            and str(r["stages_logged"]) == "4") / len(finished) * 100
                                        if finished else None)
        _pf, pm = read_csv(prefix + "_pipeline_metrics.csv")
        pm = [r for r in pm if r["completed"] == "True"]
        for k in ("stage1", "stage2", "stage3", "stage4"):
            pcts(m, k, [v for v in (fnum(r[f"{k}_ms"]) for r in pm) if v is not None])
        pcts(m, "e2e_server", [v for v in (fnum(r["e2e_pipeline_ms"]) for r in pm) if v is not None])
        pcts(m, "e2e_client", lat_all)

    res, loaded, cpu_s = monitor_window(prefix + "_resources.csv", t0, stop)
    m["idle_rss_mb"], m["idle_uss_mb"] = meta.get("idle_rss_mb"), meta.get("idle_uss_mb")
    m["idle_drift"] = meta.get("idle_drift")
    m["idle_rss_diff_mb"], m["idle_uss_diff_mb"] = meta.get("idle_rss_diff_mb"), meta.get("idle_uss_diff_mb")
    if res:
        m["peak_rss_mb"] = max(float(r["rss_mb"]) for r in res)
        m["peak_uss_mb"] = max(float(r["uss_mb"]) for r in res)
        m["rss_growth_mb"] = m["peak_rss_mb"] - m["idle_rss_mb"] if m["idle_rss_mb"] is not None else None
        m["uss_growth_mb"] = m["peak_uss_mb"] - m["idle_uss_mb"] if m["idle_uss_mb"] is not None else None
        m["cpu_mean_loaded_pct"] = statistics.mean(loaded) if loaded else None
        m["cpu_max_loaded_pct"] = max(loaded) if loaded else None
        done_loaded = sum(1 for r in ok if t0 <= float(r["end_mono"]) <= stop)
        m["cpu_ms_per_request"] = cpu_s / done_loaded * 1000 if done_loaded else None

    sim, sim_loaded, _ = monitor_window(prefix + "_sim_monitor.csv", t0, stop)
    if sim:
        m["sim_cpu_mean_pct"] = statistics.mean(sim_loaded) if sim_loaded else None
        m["sim_cpu_p95_pct"] = pct(sim_loaded, 95)
        m["sim_peak_uss_mb"] = max(float(r["uss_mb"]) for r in sim)
    m["monitor_cpu_pct"] = meta.get("monitor_cpu_pct")
    m["sim_monitor_cpu_pct"] = meta.get("sim_monitor_cpu_pct")

    for k in ("clock_rate_ratio", "clock_rate_uncertainty", "clock_rate_half_diff", "clock_rate_unstable",
              "clock_rate_off_nominal", "clock_step_detected", "clock_step_ms"):
        m[k] = meta.get(k)
    return m


METRICS = [
    "completions", "failures", "finished_loaded", "error_rate_pct", "locust_rps", "throughput_fixed_window",
    "throughput_completion_rate", "ceiling_rps", "share_of_ceiling", "share_of_ceiling_completion_rate",
    "closed_system_consistency", "min_1s_completions", "min_1s_completion_ratio",
    "latency_p50_ms", "latency_p90_ms", "latency_p95_ms", "latency_p99_ms", "latency_mean_ms",
    "inflight_at_stop", "censoring_fraction", "late_inflight", "max_inflight_age_ms",
    "response_law_R_ms", "derived_queue_wait_ms", "derived_ttft_ms",
    "stream_finished_loaded", "stream_csr_pct", "chunks_ok_pct", "ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms",
    "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms", "token_count_p50",
    "pipeline_completion_pct", "stage1_p50_ms", "stage1_p95_ms", "stage1_p99_ms", "stage2_p50_ms", "stage2_p95_ms",
    "stage2_p99_ms", "stage3_p50_ms", "stage3_p95_ms", "stage3_p99_ms", "stage4_p50_ms", "stage4_p95_ms",
    "stage4_p99_ms", "e2e_server_p50_ms", "e2e_server_p95_ms", "e2e_server_p99_ms",
    "e2e_client_p50_ms", "e2e_client_p95_ms", "e2e_client_p99_ms",
    "cpu_mean_loaded_pct", "cpu_max_loaded_pct", "cpu_ms_per_request",
    "idle_rss_mb", "peak_rss_mb", "rss_growth_mb", "idle_uss_mb", "peak_uss_mb", "uss_growth_mb",
    "sim_cpu_mean_pct", "sim_cpu_p95_pct", "sim_peak_uss_mb", "monitor_cpu_pct", "sim_monitor_cpu_pct",
    "clock_rate_ratio", "clock_rate_uncertainty", "clock_rate_half_diff", "clock_step_ms",
]


def clock_correct(m):
    """Copy of a per-run row with durations / ratio and rates x ratio."""
    out = dict(m)
    ratio = m.get("clock_rate_ratio")
    if not ratio:
        out["clock_correction"] = "unavailable"
        return out
    for k, v in m.items():
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if (k.endswith("_ms") and k not in UNCORRECTED_MS) or k == "window_s":
            out[k] = v / ratio
        elif k in RATE_KEYS:
            out[k] = v * ratio
    out["clock_correction"] = "applied"
    return out


def write_outputs(runs, out, suffix):
    keys = sorted({k for m in runs for k in m}, key=lambda k: (k not in ("framework", "endpoint", "concurrency",
                                                                         "run", "model", "clock_correction"), k))
    with open(os.path.join(out, f"per_run_v2{suffix}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(runs)

    groups = {}
    for m in runs:
        groups.setdefault((m["framework"], m["endpoint"], m["concurrency"]), []).append(m)
    long_rows, wide_rows = [], []
    for (fw, ep, c), ms in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        wide = {"framework": fw, "endpoint": ep, "concurrency": c, "model": model_of(fw), "n_runs": len(ms),
                "clock_correction": ";".join(sorted({m["clock_correction"] for m in ms})),
                "percentiles_censored_runs": sum(1 for m in ms if m["percentiles_censored"]),
                "idle_drift_runs": sum(1 for m in ms if m.get("idle_drift")),
                "clock_flagged_runs": sum(1 for m in ms if any(m.get(k) is True for k in CLOCK_FLAGS))}
        fails = collections.Counter()
        for m in ms:
            fails.update(json.loads(m.get("failures_by_type") or "{}"))
        wide["failures_by_type"] = json.dumps(dict(sorted(fails.items())))
        for k in ("idle_rss_mb", "idle_uss_mb"):
            vals = [m[k] for m in ms if m.get(k) is not None]
            wide[k.replace("_mb", "_spread_mb")] = round(max(vals) - min(vals), 4) if vals else None
        ratios = [m["clock_rate_ratio"] for m in ms if m.get("clock_rate_ratio") is not None]
        wide["clock_rate_ratio_mean"] = statistics.mean(ratios) if ratios else None
        wide["clock_rate_ratio_spread"] = max(ratios) - min(ratios) if ratios else None
        for k in METRICS:
            vals = [m[k] for m in ms if m.get(k) is not None]
            if not vals:
                continue
            row = {"framework": fw, "endpoint": ep, "concurrency": c, "metric": k,
                   "median": statistics.median(vals), "min": min(vals), "max": max(vals), "n_runs": len(vals)}
            if k.startswith("latency_") or k.startswith("ttft") or k.startswith("e2e_client"):
                row["censored"] = wide["percentiles_censored_runs"] > 0
            long_rows.append(row)
            wide[k] = round(statistics.median(vals), 4)
        wide_rows.append(wide)

    with open(os.path.join(out, f"summary_v2_long{suffix}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["framework", "endpoint", "concurrency", "metric", "median", "min", "max",
                                          "n_runs", "censored"])
        w.writeheader()
        w.writerows(long_rows)
    wide_keys = ["framework", "endpoint", "concurrency", "model", "n_runs", "clock_correction",
                 "percentiles_censored_runs", "idle_drift_runs", "clock_flagged_runs", "failures_by_type",
                 "idle_rss_spread_mb", "idle_uss_spread_mb", "clock_rate_ratio_mean", "clock_rate_ratio_spread"] + METRICS
    with open(os.path.join(out, f"summary_v2{suffix}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=wide_keys)
        w.writeheader()
        w.writerows(wide_rows)
    return groups


def list_clock_steps(data):
    flagged = 0
    for meta_path in sorted(glob.glob(os.path.join(data, "*", "*", "c*_run*_meta.json"))):
        meta = json.load(open(meta_path))
        flags = [k for k in CLOCK_FLAGS if meta.get(k) is True]
        if flags:
            flagged += 1
            print(f"{os.path.relpath(meta_path, ROOT)}: {', '.join(flags)} (status {meta.get('status')}, "
                  f"clock_step_ms {meta.get('clock_step_ms')}, clock_rate_ratio {meta.get('clock_rate_ratio')}, "
                  f"half_diff {meta.get('clock_rate_half_diff')})")
    print(f"{flagged} flagged run(s); redo with scripts/run_matrix.py --redo-clock-steps")


def fmt(v, spec):
    return "n/a" if v is None else format(v, spec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_v2")
    ap.add_argument("--out", default="results_v2")
    ap.add_argument("--clock-correct", action="store_true",
                    help="also write *_clockcorrected.csv (durations / clock_rate_ratio, rates x ratio)")
    ap.add_argument("--list-clock-steps", action="store_true",
                    help="list runs with clock_step_detected, clock_rate_unstable or clock_rate_off_nominal")
    a = ap.parse_args()
    data, out = os.path.join(ROOT, a.data), os.path.join(ROOT, a.out)
    if a.list_clock_steps:
        list_clock_steps(data)
        return
    os.makedirs(out, exist_ok=True)
    cal = json.load(open(CALIBRATION))["values"]

    runs = []
    for meta_path in sorted(glob.glob(os.path.join(data, "*", "*", "c*_run*_meta.json"))):
        meta = json.load(open(meta_path))
        if meta.get("status") != "complete":
            continue
        fw, ep = meta["framework"], meta["endpoint"]
        prefix = meta_path[:-len("_meta.json")]
        c = int(re.search(r"c(\d+)_run", meta_path).group(1))
        m = run_metrics(prefix, fw, ep, c, meta["service_time_s"], cal, meta)
        m["clock_correction"] = "uncorrected"
        runs.append(m)

    # derived TTFT for stream: queue wait + uncontended TTFT (same framework, c = 1, else calibration)
    ttft_c1 = {}
    for m in runs:
        if m["endpoint"] == "stream" and m["concurrency"] == 1 and m.get("ttft_p50_ms") is not None:
            ttft_c1.setdefault(m["framework"], []).append(m["ttft_p50_ms"])
    for m in runs:
        if m["endpoint"] == "stream" and m.get("derived_queue_wait_ms") is not None:
            base = med(ttft_c1.get(m["framework"], [])) or cal["stream_first_chunk_delay_s"] * 1000
            m["derived_ttft_ms"] = m["derived_queue_wait_ms"] + base

    groups = write_outputs(runs, out, "")
    if a.clock_correct:
        write_outputs([clock_correct(m) for m in runs], out, "_clockcorrected")
    with open(os.path.join(out, "metric_rules.txt"), "w") as f:
        f.write(STREAM_RULE.format(n=int(cal["stream_chunk_count"])) + "\n" + PCR_RULE + "\n"
                "closed_system_consistency = mean latency (steady window) x completion rate / c\n")

    ratios = [m["clock_rate_ratio"] for m in runs if m.get("clock_rate_ratio") is not None]
    with open(os.path.join(out, "clock_rate_summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["framework", "endpoint", "concurrency", "n_runs_with_ratio", "mean", "min", "max", "spread"])
        for (fw, ep, c), ms in sorted(groups.items()):
            r = [m["clock_rate_ratio"] for m in ms if m.get("clock_rate_ratio") is not None]
            w.writerow([fw, ep, c, len(r)] + ([statistics.mean(r), min(r), max(r), max(r) - min(r)] if r else
                                              [None] * 4))
        w.writerow(["ALL", "", "", len(ratios)] + ([statistics.mean(ratios), min(ratios), max(ratios),
                                                    max(ratios) - min(ratios)] if ratios else [None] * 4))

    print(f"{len(runs)} runs in {len(groups)} configurations -> {os.path.relpath(out, ROOT)}/ (uncorrected"
          + ("; *_clockcorrected.csv also written)" if a.clock_correct else ")"))
    print("Rule: " + STREAM_RULE.format(n=int(cal["stream_chunk_count"])))
    print("Rule: " + PCR_RULE)
    for (fw, ep, c), ms in sorted(groups.items()):
        s = {k: med([m.get(k) for m in ms]) for k in (
            "throughput_fixed_window", "share_of_ceiling_completion_rate", "latency_p50_ms",
            "closed_system_consistency", "censoring_fraction", "error_rate_pct", "stream_csr_pct",
            "pipeline_completion_pct", "clock_rate_ratio")}
        cens = sum(1 for m in ms if m["percentiles_censored"])
        extra = (f" csr={fmt(s['stream_csr_pct'], '.1f')}%" if ep == "stream" else
                 f" pcr={fmt(s['pipeline_completion_pct'], '.1f')}%" if ep == "pipeline" else "")
        print(f"  {fw:9} {ep:9} c{c:<3} runs={len(ms)} X={fmt(s['throughput_fixed_window'], '.3f')} "
              f"share(rate)={fmt(s['share_of_ceiling_completion_rate'], '.3f')} "
              f"p50={fmt(s['latency_p50_ms'], '.0f')}ms consistency={fmt(s['closed_system_consistency'], '.3f')} "
              f"err={fmt(s['error_rate_pct'], '.2f')}%{extra} cens_frac={fmt(s['censoring_fraction'], '.2f')} "
              f"censored_runs={cens} clock={fmt(s['clock_rate_ratio'], '.5f')}")
    if ratios:
        print(f"clock_rate_ratio over {len(ratios)} runs: mean {statistics.mean(ratios):.5f}, "
              f"min {min(ratios):.5f}, max {max(ratios):.5f}")
    flagged = [m for m in runs if any(m.get(k) is True for k in CLOCK_FLAGS)]
    drift = [m for m in runs if m.get("idle_drift")]
    for label, lst in (("clock-flagged", flagged), ("idle-drift", drift)):
        if lst:
            print(f"{label} runs: " + ", ".join(f"{m['framework']}/{m['endpoint']}/c{m['concurrency']}/run{m['run']}"
                                                for m in lst))


if __name__ == "__main__":
    try:
        main()
    except DataError as e:
        sys.exit(f"aggregate_v2: {e}")
