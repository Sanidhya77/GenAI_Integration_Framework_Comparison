"""
Multi-worker (17 Gunicorn sync workers) analysis for RESULTS_FINAL (read-only).

Inputs: results_v2/summary_v2_long.csv and per_run_v2.csv (scripts/aggregate_v2.py output, all 540
runs), and the raw data_v2/{flask_mw,django_mw}/*/c*_run*_requests.csv for the cycle estimator.

Throughput estimators (per run, then median over the 5 runs):
  rate    aggregate_v2 completion rate (n - 1) / (last - first) in [t0 + 2 S, stop]
  fixed   aggregate_v2 completions in [t0 + 2 S, stop] / window length
  cycle   multi-worker runs with c > 17 only. The 17 workers are phase-locked (PAPER_CONTEXT 21.4),
          so completions arrive in clusters every ~S. Clusters are split at gaps > S / 4 in the
          steady window; X_cycle = completions in all clusters except the last / (start of the
          last cluster - start of the first). This counts whole periods only, so it has neither
          the cluster-edge bias of "rate" nor the window-edge bias of "fixed".
Ceiling min(c, 17) / S for multi-worker, 1 / S single sync, c / S async; S = calibrated service time.
Latency: aggregate_v2 per-run p50 / p95 / mean over all successful requests, R = N / X (rate).
Resources: server CPU mean over [t0, stop] (% of one core, tree sum for MW), USS / RSS (tree sum).

Outputs: analysis/out/final_mw.csv, final_mw_ratio.csv.
"""

import csv
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "analysis", "out")
CFGS = ["flask", "django", "fastapi", "tornado", "flask_mw", "django_mw"]
EPS = ["inference", "stream", "pipeline"]
CS = [1, 5, 10, 25, 50, 100]
W = 17


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cycle_rate(prefix, s):
    lm = json.load(open(prefix + "_locust_meta.json"))
    lo, hi = lm["first_user_start_mono"] + 2 * s, lm["stop_mono"]
    ends = sorted(float(r["end_mono"]) for r in read(prefix + "_requests.csv")
                  if r["success"] == "True" and lo <= float(r["end_mono"]) <= hi)
    clusters = [[ends[0]]]
    for e in ends[1:]:
        if e - clusters[-1][-1] > s / 4:
            clusters.append([e])
        else:
            clusters[-1].append(e)
    if len(clusters) < 3:
        return None, None, None
    starts = [c[0] for c in clusters]
    x = sum(len(c) for c in clusters[:-1]) / (starts[-1] - starts[0])
    sizes = [len(c) for c in clusters[1:-1]]
    period = statistics.median(b - a for a, b in zip(starts, starts[1:]))
    return x, sizes, period


def main():
    long = {}
    for r in read(os.path.join(ROOT, "results_v2", "summary_v2_long.csv")):
        long[(r["framework"], r["endpoint"], int(r["concurrency"]), r["metric"])] = (
            float(r["median"]), float(r["min"]), float(r["max"]), int(r["n_runs"]))
    per_run = read(os.path.join(ROOT, "results_v2", "per_run_v2.csv"))
    s_ep = {r["endpoint"]: float(r["service_time_s"]) for r in per_run}

    def g(cfg, ep, c, k, i=0):
        v = long.get((cfg, ep, c, k))
        return None if v is None else v[i]

    rows = []
    for ep in EPS:
        s = s_ep[ep]
        for cfg in CFGS:
            for c in CS:
                row = {"config": cfg, "endpoint": ep, "concurrency": c, "S_s": s}
                if cfg.endswith("_mw"):
                    ceil_ = min(c, W) / s
                elif cfg in ("flask", "django"):
                    ceil_ = 1 / s
                else:
                    ceil_ = c / s
                row["ceiling_rps"] = ceil_
                for k in ("throughput_completion_rate", "throughput_fixed_window", "latency_p50_ms", "latency_p95_ms",
                          "latency_p99_ms", "latency_mean_ms", "response_law_R_ms", "closed_system_consistency",
                          "cpu_mean_loaded_pct", "cpu_max_loaded_pct", "cpu_ms_per_request", "idle_uss_mb",
                          "peak_uss_mb", "idle_rss_mb", "peak_rss_mb", "uss_growth_mb", "ttft_p50_ms", "ttft_p95_ms",
                          "tpot_p50_ms", "stage2_p50_ms", "monitor_cpu_pct", "censoring_fraction", "error_rate_pct"):
                    row[k] = g(cfg, ep, c, k)
                row["x_rate_min"], row["x_rate_max"] = (g(cfg, ep, c, "throughput_completion_rate", 1),
                                                        g(cfg, ep, c, "throughput_completion_rate", 2))
                row["share_rate"] = row["throughput_completion_rate"] / ceil_
                row["share_fixed"] = row["throughput_fixed_window"] / ceil_
                row["x_cycle"] = row["share_cycle"] = row["cluster_sizes"] = row["cycle_period_s"] = None
                if cfg.endswith("_mw") and c > W:
                    xs, sizes, periods = [], [], []
                    for rr in per_run:
                        if rr["framework"] == cfg and rr["endpoint"] == ep and int(rr["concurrency"]) == c:
                            prefix = os.path.join(ROOT, "data_v2", cfg, ep, f"c{c}_run{rr['run']}")
                            x, sz, per = cycle_rate(prefix, s)
                            if x is not None:
                                xs.append(x)
                                sizes += sz
                                periods.append(per)
                    row["x_cycle"] = statistics.median(xs)
                    row["x_cycle_min"], row["x_cycle_max"] = min(xs), max(xs)
                    row["share_cycle"] = row["x_cycle"] / ceil_
                    row["cluster_sizes"] = f"{min(sizes)}-{max(sizes)} (median {statistics.median(sizes)})"
                    row["cycle_period_s"] = statistics.median(periods)
                row["x_best"] = row["x_cycle"] if row["x_cycle"] is not None else row["throughput_completion_rate"]
                row["R_best_ms"] = c / row["x_best"] * 1000
                rows.append(row)

    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(OUT, "final_mw.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    idx = {(r["config"], r["endpoint"], r["concurrency"]): r for r in rows}
    print("== Multi-worker: throughput vs min(c, 17) / S (median of 5 runs)")
    for ep in EPS:
        print(f"-- {ep} (S = {s_ep[ep]} s, 17 / S = {W / s_ep[ep]:.4f} req/s)")
        for cfg in ("flask_mw", "django_mw"):
            for c in CS:
                r = idx[(cfg, ep, c)]
                cyc = (f" cycle {r['x_cycle']:.4f} [{r['x_cycle_min']:.4f}, {r['x_cycle_max']:.4f}] share "
                       f"{r['share_cycle']:.4f}, clusters {r['cluster_sizes']}, period {r['cycle_period_s']:.4f} s"
                       if r["x_cycle"] else "")
                print(f"  {cfg:9} c{c:<3} ceiling {r['ceiling_rps']:.4f} | rate {r['throughput_completion_rate']:.4f} "
                      f"share {r['share_rate']:.4f} | fixed {r['throughput_fixed_window']:.4f} share {r['share_fixed']:.4f}"
                      f" |{cyc}")
    print("\n== Multi-worker latency vs R = N / X (ms; X = cycle estimator for c > 17, else completion rate)")
    for ep in EPS:
        for cfg in ("flask_mw", "django_mw"):
            for c in CS:
                r = idx[(cfg, ep, c)]
                print(f"  {ep:9} {cfg:9} c{c:<3} p50 {r['latency_p50_ms']:9.1f} p95 {r['latency_p95_ms']:9.1f} "
                      f"mean {r['latency_mean_ms']:9.1f} | R(rate) {r['response_law_R_ms']:9.1f} R(best) {r['R_best_ms']:9.1f}"
                      f" | theory c S / min(c,17) {c * s_ep[ep] / min(c, W) * 1000:9.1f} | p50/R(best) "
                      f"{r['latency_p50_ms'] / r['R_best_ms']:.4f} mean/R(best) {r['latency_mean_ms'] / r['R_best_ms']:.4f}"
                      f" | cens frac {r['censoring_fraction']:.3f} consistency {r['closed_system_consistency']:.3f}")
    print("\n== Resources: CPU mean % of one core, CPU ms per request, idle / peak USS MB, idle / peak RSS MB")
    for ep in EPS:
        for c in CS:
            print(f"  {ep:9} c{c:<3} " + " | ".join(
                f"{cfg} {idx[(cfg, ep, c)]['cpu_mean_loaded_pct']:.2f}% {idx[(cfg, ep, c)]['cpu_ms_per_request']:.1f}ms "
                f"{idx[(cfg, ep, c)]['idle_uss_mb']:.1f}/{idx[(cfg, ep, c)]['peak_uss_mb']:.1f} "
                f"{idx[(cfg, ep, c)]['idle_rss_mb']:.1f}/{idx[(cfg, ep, c)]['peak_rss_mb']:.1f}" for cfg in CFGS))
    print("  monitor CPU (% of one core), MW: " + ", ".join(
        f"{cfg} {ep} c{c} {idx[(cfg, ep, c)]['monitor_cpu_pct']:.2f}" for cfg in ("flask_mw", "django_mw")
        for ep in EPS for c in (1, 100)))

    ratios = []
    print("\n== Async / 17-worker throughput ratio: mean(FastAPI, Tornado) / mean(flask_mw, django_mw)")
    for ep in EPS:
        for c in CS:
            a_rate = statistics.mean(idx[(f, ep, c)]["throughput_completion_rate"] for f in ("fastapi", "tornado"))
            a_fix = statistics.mean(idx[(f, ep, c)]["throughput_fixed_window"] for f in ("fastapi", "tornado"))
            m_rate = statistics.mean(idx[(f, ep, c)]["throughput_completion_rate"] for f in ("flask_mw", "django_mw"))
            m_fix = statistics.mean(idx[(f, ep, c)]["throughput_fixed_window"] for f in ("flask_mw", "django_mw"))
            m_best = statistics.mean(idx[(f, ep, c)]["x_best"] for f in ("flask_mw", "django_mw"))
            pairs = [idx[(a, ep, c)]["throughput_completion_rate"] / idx[(m, ep, c)]["x_best"]
                     for a in ("fastapi", "tornado") for m in ("flask_mw", "django_mw")]
            s1 = statistics.mean(idx[(f, ep, c)]["throughput_completion_rate"] for f in ("flask", "django"))
            s1f = statistics.mean(idx[(f, ep, c)]["throughput_fixed_window"] for f in ("flask", "django"))
            spairs = [idx[(a, ep, c)]["throughput_completion_rate"] / idx[(m, ep, c)]["throughput_completion_rate"]
                      for a in ("fastapi", "tornado") for m in ("flask", "django")]
            row = dict(endpoint=ep, concurrency=c, async_rate=a_rate, async_fixed=a_fix, mw_rate=m_rate, mw_fixed=m_fix,
                       mw_best=m_best, ratio_best=a_rate / m_best, ratio_rate=a_rate / m_rate, ratio_fixed=a_fix / m_fix,
                       ratio_best_min=min(pairs), ratio_best_max=max(pairs), theory=c / min(c, W),
                       mw_over_single_sync=m_best / s1, async_over_single_rate=a_rate / s1,
                       async_over_single_rate_min=min(spairs), async_over_single_rate_max=max(spairs),
                       async_over_single_fixed=a_fix / s1f)
            ratios.append(row)
            print(f"  {ep:9} c{c:<3} async {a_rate:.4f} / MW {m_best:.4f} = {row['ratio_best']:.3f} "
                  f"[{row['ratio_best_min']:.3f}, {row['ratio_best_max']:.3f}] (theory c / min(c,17) = {row['theory']:.3f}); "
                  f"rate/rate {row['ratio_rate']:.3f}; fixed/fixed {row['ratio_fixed']:.3f}; MW / single-worker sync "
                  f"{row['mw_over_single_sync']:.3f}; async / 1-worker sync rate {row['async_over_single_rate']:.2f} "
                  f"[{row['async_over_single_rate_min']:.2f}, {row['async_over_single_rate_max']:.2f}], fixed "
                  f"{row['async_over_single_fixed']:.2f}")
    with open(os.path.join(OUT, "final_mw_ratio.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ratios[0]))
        w.writeheader()
        w.writerows(ratios)
    print("\nSaved analysis/out/final_mw.csv, final_mw_ratio.csv")


if __name__ == "__main__":
    main()
