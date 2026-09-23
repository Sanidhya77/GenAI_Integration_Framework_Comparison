"""
Aggregation for the v2 rerun (data_v2/ -> results_v2/). The thesis aggregation,
scripts/aggregate_data.py, is unchanged.

One rule for every metric: compute the value per run, then report the median over
runs with the run-to-run spread (min, max, number of runs).

Per framework, endpoint, concurrency and run:
  throughput      Locust Requests/s (continuity with the thesis) and fixed-window
                  throughput from the per-request log: completions ending in
                  [first user start + 2 S_ep, stop] divided by the window length
                  plus completion rate (n - 1) / (last - first completion) in the same
                  window, which avoids the +-1 completion quantisation of count / window
  ceiling         async: c / S_ep; single sync worker: 1 / S_ep;
                  multi-worker: min(c, workers) / S_ep; share reported for both
                  estimators (share_of_ceiling, share_of_ceiling_completion_rate)
  Little's law    c / mean latency (requests ending in the window) vs X, where X is the
                  completion rate (count / window if fewer than 2 completions)
  latency         p50, p90, p95, mean from the per-request log (not Locust buckets);
                  p99 omitted when n < 100
  censoring       completions, in-flight at stop, censoring fraction
                  inflight / (completions + inflight); late in-flight = in-flight
                  requests already older than the observed p95; the run's
                  percentiles are flagged censored when late in-flight >= 1 % of
                  completions
  response law    R = N / X (interactive response time law, zero think time,
                  N = c users, X as for Little's law); derived queue wait
                  R - service and derived TTFT = wait + uncontended TTFT (stream);
                  checked against measured mean latency at c = 1, 5, 10
  stream          TTFT, TPOT, token count (medians per run)
  pipeline        Stages 1 to 4 and server-side E2E (within one execution model only),
                  client-side E2E (Locust response time) for cross-model comparison
  resources       CPU mean over the loaded window [first user start, stop] only,
                  CPU seconds per completed request, idle RSS/USS after warm-up
                  (first monitor sample), peak, growth

Usage:
  venv/bin/python scripts/aggregate_v2.py [--data data_v2] [--out results_v2]
"""

import argparse
import csv
import glob
import json
import os
import re
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIBRATION = os.path.join(ROOT, "simulated_endpoint", "calibration_v2.json")
SYNC_SINGLE = {"flask", "django"}
MULTI = {"flask_mw", "django_mw"}
LATE_INFLIGHT_THRESHOLD = 0.01


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


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


def run_metrics(prefix, fw, ep, c, s_ep, cal):
    meta = json.load(open(prefix + "_meta.json"))
    lmeta = json.load(open(prefix + "_locust_meta.json"))
    req = read_csv(prefix + "_requests.csv")
    ok = [r for r in req if r["success"] == "True"]
    lat_all = [float(r["response_time_ms"]) for r in ok]
    t0, stop = lmeta["first_user_start_ts"], lmeta["stop_ts"]
    w_lo, w_hi = t0 + 2 * s_ep, stop
    in_win = [r for r in ok if w_lo <= float(r["end_ts"]) <= w_hi]
    lat_win = [float(r["response_time_ms"]) for r in in_win]
    x_fixed = len(in_win) / (w_hi - w_lo) if w_hi > w_lo else None

    m = {"framework": fw, "endpoint": ep, "concurrency": c, "run": meta["run"], "model": model_of(fw),
         "service_time_s": s_ep, "completions": len(ok), "failures": len(req) - len(ok),
         "window_s": round(w_hi - w_lo, 3)}

    stats = [r for r in read_csv(prefix + "_stats.csv") if r["Name"] == "Aggregated"]
    m["locust_rps"] = fnum(stats[0]["Requests/s"]) if stats else None
    m["throughput_fixed_window"] = x_fixed
    workers = len(meta.get("worker_pids", [])) or 1
    m["workers"] = workers
    m["ceiling_rps"] = ceiling(fw, c, s_ep, workers)
    m["share_of_ceiling"] = x_fixed / m["ceiling_rps"] if x_fixed is not None else None
    ends = sorted(float(r["end_ts"]) for r in in_win)
    x_rate = (len(ends) - 1) / (ends[-1] - ends[0]) if len(ends) >= 2 and ends[-1] > ends[0] else None
    m["throughput_completion_rate"] = x_rate
    m["share_of_ceiling_completion_rate"] = x_rate / m["ceiling_rps"] if x_rate is not None else None

    x_ss = x_rate if x_rate is not None else x_fixed
    mean_win = statistics.mean(lat_win) / 1000 if lat_win else None
    m["littles_law_rps"] = c / mean_win if mean_win else None
    m["littles_ratio"] = (m["littles_law_rps"] / x_ss) if (mean_win and x_ss) else None

    m["latency_p50_ms"] = pct(lat_all, 50)
    m["latency_p90_ms"] = pct(lat_all, 90)
    m["latency_p95_ms"] = pct(lat_all, 95)
    m["latency_p99_ms"] = pct(lat_all, 99) if len(lat_all) >= 100 else None
    m["latency_mean_ms"] = statistics.mean(lat_all) if lat_all else None

    inflight = read_csv(prefix + "_inflight.csv")
    ages = [float(r["age_at_stop_s"]) * 1000 for r in inflight]
    m["inflight_at_stop"] = len(inflight)
    m["censoring_fraction"] = len(inflight) / (len(ok) + len(inflight)) if (ok or inflight) else None
    p95 = m["latency_p95_ms"]
    late = sum(1 for a in ages if p95 is not None and a > p95)
    m["late_inflight"] = late
    m["max_inflight_age_ms"] = max(ages) if ages else None
    m["percentiles_censored"] = bool(ok) and late / len(ok) >= LATE_INFLIGHT_THRESHOLD

    # Interactive response time law, zero think time
    m["response_law_R_ms"] = c / x_ss * 1000 if x_ss else None
    if fw in SYNC_SINGLE and x_ss:
        service_ms = 1000 / x_ss
    elif fw in MULTI and x_ss:
        service_ms = min(c, workers) / x_ss * 1000
    else:
        service_ms = s_ep * 1000
    m["derived_queue_wait_ms"] = (max(0.0, m["response_law_R_ms"] - service_ms)
                                  if m["response_law_R_ms"] is not None else None)
    m["response_law_vs_measured_mean"] = (m["response_law_R_ms"] / (mean_win * 1000)
                                          if (mean_win and m["response_law_R_ms"]) else None)

    if ep == "stream":
        sm = [r for r in read_csv(prefix + "_stream_metrics.csv") if r["success"] == "True"]
        m["ttft_p50_ms"] = med([fnum(r["ttft_ms"]) for r in sm])
        m["tpot_p50_ms"] = med([fnum(r["tpot_ms"]) for r in sm])
        m["token_count_p50"] = med([fnum(r["token_count"]) for r in sm])
        m["token_count_min"] = min((int(r["token_count"]) for r in sm), default=None)
        m["token_count_max"] = max((int(r["token_count"]) for r in sm), default=None)
    if ep == "pipeline":
        pm = [r for r in read_csv(prefix + "_pipeline_metrics.csv") if r["completed"] == "True"]
        for k in ("stage1_ms", "stage2_ms", "stage3_ms", "stage4_ms"):
            m[f"{k[:-3]}_p50_ms"] = med([fnum(r[k]) for r in pm])
        m["e2e_server_p50_ms"] = med([fnum(r["e2e_pipeline_ms"]) for r in pm])
        m["e2e_client_p50_ms"] = m["latency_p50_ms"]

    res = read_csv(prefix + "_resources.csv")
    if res:
        m["idle_rss_mb"] = float(res[0]["rss_mb"])
        m["idle_uss_mb"] = float(res[0]["uss_mb"])
        m["peak_rss_mb"] = max(float(r["rss_mb"]) for r in res)
        m["peak_uss_mb"] = max(float(r["uss_mb"]) for r in res)
        m["rss_growth_mb"] = m["peak_rss_mb"] - m["idle_rss_mb"]
        m["uss_growth_mb"] = m["peak_uss_mb"] - m["idle_uss_mb"]
        loaded, cpu_s, prev = [], 0.0, None
        for r in res:
            ts, cpu = float(r["timestamp"]), float(r["cpu_percent"])
            if prev is not None and t0 <= ts <= stop:
                loaded.append(cpu)
                cpu_s += cpu / 100 * (ts - prev)
            prev = ts
        m["cpu_mean_loaded_pct"] = statistics.mean(loaded) if loaded else None
        done_loaded = sum(1 for r in ok if t0 <= float(r["end_ts"]) <= stop)
        m["cpu_ms_per_request"] = cpu_s / done_loaded * 1000 if done_loaded else None
    return m


METRICS = [
    "completions", "failures", "locust_rps", "throughput_fixed_window", "throughput_completion_rate", "ceiling_rps",
    "share_of_ceiling", "share_of_ceiling_completion_rate",
    "littles_law_rps", "littles_ratio", "latency_p50_ms", "latency_p90_ms", "latency_p95_ms", "latency_p99_ms",
    "latency_mean_ms", "inflight_at_stop", "censoring_fraction", "late_inflight", "max_inflight_age_ms",
    "response_law_R_ms", "derived_queue_wait_ms", "derived_ttft_ms", "response_law_vs_measured_mean",
    "ttft_p50_ms", "tpot_p50_ms", "token_count_p50", "stage1_p50_ms", "stage2_p50_ms", "stage3_p50_ms",
    "stage4_p50_ms", "e2e_server_p50_ms", "e2e_client_p50_ms", "cpu_mean_loaded_pct", "cpu_ms_per_request",
    "idle_rss_mb", "peak_rss_mb", "rss_growth_mb", "idle_uss_mb", "peak_uss_mb", "uss_growth_mb",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_v2")
    ap.add_argument("--out", default="results_v2")
    a = ap.parse_args()
    data, out = os.path.join(ROOT, a.data), os.path.join(ROOT, a.out)
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
        runs.append(run_metrics(prefix, fw, ep, c, meta["service_time_s"], cal))

    # derived TTFT for stream: queue wait + uncontended TTFT (same framework, c = 1, else calibration)
    ttft_c1 = {}
    for m in runs:
        if m["endpoint"] == "stream" and m["concurrency"] == 1 and m.get("ttft_p50_ms") is not None:
            ttft_c1.setdefault(m["framework"], []).append(m["ttft_p50_ms"])
    for m in runs:
        if m["endpoint"] == "stream" and m.get("derived_queue_wait_ms") is not None:
            base = med(ttft_c1.get(m["framework"], [])) or cal["stream_first_chunk_delay_s"] * 1000
            m["derived_ttft_ms"] = m["derived_queue_wait_ms"] + base

    keys = sorted({k for m in runs for k in m}, key=lambda k: (k not in ("framework", "endpoint", "concurrency",
                                                                         "run", "model"), k))
    with open(os.path.join(out, "per_run_v2.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(runs)

    groups = {}
    for m in runs:
        groups.setdefault((m["framework"], m["endpoint"], m["concurrency"]), []).append(m)
    long_rows, wide_rows = [], []
    for (fw, ep, c), ms in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        wide = {"framework": fw, "endpoint": ep, "concurrency": c, "model": model_of(fw), "n_runs": len(ms),
                "percentiles_censored_runs": sum(1 for m in ms if m["percentiles_censored"])}
        for k in METRICS:
            vals = [m[k] for m in ms if m.get(k) is not None]
            if not vals:
                continue
            row = {"framework": fw, "endpoint": ep, "concurrency": c, "metric": k,
                   "median": statistics.median(vals), "min": min(vals), "max": max(vals), "n_runs": len(vals)}
            if k.startswith("latency_") or k.startswith("ttft") or k == "e2e_client_p50_ms":
                row["censored"] = wide["percentiles_censored_runs"] > 0
            long_rows.append(row)
            wide[k] = round(statistics.median(vals), 4)
        wide_rows.append(wide)

    with open(os.path.join(out, "summary_v2_long.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["framework", "endpoint", "concurrency", "metric", "median", "min", "max",
                                          "n_runs", "censored"])
        w.writeheader()
        w.writerows(long_rows)
    wide_keys = ["framework", "endpoint", "concurrency", "model", "n_runs", "percentiles_censored_runs"] + METRICS
    with open(os.path.join(out, "summary_v2.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=wide_keys)
        w.writeheader()
        w.writerows(wide_rows)

    # R = N / X check at the uncensored levels
    check = [m for m in runs if m["concurrency"] in (1, 5, 10) and m.get("response_law_vs_measured_mean")
             and not m["percentiles_censored"]]
    print(f"{len(runs)} runs in {len(groups)} configurations -> {os.path.relpath(out, ROOT)}/")
    for (fw, ep, c), ms in sorted(groups.items()):
        s = {k: med([m.get(k) for m in ms]) for k in ("throughput_fixed_window", "share_of_ceiling_completion_rate",
                                                      "latency_p50_ms", "littles_ratio", "censoring_fraction")}
        cens = sum(1 for m in ms if m["percentiles_censored"])
        print(f"  {fw:9} {ep:9} c{c:<3} runs={len(ms)} X={s['throughput_fixed_window']:.3f} "
              f"share(rate)={s['share_of_ceiling_completion_rate']:.3f} p50={s['latency_p50_ms']:.0f}ms "
              f"little={s['littles_ratio']:.3f} cens_frac={s['censoring_fraction']:.2f} censored_runs={cens}")
    if check:
        ratios = [m["response_law_vs_measured_mean"] for m in check]
        print(f"R = N/X vs measured mean at c = 1, 5, 10: median ratio {statistics.median(ratios):.3f}, "
              f"range {min(ratios):.3f} to {max(ratios):.3f} over {len(ratios)} uncensored runs")


if __name__ == "__main__":
    main()
