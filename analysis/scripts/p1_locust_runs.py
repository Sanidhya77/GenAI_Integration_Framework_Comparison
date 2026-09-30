"""Per-run Locust stats: completions, Requests/s (Aggregated vs named row), implied denominators,
recorded median/p95/p99. Writes analysis/out/locust_runs.csv and prints a per-config summary."""
import csv, os, statistics
from common_load import *

OUT = os.path.join(ROOT, "analysis", "out"); os.makedirs(OUT, exist_ok=True)
recs = []
for fw in FWS:
    for ep in EPS:
        for c in CS:
            for r in RUNS:
                named, agg = stats_rows(fw, ep, c, r)
                if not agg: continue
                n = int(agg["Request Count"]); fails = int(agg["Failure Count"])
                rps_a = float(agg["Requests/s"]); rps_n = float(named["Requests/s"]) if named else None
                h = history(fw, ep, c, r)
                ts = [int(x["Timestamp"]) for x in h]
                first_user = next((int(x["Timestamp"]) for x in h if int(x["User Count"]) > 0), None)
                recs.append(dict(fw=fw, ep=ep, c=c, run=r, n=n, fails=fails, rps_agg=rps_a, rps_named=rps_n,
                    denom_agg=(n / rps_a if rps_a else None), denom_named=(n / rps_n if rps_n else None),
                    median=float(agg["Median Response Time"]), avg=float(agg["Average Response Time"]),
                    p95=float(agg["95%"]), p99=float(agg["99%"]), maxrt=float(agg["Max Response Time"]),
                    minrt=float(agg["Min Response Time"]), hist_span=(ts[-1]-ts[0]) if ts else None,
                    hist_first_user_to_end=(ts[-1]-first_user) if first_user else None))
with open(os.path.join(OUT, "locust_runs.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(recs[0])); w.writeheader(); w.writerows(recs)
print(f"{'fw':8}{'ep':10}{'c':>4} {'n/run':>18} {'rpsAgg med':>10} {'rpsNamed med':>12} {'denomAgg':>9} {'denomNamed':>10} {'median':>7} {'p95':>7} {'p99':>7} {'fails':>5}")
for fw in FWS:
    for ep in EPS:
        for c in CS:
            rr = [x for x in recs if x["fw"]==fw and x["ep"]==ep and x["c"]==c]
            print(f"{fw:8}{ep:10}{c:>4} {str([x['n'] for x in rr]):>18} {med([x['rps_agg'] for x in rr]):>10.3f} "
                  f"{med([x['rps_named'] for x in rr]):>12.3f} {med([x['denom_agg'] for x in rr]):>9.2f} {med([x['denom_named'] for x in rr]):>10.2f} "
                  f"{med([x['median'] for x in rr]):>7.0f} {med([x['p95'] for x in rr]):>7.0f} {med([x['p99'] for x in rr]):>7.0f} {sum(x['fails'] for x in rr):>5}")
