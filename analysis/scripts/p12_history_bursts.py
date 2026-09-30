"""Per-second completions from *_stats_history.csv (diff of Total Request Count). Bursty closed-loop
traffic shows as spikes of ~c completions every ~L seconds separated by zeros."""
from common_load import *
for fw, ep, c in [("fastapi","inference",100),("tornado","inference",100),("fastapi","inference",25),("fastapi","inference",10),("flask","inference",100)]:
    h = history(fw, ep, c, 1); n = [int(x["Total Request Count"]) for x in h]
    d = [b - a for a, b in zip(n, n[1:])]
    nz = sum(1 for x in d if x == 0)
    print(f"{fw:8}{ep:10}c{c:<3} per-second completions: {d[:40]} ... zero-seconds={nz}/{len(d)}")
