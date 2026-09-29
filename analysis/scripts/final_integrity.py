"""
Integrity summary for RESULTS_FINAL (read-only): all runs in data_v2/ (main matrix + multi-worker)
and data_v2_real/ (Phases A, B, C). Prints counts, statuses, flags, clock-rate statistics, idle
drift, run spans, provenance hashes, warm-ups, Locust failure rows, and the same-class framework
differences in the aggregate medians (results_v2/summary_v2_long.csv).
"""

import csv
import datetime
import glob
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLAGS = ("clock_step_detected", "clock_rate_unstable", "clock_rate_off_nominal")


def utc(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")


def rows(path):
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dataset(name, metas):
    print(f"\n== {name}: {len(metas)} meta.json")
    st = {}
    for p, m in metas:
        st[m.get("status")] = st.get(m.get("status"), 0) + 1
    print("  status:", st)
    flagged = [(p, [k for k in FLAGS if m.get(k) is True]) for p, m in metas if any(m.get(k) is True for k in FLAGS)]
    print("  clock-flagged:", len(flagged), flagged[:5])
    r = [m["clock_rate_ratio"] for _p, m in metas if m.get("clock_rate_ratio") is not None]
    u = [m["clock_rate_uncertainty"] for _p, m in metas if m.get("clock_rate_uncertainty") is not None]
    h = [m["clock_rate_half_diff"] for _p, m in metas if m.get("clock_rate_half_diff") is not None]
    s = [m["clock_step_ms"] for _p, m in metas if m.get("clock_step_ms") is not None]
    print(f"  clock_rate_ratio n={len(r)} mean {statistics.mean(r):.6f} min {min(r):.6f} max {max(r):.6f}; "
          f"uncertainty max {max(u):.6f}; half_diff max {max(h):.6f}; clock_step_ms max {max(s):.3f}")
    drift = [p for p, m in metas if m.get("idle_drift")]
    print(f"  idle_drift runs: {len(drift)}")
    for k in ("git_sha", "calibration_v2_sha256", "pip_freeze_sha256", "mode", "rest_mode", "duration_s",
              "locust_returncode", "clocksource"):
        print(f"  {k}: {sorted({str(m.get(k))[:12] for _p, m in metas})}")
    ts = [m["run_start_ts"] for _p, m in metas]
    ends = [m.get("run_end_ts") or m["run_start_ts"] for _p, m in metas]
    print(f"  span {utc(min(ts))} to {utc(max(ends))} UTC (guest wall clock)")
    ts_state = sorted({json.dumps(m.get("timesync_state"), sort_keys=True) for _p, m in metas})
    print(f"  timesync_state: {ts_state}")
    wu = [w for _p, m in metas for w in m.get("warmup", [])]
    print(f"  warm-ups: {len(wu)}, status {sorted({w.get('status') for w in wu})}, seconds "
          f"{min(w['seconds'] for w in wu):.3f} to {max(w['seconds'] for w in wu):.3f}")
    miss = [p for p, m in metas if m.get("missing_files")]
    print(f"  runs with missing_files: {len(miss)}")
    fail_rows = exc_rows = 0
    for p, _m in metas:
        pre = p[:-len("_meta.json")]
        f = rows(pre + "_failures.csv")
        e = rows(pre + "_exceptions.csv")
        fail_rows += len(f or [])
        exc_rows += len(e or [])
    print(f"  Locust failures.csv data rows {fail_rows}, exceptions.csv data rows {exc_rows}")
    pids = [len(m.get("worker_pids", [])) for _p, m in metas]
    print(f"  worker_pids per run: {sorted(set(pids))}")
    mon = [m.get("monitor_cpu_pct") for _p, m in metas if m.get("monitor_cpu_pct") is not None]
    if mon:
        print(f"  monitor CPU % of one core: {min(mon):.2f} to {max(mon):.2f}")


def main():
    all_meta = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data_v2", "*", "*", "c*_run*_meta.json"))):
        if p.endswith("_locust_meta.json"):
            continue
        all_meta.append((os.path.relpath(p, ROOT), json.load(open(p))))
    main_m = [(p, m) for p, m in all_meta if m["framework"] in ("flask", "django", "fastapi", "tornado")]
    mw_m = [(p, m) for p, m in all_meta if m["framework"] in ("flask_mw", "django_mw")]
    real_m = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data_v2_real", "**", "c*_run*_meta.json"), recursive=True)):
        if not p.endswith("_locust_meta.json"):
            real_m.append((os.path.relpath(p, ROOT), json.load(open(p))))
    dataset("main matrix (data_v2, 4 frameworks)", main_m)
    dataset("multi-worker arm (data_v2, flask_mw, django_mw)", mw_m)
    dataset("real-API validation (data_v2_real)", real_m)

    red = [m for p, m in main_m if p.endswith("tornado/pipeline/c5_run5_meta.json")][0]
    print(f"\n== redone run tornado/pipeline/c5_run5: status {red['status']}, start {utc(red['run_start_ts'])} UTC, "
          f"clock_rate_ratio {red['clock_rate_ratio']:.6f}, clock_step_ms {red['clock_step_ms']}, flags "
          f"{[k for k in FLAGS if red.get(k)]}")

    idle = {}
    for p, m in main_m:
        idle.setdefault(m["framework"], []).append(abs(m.get("idle_uss_diff_mb") or 0))
    print("  main matrix max |idle USS diff| per framework (MB): " +
          ", ".join(f"{k} {max(v):.2f}" for k, v in sorted(idle.items())))

    # same-class differences in the medians
    long = {}
    for r in rows(os.path.join(ROOT, "results_v2", "summary_v2_long.csv")):
        long[(r["framework"], r["endpoint"], int(r["concurrency"]), r["metric"])] = float(r["median"])
    print("\n== Same-class differences of medians, max |a/b - 1| over endpoints and c (%)")
    for a, b in (("flask", "django"), ("fastapi", "tornado"), ("flask_mw", "django_mw")):
        for k in ("throughput_completion_rate", "throughput_fixed_window", "latency_p50_ms", "latency_mean_ms",
                  "cpu_mean_loaded_pct", "cpu_ms_per_request", "idle_uss_mb", "peak_uss_mb"):
            d = []
            for ep in ("inference", "stream", "pipeline"):
                for c in (1, 5, 10, 25, 50, 100):
                    if (a, ep, c, k) in long and (b, ep, c, k) in long:
                        d.append(((long[(a, ep, c, k)] / long[(b, ep, c, k)] - 1) * 100, ep, c))
            lo, hi = min(d), max(d)
            print(f"  {a} vs {b} {k:28}: {lo[0]:+.3f} % ({lo[1]} c{lo[2]}) to {hi[0]:+.3f} % ({hi[1]} c{hi[2]})")


if __name__ == "__main__":
    main()
