"""Chronological RSS timeline per framework: for each run, start time, idle RSS (first sample,
taken before Locust starts), peak RSS. A drop in idle RSS vs the previous run's peak implies a server restart."""
import datetime
from common_load import *
for fw in FWS:
    runs = []
    for ep in EPS:
        for c in CS:
            for r in RUNS:
                rs = resources(fw, ep, c, r)
                runs.append((rs[0]["timestamp"], ep, c, r, rs[0]["rss_mb"], max(x["rss_mb"] for x in rs)))
    runs.sort()
    print(f"== {fw}")
    prev_peak = None; line = []
    for t, ep, c, r, idle, peak in runs:
        flag = ""
        if prev_peak is not None and idle < prev_peak - 3: flag = "  <-- RESTART (idle < prev peak)"
        if r == 1 or flag:
            print(f"  {datetime.datetime.utcfromtimestamp(t):%m-%d %H:%M} {ep:9} c{c:<3} run{r} idle={idle:6.1f} peak={peak:6.1f}{flag}")
        prev_peak = peak
