"""Per-config resource summary: idle RSS, peak RSS, mean CPU over loaded samples,
CPU-seconds per completed request. Loaded samples = rows with elapsed_s in [3, 62]
(monitor starts ~2 s before Locust, run_config.sh:107-120)."""
import csv, os
from common_load import *
lr = {(r["fw"], r["ep"], int(r["c"]), int(r["run"])): r for r in csv.DictReader(open(os.path.join(ROOT, "analysis/out/locust_runs.csv")))}
out = []
print(f"{'fw':8}{'ep':10}{'c':>4} {'idle':>7} {'peak':>7} {'cpuLoaded%':>10} {'cpuMax%':>8} {'cpuMs/req':>9} {'nSamples':>8}")
for fw in FWS:
    for ep in EPS:
        for c in CS:
            idl, pk, cpu, cmax, cpr, ns = [], [], [], [], [], []
            for r in RUNS:
                rs = resources(fw, ep, c, r)
                if not rs: continue
                idl.append(rs[0]["rss_mb"]); pk.append(max(x["rss_mb"] for x in rs))
                loaded = [x["cpu_percent"] for x in rs if 3 <= x["elapsed_s"] <= 62]
                m = sum(loaded) / len(loaded) if loaded else 0
                cpu.append(m); cmax.append(max(x["cpu_percent"] for x in rs)); ns.append(len(rs))
                n = int(lr[(fw, ep, c, r)]["n"])
                cpr.append(m / 100 * 60 / n * 1000 if n else None)
            out.append(dict(fw=fw, ep=ep, c=c, idle=med(idl), peak=med(pk), cpu=med(cpu), cpumax=med(cmax), cpu_ms_per_req=med(cpr)))
            print(f"{fw:8}{ep:10}{c:>4} {med(idl):7.1f} {med(pk):7.1f} {med(cpu):10.1f} {med(cmax):8.1f} {med(cpr):9.1f} {str(ns):>8}")
with open(os.path.join(ROOT, "analysis/out/resources_summary.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
