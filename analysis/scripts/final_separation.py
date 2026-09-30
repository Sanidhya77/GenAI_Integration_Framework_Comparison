"""
Same-class separation and run-to-run spread for RESULTS_FINAL (read-only; results_v2/per_run_v2.csv).

Separation: two frameworks are "separated" on a metric at a given endpoint and c when the ranges
[min, max] of their 5 per-run values do not overlap (same definition as RESULTS_V2 c.6). Metrics:
X fixed and completion rate, latency p50 and mean, idle and peak USS, CPU mean and CPU ms per
request; plus p95 (inference), TTFT and TPOT p50 (stream), Stage 2, Stage 3 and server E2E p50
(pipeline). Pairs: Flask vs Django, FastAPI vs Tornado, flask_mw vs django_mw.

Run-to-run spread: (max - min) / median of the 5 per-run values, largest over c and configurations
of each class, per endpoint and metric (single-worker sync latency only where uncensored, c <= 10).
"""

import csv
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = ["throughput_fixed_window", "throughput_completion_rate", "latency_p50_ms", "latency_mean_ms",
        "idle_uss_mb", "peak_uss_mb", "cpu_mean_loaded_pct", "cpu_ms_per_request"]
EXTRA = {"inference": ["latency_p95_ms"], "stream": ["ttft_p50_ms", "tpot_p50_ms"],
         "pipeline": ["stage2_p50_ms", "stage3_p50_ms", "e2e_server_p50_ms"]}
CS = [1, 5, 10, 25, 50, 100]


def main():
    with open(os.path.join(ROOT, "results_v2", "per_run_v2.csv"), newline="") as f:
        runs = list(csv.DictReader(f))
    vals = {}
    for r in runs:
        for k in r:
            if r[k] not in ("", "None"):
                try:
                    vals.setdefault((r["framework"], r["endpoint"], int(r["concurrency"]), k), []).append(float(r[k]))
                except ValueError:
                    pass
    print("== Separated comparisons (non-overlapping 5-run ranges)")
    for a, b in (("flask", "django"), ("fastapi", "tornado"), ("flask_mw", "django_mw")):
        for ep in ("inference", "stream", "pipeline"):
            mets = BASE + EXTRA[ep]
            sep, total, detail = 0, 0, []
            for c in CS:
                for k in mets:
                    va, vb = vals.get((a, ep, c, k)), vals.get((b, ep, c, k))
                    if not va or not vb:
                        continue
                    total += 1
                    if max(va) < min(vb) or max(vb) < min(va):
                        sep += 1
                        d = (statistics.median(va) / statistics.median(vb) - 1) * 100
                        detail.append(f"{k} c{c} {d:+.2f}%")
            print(f"  {a} vs {b} {ep}: {sep} of {total}")
            small = [x for x in detail if not x.startswith(("idle_uss", "peak_uss", "cpu_"))]
            print(f"    separated, excluding memory and CPU: {', '.join(small) if small else 'none'}")
            cpu = [x for x in detail if x.startswith("cpu_")]
            print(f"    separated CPU: {', '.join(cpu) if cpu else 'none'}")
    print("\n== Largest run-to-run spread (max - min) / median, %, per class and endpoint")
    classes = {"1-worker sync": ("flask", "django"), "17-worker sync": ("flask_mw", "django_mw"),
               "async": ("fastapi", "tornado")}
    for cls, fws in classes.items():
        for ep in ("inference", "stream", "pipeline"):
            out = []
            for k in ("throughput_completion_rate", "latency_p50_ms", "latency_mean_ms", "ttft_p50_ms",
                      "cpu_mean_loaded_pct", "peak_uss_mb"):
                worst = None
                for fw in fws:
                    for c in CS:
                        if cls == "1-worker sync" and k.startswith(("latency", "ttft")) and c > 10:
                            continue
                        v = vals.get((fw, ep, c, k))
                        if not v:
                            continue
                        s = (max(v) - min(v)) / statistics.median(v) * 100
                        if worst is None or s > worst[0]:
                            worst = (s, fw, c)
                if worst:
                    out.append(f"{k} {worst[0]:.2f} ({worst[1]} c{worst[2]})")
            print(f"  {cls:15} {ep:9}: " + "; ".join(out))


if __name__ == "__main__":
    main()
