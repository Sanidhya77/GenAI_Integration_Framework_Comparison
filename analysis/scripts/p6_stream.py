"""Stream custom metrics by fw x c: token_count distribution, TTFT, TPOT, total, success.
Also TPOT recomputed excluding the last 'token' when token_count==13 in simulated mode, and
the inter-arrival of the final (sentinel) event."""
import collections
from common_load import *
print(f"{'fw':8}{'c':>4} {'n':>5} {'tokcount dist':32} {'TTFT med':>9} {'TTFT p95':>9} {'TPOT med':>9} {'total med':>9} {'succ%':>6} {'first->last tok ms':>18}")
for fw in FWS:
    for c in CS:
        allm = []
        for r in RUNS: allm += stream_metrics(fw, c, r)
        succ = [m for m in allm if m["success"]]
        d = collections.Counter(m["token_count"] for m in allm)
        span = [m["tpot_ms"] * (m["token_count"] - 1) for m in succ if m["tpot_ms"]]
        print(f"{fw:8}{c:>4} {len(allm):5d} {str(dict(sorted(d.items()))):32} {med([m['ttft_ms'] for m in succ]):9.0f} {pct([m['ttft_ms'] for m in succ],95):9.0f} "
              f"{med([m['tpot_ms'] for m in succ]):9.1f} {med([m['total_time_ms'] for m in succ]):9.0f} {100*len(succ)/len(allm):6.1f} {med(span):18.0f}")
