"""
Streaming-granularity CPU projection for RESULTS_FINAL (read-only). Everything here is a
PROJECTION (INFERRED) except the measured inputs, which are listed with their source.

Measured inputs
  results_v2/summary_v2_long.csv   simulated runs (12 chunks per stream): cpu_ms_per_request,
                                   cpu_mean_loaded_pct, throughput_completion_rate (median of 5 runs)
  data_v2_real/fastapi/stream      real FastAPI stream c = 1 and c = 25 (Phase B): CPU per request,
                                   mean chunks per stream (via analysis/out/final_real_per_run.csv
                                   and the stream_metrics files)

Method 1 (as specified): per-chunk CPU k1(c) = (stream CPU ms per request - inference CPU ms per
  request at the same c) / 12. Projected CPU per request with n chunks = inference base + n x k1.
  Projected CPU (% of one core) = X x CPU ms per request / 10, with X = c / S.
  Two throughput assumptions: X = measured simulated stream throughput at c (service time held
  at S_sim = 2.7804 s), and X = c / S_today with S_today = 3.2555 s (Phase B real c = 1 median).
Method 2 (anchored on the measured real c = 25 FastAPI stream): real CPU ms per request at c = 25
  scaled to c = 50, 100 by the simulated FastAPI ratio cpu_ms(c) / cpu_ms(25) (load-dependent
  efficiency), Tornado by the simulated Tornado / FastAPI ratio at the same c; X = c / S_today.
Check: Method 1 applied at c = 25 vs the measured real c = 25 FastAPI CPU.

A single Python process with one event loop cannot use more than about 100 % of one core; a
projection above 100 % means the server would be CPU-bound (throughput below c / S, TTFT growing).

Output: analysis/out/final_stream_cpu.csv
"""

import csv
import glob
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "analysis", "out")
S_SIM = 2.7804
N_SIM = 12
N_NEW = 92


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    long = {}
    for r in read(os.path.join(ROOT, "results_v2", "summary_v2_long.csv")):
        long[(r["framework"], r["endpoint"], int(r["concurrency"]), r["metric"])] = float(r["median"])
    real = [r for r in read(os.path.join(OUT, "final_real_per_run.csv")) if r["phase"] == "B"]
    lv = {r["metric"]: r for r in read(os.path.join(OUT, "final_real_levels.csv"))
          if r["phase"] == "B" and r["concurrency"] == "1" and r["metric"] == "latency_ms"}
    s_today = float(lv["latency_ms"]["pooled_median"]) / 1000
    real_c25 = [r for r in real if r["concurrency"] == "25"]
    real_ms25 = statistics.median(float(r["cpu_ms_per_request"]) for r in real_c25)
    real_pct25 = statistics.median(float(r["cpu_mean_loaded_pct"]) for r in real_c25)
    real_x25 = statistics.median(float(r["throughput_completion_rate"]) for r in real_c25)
    chunks25 = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data_v2_real", "fastapi", "stream", "c25_run*_stream_metrics.csv"))):
        chunks25 += [int(x["token_count"]) for x in read(p) if x["success"] == "True"]
    mean_chunks25 = statistics.mean(chunks25)
    real_c1 = [r for r in real if r["concurrency"] == "1"]
    real_ms1 = statistics.median(float(r["cpu_ms_per_request"]) for r in real_c1)
    print(f"Measured: S_today {s_today:.4f} s (Phase B c1 pooled median); real FastAPI stream c25 CPU "
          f"{real_ms25:.2f} ms/request, {real_pct25:.2f} % of one core, X {real_x25:.3f} req/s, mean chunks "
          f"{mean_chunks25:.2f} (n={len(chunks25)}); real c1 CPU {real_ms1:.2f} ms/request")

    rows = []
    print("\nMethod 1: k1 = (stream - inference CPU ms per request) / 12, per c (simulated data)")
    for fw in ("fastapi", "tornado"):
        for c in (1, 5, 10, 25, 50, 100):
            st, inf = long[(fw, "stream", c, "cpu_ms_per_request")], long[(fw, "inference", c, "cpu_ms_per_request")]
            k1 = (st - inf) / N_SIM
            x_sim = long[(fw, "stream", c, "throughput_completion_rate")]
            meas = long[(fw, "stream", c, "cpu_mean_loaded_pct")]
            ms92 = inf + N_NEW * k1
            row = dict(method="1", framework=fw, concurrency=c, stream_ms_req=st, inference_ms_req=inf,
                       k1_ms_per_chunk=k1, measured_sim_cpu_pct=meas, x_sim=x_sim,
                       check_12chunks_pct=x_sim * st / 10, proj_ms_req_92=ms92,
                       proj_pct_92_xsim=x_sim * ms92 / 10, proj_pct_92_xtoday=c / s_today * ms92 / 10)
            rows.append(row)
            print(f"  {fw:8} c{c:<3} stream {st:6.2f} - inference {inf:6.2f} = {st - inf:6.2f} ms -> k1 "
                  f"{k1:.3f} ms/chunk | measured sim CPU {meas:6.2f} % (X x ms/10 = {row['check_12chunks_pct']:6.2f} %) | "
                  f"92 chunks: {ms92:6.1f} ms/request -> {row['proj_pct_92_xsim']:6.1f} % at X_sim {x_sim:.2f}, "
                  f"{row['proj_pct_92_xtoday']:6.1f} % at c/S_today {c / s_today:.2f}")
    k1_25 = [r for r in rows if r["framework"] == "fastapi" and r["concurrency"] == 25][0]
    pred25 = k1_25["inference_ms_req"] + mean_chunks25 * k1_25["k1_ms_per_chunk"]
    print(f"\nCheck at c = 25 (FastAPI): Method 1 with {mean_chunks25:.2f} chunks predicts {pred25:.1f} ms/request, "
          f"{real_x25 * pred25 / 10:.1f} % at the real X {real_x25:.3f}; measured {real_ms25:.1f} ms/request, "
          f"{real_pct25:.1f} % -> Method 1 / measured = {pred25 / real_ms25:.2f}")
    k2 = (real_ms25 - long[("fastapi", "stream", 25, "cpu_ms_per_request")]) / (mean_chunks25 - N_SIM)
    fixed = long[("fastapi", "stream", 25, "cpu_ms_per_request")] - long[("fastapi", "inference", 25,
                                                                          "cpu_ms_per_request")] - N_SIM * k2
    print(f"Two-point decomposition at c = 25 (sim 12 chunks vs real {mean_chunks25:.2f}): {k2:.3f} ms per extra "
          f"chunk, stream fixed overhead {fixed:.1f} ms per request above inference (INFERRED; the real path also "
          f"adds TLS and a different upstream event stream, so k2 is an upper bound of the per-chunk cost)")

    print("\nMethod 2: real c25 CPU/request scaled by simulated load efficiency; X = c / S_today")
    fa25 = long[("fastapi", "stream", 25, "cpu_ms_per_request")]
    for fw in ("fastapi", "tornado"):
        for c in (25, 50, 100):
            eff = long[("fastapi", "stream", c, "cpu_ms_per_request")] / fa25
            fwr = long[(fw, "stream", c, "cpu_ms_per_request")] / long[("fastapi", "stream", c, "cpu_ms_per_request")]
            ms = real_ms25 * eff * fwr
            pct = c / s_today * ms / 10
            rows.append(dict(method="2", framework=fw, concurrency=c, proj_ms_req_92=ms, proj_pct_92_xtoday=pct,
                             load_eff=eff, fw_ratio=fwr))
            print(f"  {fw:8} c{c:<3} {real_ms25:.2f} x load {eff:.3f} x framework {fwr:.3f} = {ms:6.2f} ms/request -> "
                  f"{pct:6.1f} % of one core at X = {c / s_today:.2f} req/s")
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(OUT, "final_stream_cpu.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print("Saved analysis/out/final_stream_cpu.csv")


if __name__ == "__main__":
    main()
