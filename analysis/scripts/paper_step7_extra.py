"""
Step 7 (8 Oct 2026), Part 1.3: extra analysis of existing data (read-only; no server, no API call).

(a) Streaming CPU. CPU per completed request of the live Phase A runs (FastAPI inference, c = 1 and 25)
    against the simulated FastAPI inference cells, and CPU per relayed chunk
        (stream CPU per request - inference CPU per request) / mean chunks per response
    for FastAPI at c = 1 and 25 (live Phase B and simulated) and for the four frameworks at c = 1 (live
    Phase C and simulated). Each run gives one value: its stream CPU per request minus the median
    inference CPU per request of the reference cell, divided by the run's mean chunk count. Live
    references: the Phase A median for FastAPI at the same c; Phase C has no live inference runs, so its
    reference is the simulated inference cell of the same framework at c = 1 (for FastAPI both are shown).
    Value: median of the per-run values; interval: their range (3 live runs, 5 simulated runs).
(d) Ranges behind the range sentences of Results (idle USS, Figure 3, steady state against R), from
    analysis/out/paper_v2.1/numbers.csv.

All live and simulated runs used the same resource monitor (aggregate_v2.run_metrics).

Inputs
  analysis/out/final_real_per_run.csv            live per-run CPU (final_real.py)
  results_v2/per_run_v2.csv                      simulated per-run CPU (aggregate_v2.py)
  data_v2_real/fastapi/stream/c{1,25}_run{1..3}_stream_metrics.csv           Phase B chunks
  data_v2_real/phase_c/{fw}/stream/c1_run{1..3}_stream_metrics.csv           Phase C chunks
  data_v2/{fw}/stream/c{1,25}_run{1..5}_stream_metrics.csv                   simulated chunks
  analysis/out/paper_v2.1/numbers.csv
Outputs: analysis/out/paper_v2.1/step7_stream_cpu.csv and step7_ranges.csv; summary to stdout.
"""

import csv
import os
import re
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "analysis", "out", "paper_v2.1")
FWS = ["flask", "django", "fastapi", "tornado"]


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def mean_chunks(path):
    rows = [r for r in read(path) if r["success"] == "True"]
    return statistics.mean(float(r["token_count"]) for r in rows), len(rows)


def summ(vals):
    return statistics.median(vals), min(vals), max(vals), len(vals)


def main():
    rpr = read(os.path.join(ROOT, "analysis", "out", "final_real_per_run.csv"))
    sim = {}
    for r in read(os.path.join(ROOT, "results_v2", "per_run_v2.csv")):
        sim.setdefault((r["framework"], r["endpoint"], int(r["concurrency"])), []).append(r)

    def sim_cpu(fw, ep, c):
        return {int(r["run"]): float(r["cpu_ms_per_request"]) for r in sim[(fw, ep, c)]}

    def live_cpu(ph, fw, ep, c):
        return {int(r["run"]): float(r["cpu_ms_per_request"]) for r in rpr
                if r["phase"] == ph and r["framework"] == fw and r["endpoint"] == ep and r["concurrency"] == str(c)}

    rows = []

    def add(group, what, fw, c, src, vals, unit):
        med, lo, hi, n = summ(vals)
        rows.append(dict(group=group, quantity=what, framework=fw, concurrency=c, source=src, value=med,
                         range_low=lo, range_high=hi, n_runs=n, unit=unit))
        return med

    # (a1) inference CPU per request, live Phase A vs simulated
    inf_live, inf_sim = {}, {}
    for c in (1, 25):
        lv, sv = live_cpu("A", "fastapi", "inference", c), sim_cpu("fastapi", "inference", c)
        inf_live[c] = add("a1", "inference CPU per request", "fastapi", c, "live Phase A", list(lv.values()), "ms")
        inf_sim[c] = add("a1", "inference CPU per request", "fastapi", c, "simulated", list(sv.values()), "ms")
        rows.append(dict(group="a1", quantity="live / simulated inference CPU per request (ratio of medians)",
                         framework="fastapi", concurrency=c, source="live Phase A / simulated",
                         value=inf_live[c] / inf_sim[c], range_low=min(lv.values()) / max(sv.values()),
                         range_high=max(lv.values()) / min(sv.values()), n_runs="3+5",
                         unit="x (range: extreme run pairs)"))
    for c in (1, 5, 10, 25, 50, 100):
        for fw in FWS:
            inf_sim[(fw, c)] = statistics.median(sim_cpu(fw, "inference", c).values())

    # (a2) CPU per relayed chunk
    def per_chunk(group, fw, c, src, cpu_by_run, chunk_path, ref, refname):
        vals, chunks, streams, cpus = [], [], 0, []
        for run, cpu in sorted(cpu_by_run.items()):
            m, n = mean_chunks(chunk_path.format(run=run))
            vals.append((cpu - ref) / m)
            chunks.append(m)
            cpus.append(cpu)
            streams += n
        add(group, "stream CPU per request", fw, c, src, cpus, "ms")
        add(group, "mean chunks per response", fw, c, src, chunks, "chunks")
        add(group, f"CPU per relayed chunk (reference: {refname} = {ref:.2f} ms)", fw, c, src, vals, "ms per chunk")

    for c in (1, 25):
        per_chunk("a2", "fastapi", c, "live Phase B", live_cpu("B", "fastapi", "stream", c),
                  os.path.join(ROOT, "data_v2_real", "fastapi", "stream", f"c{c}_run{{run}}_stream_metrics.csv"),
                  inf_live[c], "live Phase A inference median")
        per_chunk("a2", "fastapi", c, "live Phase B", live_cpu("B", "fastapi", "stream", c),
                  os.path.join(ROOT, "data_v2_real", "fastapi", "stream", f"c{c}_run{{run}}_stream_metrics.csv"),
                  inf_sim[c], "simulated inference median (sensitivity)")
        per_chunk("a2", "fastapi", c, "simulated", sim_cpu("fastapi", "stream", c),
                  os.path.join(ROOT, "data_v2", "fastapi", "stream", f"c{c}_run{{run}}_stream_metrics.csv"),
                  inf_sim[c], "simulated inference median")
    for fw in FWS:
        per_chunk("a3", fw, 1, "live Phase C", live_cpu("C", fw, "stream", 1),
                  os.path.join(ROOT, "data_v2_real", "phase_c", fw, "stream", "c1_run{run}_stream_metrics.csv"),
                  inf_sim[(fw, 1)], "simulated inference median")
        if fw == "fastapi":
            per_chunk("a3", fw, 1, "live Phase C", live_cpu("C", fw, "stream", 1),
                      os.path.join(ROOT, "data_v2_real", "phase_c", fw, "stream", "c1_run{run}_stream_metrics.csv"),
                      inf_live[1], "live Phase A inference median (sensitivity)")
        per_chunk("a3", fw, 1, "simulated", sim_cpu(fw, "stream", 1),
                  os.path.join(ROOT, "data_v2", fw, "stream", "c1_run{run}_stream_metrics.csv"),
                  inf_sim[(fw, 1)], "simulated inference median")

    keys = ["group", "quantity", "framework", "concurrency", "source", "value", "range_low", "range_high", "n_runs", "unit"]
    with open(os.path.join(OUT, "step7_stream_cpu.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"{r['group']} {r['framework']:8s} c={r['concurrency']:<3} {r['source']:14s} {r['quantity'][:78]:78s} "
              f"{r['value']:9.3f} [{r['range_low']:.3f}, {r['range_high']:.3f}] n={r['n_runs']}")

    # (d) ranges
    num = {x["id"]: x for x in read(os.path.join(OUT, "numbers.csv"))}

    def rng(name, pat, note):
        ids = sorted(k for k in num if re.match(pat, k))
        v = [(float(num[k]["value"]), k) for k in ids]
        lo, hi = min(v), max(v)
        cl = min(float(num[k]["ci_low"]) for k in ids)
        ch = max(float(num[k]["ci_high"]) for k in ids)
        return dict(name=name, pattern=pat, n=len(ids), min=lo[0], min_id=lo[1], max=hi[0], max_id=hi[1],
                    interval_low=cl, interval_high=ch, note=note)

    sp = r"(flask|django|fastapi|tornado)"
    rr = [
        rng("idle USS, single-process, inference c = 1 (N.USSI1)", rf"USSI\.inf\.{sp}\.c1$", "as printed in 5.3"),
        rng("idle USS, single-process, all endpoints and levels", rf"USSI\.(inf|str|pip)\.{sp}\.c\d+$", ""),
        rng("idle USS, single-process, c = 100 (Table 4 cells)", rf"USSI\.(inf|str|pip)\.{sp}\.c100$", ""),
        rng("idle USS, Flask 17w, all endpoints and levels", r"USSI\.(inf|str|pip)\.flask17w\.c\d+$", ""),
        rng("idle USS, Django 17w, all endpoints and levels", r"USSI\.(inf|str|pip)\.django17w\.c\d+$", ""),
        rng("idle USS, Flask 17w, c = 100 (Table 4 cells)", r"USSI\.(inf|str|pip)\.flask17w\.c100$", ""),
        rng("idle USS, Django 17w, c = 100 (Table 4 cells)", r"USSI\.(inf|str|pip)\.django17w\.c100$", ""),
        rng("17w / async peak USS, c = 100, inference (Figure 3)", r"M17A\.inf\.", ""),
        rng("17w / async peak USS, c = 100, all endpoints (N.M17A)", r"M17A\.", ""),
        rng("steady-state mean / R, 17 workers, all endpoints (N.SSR17)", r"SSR\.(inf|str|pip)\.(flask|django)17w\.", ""),
        rng("steady-state mean / R, 17 workers, inference (Figure 2)", r"SSR\.inf\.(flask|django)17w\.", ""),
        rng("steady-state mean / R, one worker c = 5, 10, all endpoints (N.SSR1)", r"SSR\.(inf|str|pip)\.(flask|django)\.", ""),
        rng("steady-state mean / R, one worker, inference (Figure 2)", r"SSR\.inf\.(flask|django)\.", ""),
        rng("R / (c S / 17), 17 workers, c = 100 (N.RTH)", r"RTH\.", ""),
    ]
    with open(os.path.join(OUT, "step7_ranges.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rr[0].keys()))
        w.writeheader()
        w.writerows(rr)
    print()
    for r in rr:
        print(f"{r['name'][:70]:70s} n={r['n']:<3} {r['min']:.4f} ({r['min_id']}) to {r['max']:.4f} ({r['max_id']}); "
              f"interval envelope [{r['interval_low']:.4f}, {r['interval_high']:.4f}]")


if __name__ == "__main__":
    main()
