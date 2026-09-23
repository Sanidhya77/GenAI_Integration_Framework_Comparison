"""
Validate the simulator: simulated c = 1, 5, 10 (data_v2/) against the real-API thesis
data at c = 1, 5, 10 (data/), per framework and endpoint.

Metrics (median over runs of the per-run value, the same rule on both sides):
  throughput          Locust Requests/s (same definition on both sides)
  median latency      real: Locust median (2 significant figures) for inference and
                      pipeline, exact stream total time for stream; sim: exact p50
                      from the per-request log
  mean latency        exact on both sides (Locust average / stream total time)
  TTFT, TPOT, token count           stream_metrics.csv
  Stage 2, Stage 3                  pipeline_metrics.csv
  p95 latency (tail)  reported, never flagged: the simulator has no jitter by design (D3)

Medians more than 5 % apart are flagged.

Usage:
  venv/bin/python scripts/validate_sim.py [--sim data_v2] [--real data] [--out results_v2]
"""

import argparse
import csv
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMEWORKS = ["flask", "django", "fastapi", "tornado"]
ENDPOINTS = ["inference", "stream", "pipeline"]
LEVELS = [1, 5, 10]
RUNS = [1, 2, 3, 4, 5]
FLAG_PCT = 5.0


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def pct(v, p):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def f(v):
    return None if v in (None, "", "None", "N/A") else float(v)


def per_run(root, fw, ep, c, r, sim):
    prefix = os.path.join(root, fw, ep, f"c{c}_run{r}")
    stats = [x for x in read_csv(prefix + "_stats.csv") if x["Name"] == "Aggregated"]
    if not stats:
        return None
    if sim:
        meta = read_csv(prefix + "_requests.csv")
        if not meta:
            return None
    agg = stats[0]
    m = {"throughput_rps": f(agg["Requests/s"]), "mean_latency_ms": f(agg["Average Response Time"]),
         "p95_latency_ms": f(agg["95%"])}
    if sim:
        lat = [float(x["response_time_ms"]) for x in read_csv(prefix + "_requests.csv") if x["success"] == "True"]
        m["median_latency_ms"] = pct(lat, 50)
        m["mean_latency_ms"] = statistics.mean(lat) if lat else None
        m["p95_latency_ms"] = pct(lat, 95)
    else:
        m["median_latency_ms"] = f(agg["Median Response Time"])
    if ep == "stream":
        sm = [x for x in read_csv(prefix + "_stream_metrics.csv") if x["success"] == "True"]
        tot = [f(x["total_time_ms"]) for x in sm]
        if not sim:
            m["median_latency_ms"] = med(tot)
            m["mean_latency_ms"] = statistics.mean(tot) if tot else None
            m["p95_latency_ms"] = pct(tot, 95)
        m["ttft_ms"] = med([f(x["ttft_ms"]) for x in sm])
        m["tpot_ms"] = med([f(x["tpot_ms"]) for x in sm])
        m["token_count"] = med([f(x["token_count"]) for x in sm])
    if ep == "pipeline":
        pm = [x for x in read_csv(prefix + "_pipeline_metrics.csv") if x["completed"] == "True"]
        m["stage2_ms"] = med([f(x["stage2_ms"]) for x in pm])
        m["stage3_ms"] = med([f(x["stage3_ms"]) for x in pm])
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", default="data_v2")
    ap.add_argument("--real", default="data")
    ap.add_argument("--out", default="results_v2")
    a = ap.parse_args()
    sim_root, real_root = os.path.join(ROOT, a.sim), os.path.join(ROOT, a.real)
    os.makedirs(os.path.join(ROOT, a.out), exist_ok=True)

    rows = []
    for fw in FRAMEWORKS:
        for ep in ENDPOINTS:
            for c in LEVELS:
                sim = [m for m in (per_run(sim_root, fw, ep, c, r, True) for r in RUNS) if m]
                real = [m for m in (per_run(real_root, fw, ep, c, r, False) for r in RUNS) if m]
                if not sim or not real:
                    continue
                for metric in sorted({k for m in sim + real for k in m}):
                    sv, rv = med([m.get(metric) for m in sim]), med([m.get(metric) for m in real])
                    if sv is None or rv is None:
                        continue
                    delta = (sv - rv) / rv * 100 if rv else None
                    tail = metric.startswith("p95")
                    rows.append({"framework": fw, "endpoint": ep, "concurrency": c, "metric": metric,
                                 "sim": round(sv, 3), "real": round(rv, 3),
                                 "delta_pct": None if delta is None else round(delta, 2),
                                 "sim_runs": len(sim), "real_runs": len(real), "tail": tail,
                                 "flag": (not tail) and delta is not None and abs(delta) > FLAG_PCT})

    out = os.path.join(ROOT, a.out, "validation_sim_vs_real.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["framework", "endpoint", "concurrency", "metric", "sim", "real",
                                           "delta_pct", "sim_runs", "real_runs", "tail", "flag"])
        w.writeheader()
        w.writerows(rows)

    print(f"{'framework':9} {'endpoint':9} {'c':>3} {'metric':18} {'sim':>10} {'real':>10} {'delta%':>8}  flag")
    for r in rows:
        mark = "FLAG" if r["flag"] else ("tail" if r["tail"] else "")
        print(f"{r['framework']:9} {r['endpoint']:9} {r['concurrency']:>3} {r['metric']:18} {r['sim']:>10} "
              f"{r['real']:>10} {r['delta_pct'] if r['delta_pct'] is not None else '':>8}  {mark}")
    flagged = sum(r["flag"] for r in rows)
    print(f"{len(rows)} comparisons, {flagged} medians more than {FLAG_PCT:.0f} % apart -> {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
