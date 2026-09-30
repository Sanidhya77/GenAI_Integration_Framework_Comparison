"""Arrival/completion pattern analysis.
Server-side: logs/<fw>/pipeline_timing.jsonl 'timestamp' = time.time() at pipeline start (pipeline_service.py:94/143),
logged at pipeline end. Client-side: stream_metrics / pipeline_metrics 'timestamp' = completion time at Locust.
For each run we assign jsonl records by the Locust-side time window and measure clustering."""
import sys, statistics
from common_load import *

def windows(fw, c):
    out = {}
    for r in RUNS:
        pm = pipeline_metrics(fw, c, r)
        if pm:
            out[r] = (min(x["timestamp"] for x in pm) - 70, max(x["timestamp"] for x in pm) + 1)
    return out

def burst_stats(ts, gap=0.25):
    """Group sorted timestamps into clusters separated by gaps > gap seconds."""
    ts = sorted(ts); groups = [[ts[0]]]
    for t in ts[1:]:
        if t - groups[-1][-1] > gap: groups.append([t])
        else: groups[-1].append(t)
    return groups

for fw in (sys.argv[1:] or FWS):
    J = jsonl(fw)
    for c in CS:
        W = windows(fw, c)
        for r in [1]:
            lo, hi = W[r]
            pm = pipeline_metrics(fw, c, r)
            first_done = min(x["timestamp"] for x in pm)
            recs = [j for j in J if lo <= j["timestamp"] <= hi and j["timestamp"] >= first_done - 70]
            # keep only records from this run: starts within 65 s before last Locust completion
            recs = [j for j in recs if j["timestamp"] >= max(x["timestamp"] for x in pm) - 65]
            starts = sorted(j["timestamp"] for j in recs)
            g = burst_stats(starts)
            sizes = [len(x) for x in g]; spans = [x[-1]-x[0] for x in g]
            ends = sorted(j["timestamp"] + j["total_pipeline_ms"]/1000 for j in recs)
            ge = burst_stats(ends)
            print(f"{fw:8} c{c:<3} run{r}: server starts={len(starts):5d} locust rows={len(pm):5d} | start clusters={len(g):4d} "
                  f"size med={statistics.median(sizes):5.0f} max={max(sizes):4d} span med={statistics.median(spans)*1000:7.0f}ms | "
                  f"end clusters={len(ge):4d} size med={statistics.median([len(x) for x in ge]):5.0f}")
