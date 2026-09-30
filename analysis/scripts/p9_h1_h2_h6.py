"""H1: overhead above simulated service time for async; H2: sync censoring; H6: throughput ceilings.
Service times (simulated): inference 2.878 s (simulator.py:86-89); stream 12*0.2 = 2.4 s (simulator.py:112-136);
pipeline 0.05 + 2.878 = 2.928 s (retrieval.py:261/272 + simulator)."""
import csv, os
from common_load import *
lr = [r for r in csv.DictReader(open(os.path.join(ROOT, "analysis/out/locust_runs.csv")))]
def g(fw, ep, c): return [r for r in lr if r["fw"] == fw and r["ep"] == ep and int(r["c"]) == c]
S = {"inference": 2.878, "stream": 2.4, "pipeline": 2.928}
# exact (unrounded) latency: Locust avg for inference; custom CSVs for stream/pipeline
def exact_lat(fw, ep, c):
    if ep == "stream":
        return med([m["total_time_ms"] for r in RUNS for m in stream_metrics(fw, c, r)]) / 1000
    if ep == "pipeline":
        return med([m["e2e"] for r in RUNS for m in pipeline_metrics(fw, c, r) if m["completed"]]) / 1000
    return med([float(r["avg"]) for r in g(fw, ep, c)]) / 1000
print("== H1 (async, simulated). overhead = exact median latency - S; X = overhead/c")
print(f"{'fw':8}{'ep':10}{'c':>4} {'lat s':>6} {'ovh ms':>7} {'ovh/c ms':>8}")
for fw in ASYNC:
    for ep in EPS:
        for c in (25, 50, 100):
            L = exact_lat(fw, ep, c); o = (L - S[ep]) * 1000
            print(f"{fw:8}{ep:10}{c:>4} {L:6.3f} {o:7.0f} {o/c:8.2f}")
print("\n== H2 (sync). completions/run, recorded median/p95/p99 (Locust, 2 s.f.), uncensored steady-state expectation c*S")
print(f"{'fw':8}{'ep':10}{'c':>4} {'n per run':>22} {'median':>7} {'p95':>6} {'p99':>6} {'max':>6} {'c*S s':>7} {'inflight dropped/run':>20}")
for fw in SYNC:
    for ep in EPS:
        for c in CS:
            rr = g(fw, ep, c); s = S[ep] if c >= 25 else 2.9
            print(f"{fw:8}{ep:10}{c:>4} {str([int(r['n']) for r in rr]):>22} {med([float(r['median']) for r in rr]):7.0f} {med([float(r['p95']) for r in rr]):6.0f} "
                  f"{med([float(r['p99']) for r in rr]):6.0f} {med([float(r['maxrt']) for r in rr]):6.0f} {c*s:7.1f} {c:>20}")
print("\n== H6. RPS, Little's law check c/avg_latency, thesis share rps/(c/2.878), corrected share rps/(c/S_ep)")
print(f"{'fw':8}{'ep':10}{'c':>4} {'rps':>7} {'c/avgLat':>8} {'thesis share':>12} {'S_ep':>5} {'corr share':>10}")
for fw in FWS:
    for ep in EPS:
        for c in CS:
            rr = g(fw, ep, c); rps = med([float(r["rps_agg"]) for r in rr])
            avg = med([float(r["avg"]) for r in rr]) / 1000
            if c >= 25: s = S[ep]
            else:  # real API: use the same framework's c=1 exact median latency as its service time
                s = exact_lat(fw, ep, 1)
            ideal = c / s if fw in ASYNC else 1 / s
            print(f"{fw:8}{ep:10}{c:>4} {rps:7.3f} {c/avg:8.3f} {100*rps/((c if fw in ASYNC else 1)/2.878):11.1f}% {s:5.3f} {100*rps/ideal:9.1f}%")
