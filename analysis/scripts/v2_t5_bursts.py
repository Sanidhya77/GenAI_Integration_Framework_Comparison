"""T5: Stage 2, overhead above S_ep and per-second completion pattern for a v2 pipeline run,
next to the thesis c = 100 run (data/). Usage: v2_t5_bursts.py <data_root> <fw> [c] [run]"""
import csv, json, math, statistics, sys, os
root, fw = sys.argv[1], sys.argv[2]
c = int(sys.argv[3]) if len(sys.argv) > 3 else 100
run = int(sys.argv[4]) if len(sys.argv) > 4 else 1
cal = json.load(open("simulated_endpoint/calibration_v2.json"))["values"]
S_new = cal["service_time_s"]["pipeline"]; S_old = 2.878 + 0.05
def load(base):
    rows = list(csv.DictReader(open(f"{base}/{fw}/pipeline/c{c}_run{run}_pipeline_metrics.csv")))
    return [r for r in rows if r["completed"] == "True"]
def per_second(ts):
    t0 = math.floor(min(ts)); t1 = math.floor(max(ts))
    counts = [0] * (t1 - t0 + 1)
    for t in ts: counts[math.floor(t) - t0] += 1
    return counts
out = {}
for label, base, S in (("thesis", "data", S_old), ("v2", root, S_new)):
    rows = load(base)
    s2 = [float(r["stage2_ms"]) for r in rows]; e2e = [float(r["e2e_pipeline_ms"]) for r in rows]
    pcs = per_second([float(r["timestamp"]) for r in rows])
    out[label] = dict(n=len(rows), stage2_median_ms=round(statistics.median(s2), 1),
                      stage2_p95_ms=round(sorted(s2)[int(.95 * len(s2))], 1),
                      e2e_median_ms=round(statistics.median(e2e), 1),
                      overhead_above_S_ms=round(statistics.median(e2e) - S * 1000, 1),
                      seconds_with_completions=len(pcs), empty_seconds=pcs.count(0),
                      max_per_second=max(pcs), per_second_first_20=pcs[:20])
# client-side latency from the v2 per-request log
req = [r for r in csv.DictReader(open(f"{root}/{fw}/pipeline/c{c}_run{run}_requests.csv")) if r["success"] == "True"]
lat = statistics.median(float(r["response_time_ms"]) for r in req)
out["v2"]["client_latency_median_ms"] = round(lat, 1)
out["v2"]["client_overhead_above_S_ms"] = round(lat - S_new * 1000, 1)
print(json.dumps({fw: out}, indent=1))
