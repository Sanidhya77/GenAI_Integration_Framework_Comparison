"""Within-burst structure of Stage 2 / Stage 3 for async pipeline (Locust-side pipeline_metrics.csv).
If per-request client construction serialises on the event loop after the 50 ms sleep, then
s2(k) ~ 50 + (k-1)*X and s2+s3 ~ constant within a burst (all complete together)."""
import statistics
from common_load import *
import numpy as np
print(f"{'fw':8}{'c':>4} {'s2 med':>7} {'s2 p5':>7} {'s2 p95':>7} {'s3 med':>7} {'s2+s3 med':>9} {'s2+s3 IQR':>9} {'slope ms/pos':>12} {'(s2med-50)/(c/2)':>16} {'(e2e-2928)/c':>12}")
for fw in ASYNC:
    for c in CS:
        s2, s3, tot, e2e, slopes = [], [], [], [], []
        for r in RUNS:
            pm = [x for x in pipeline_metrics(fw, c, r) if x["completed"]]
            s2 += [x["s2"] for x in pm]; s3 += [x["s3"] for x in pm]; tot += [x["s2"] + x["s3"] for x in pm]; e2e += [x["e2e"] for x in pm]
            # slope of sorted s2 across a burst: group completions by timestamp gaps
            pm.sort(key=lambda x: x["timestamp"])
            groups, cur = [], [pm[0]]
            for a, b in zip(pm, pm[1:]):
                if b["timestamp"] - a["timestamp"] > 0.25: groups.append(cur); cur = [b]
                else: cur.append(b)
            groups.append(cur)
            for g in groups:
                if len(g) == c and c >= 25:
                    v = sorted(x["s2"] for x in g)
                    slopes.append(np.polyfit(np.arange(len(v)), v, 1)[0])
        q = np.percentile(tot, [25, 75])
        print(f"{fw:8}{c:>4} {med(s2):7.1f} {pct(s2,5):7.1f} {pct(s2,95):7.1f} {med(s3):7.0f} {med(tot):9.0f} {q[1]-q[0]:9.0f} "
              f"{(statistics.median(slopes) if slopes else float('nan')):12.2f} {(med(s2)-50)/(c/2):16.2f} {(med(e2e)-2928)/c:12.2f}")
