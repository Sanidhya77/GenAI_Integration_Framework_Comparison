"""Locust Requests/s = num_requests / (last_request_timestamp - start_time)  (locust/stats.py:472-476).
Using stream_metrics (completion ts, total_time) we recover first send and last completion, then
compare with the denominator N/RPS from *_stats.csv to locate start_time relative to the first send."""
import csv, os
from common_load import *
lr = {(r["fw"], r["ep"], int(r["c"]), int(r["run"])): r for r in csv.DictReader(open(os.path.join(ROOT, "analysis/out/locust_runs.csv")))}
print(f"{'fw':8}{'c':>4} {'denom':>7} {'lastDone-firstSend':>18} {'lead(start before 1st send)':>27} {'spawn spread':>12} {'lastDone-firstSend(rel to last send)':>10}")
for fw in FWS:
    for c in CS:
        dn, span, lead, spread = [], [], [], []
        for r in RUNS:
            sm = stream_metrics(fw, c, r)
            sends = sorted(m["timestamp"] - m["total_time_ms"] / 1000 for m in sm)
            last = max(m["timestamp"] for m in sm)
            L = lr[(fw, "stream", c, r)]
            d = float(L["denom_agg"]); dn.append(d)
            span.append(last - sends[0]); lead.append(d - (last - sends[0]))
            spread.append(sends[min(c, len(sends)) - 1] - sends[0])
        print(f"{fw:8}{c:>4} {med(dn):7.2f} {med(span):18.2f} {med(lead):27.3f} {med(spread):12.3f}")
