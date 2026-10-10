"""
Step 10 (10 Oct 2026): extra values for the paper, read from existing data only (no server, no API call).

(b1) Thesis one-worker sync throughput at c = 100, inference, behind the printed "0.34 req/s" (P.th.sync).
     Per run: Locust "Requests/s" of the Aggregated row of data/{flask,django}/inference/c100_run{1..5}_stats.csv
     (thesis harness, April 2026; the same files as tag thesis-v1). Value: mean of the Flask and Django medians
     (the rule of P.v2sync); relation to P.v2sync (numbers.csv v2.1): v2 / thesis - 1 and 1 - thesis / v2.
     Comparison of the runs with the v2 runs of the same cells: v2 completion rate (throughput_completion_rate)
     and v2 Locust Requests/s (locust_rps) of results_v2/per_run_v2.csv.
     Shortest request per run: Locust "Min Response Time" of the same stats files (thesis) and of
     data_v2/{flask,django}/inference/c100_run{1..5}_stats.csv (v2); difference of the per-framework medians.
(b4) Thesis server memory carried over between runs: FastAPI RSS at the first monitor sample of each simulated thesis run
     (data/fastapi/{inference,stream,pipeline}/c{25,50,100}_run{1..5}_resources.csv, column rss_mb = RSS / 1024^2, i.e. MiB;
     thesis monitoring/resource_monitor.py), runs in the order of their first timestamp.
(c5) Simulator CPU in the simulated runs: sim_cpu_mean_pct of results_v2/per_run_v2.csv (mean CPU of the
     simulator process over the loaded window [t0, stop], % of one core; scripts/aggregate_v2.py), async servers
     at c = 100 on the three endpoints. Value: median of the 5 runs; interval: [min, max] of the 5 runs.
(c7) Text chunks per live stream at c = 1, Phase C (28 Sep 2026): token_count of the successful streams in
     data_v2_real/phase_c/{fw}/stream/c1_run{1..3}_stream_metrics.csv. Value: median pooled over the 3 runs;
     interval: [min, max] of the 3 per-run medians (as VB.chunks.p50.c1).

Output: analysis/out/paper_v2.1/step10_extra.csv; summary to stdout.
"""

import csv
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "analysis", "out", "paper_v2.1", "step10_extra.csv")
FWS = ["flask", "django", "fastapi", "tornado"]


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def aggregated(path):
    return next(r for r in read(path) if r["Name"] == "Aggregated")


def main():
    rows = []

    def add(rid, quantity, value, low, high, n, unit, formula, sources):
        rows.append(dict(id=rid, quantity=quantity, value=value, range_low=low, range_high=high, n=n, unit=unit,
                         formula=formula, sources=sources))

    num = {r["id"]: r for r in read(os.path.join(ROOT, "analysis", "out", "paper_v2.1", "numbers.csv"))}
    v2sync = float(num["P.v2sync"]["value"])
    per_run = read(os.path.join(ROOT, "results_v2", "per_run_v2.csv"))

    # (b1) thesis one-worker sync throughput, c = 100, inference
    th_rps, th_min, v2_min = {}, {}, {}
    for fw in ["flask", "django"]:
        th_rps[fw], th_min[fw], v2_min[fw] = [], [], []
        for k in range(1, 6):
            a = aggregated(os.path.join(ROOT, "data", fw, "inference", f"c100_run{k}_stats.csv"))
            th_rps[fw].append(float(a["Requests/s"]))
            th_min[fw].append(float(a["Min Response Time"]))
            b = aggregated(os.path.join(ROOT, "data_v2", fw, "inference", f"c100_run{k}_stats.csv"))
            v2_min[fw].append(float(b["Min Response Time"]))
        src = f"data/{fw}/inference/c100_run1..5_stats.csv (Aggregated, Requests/s)"
        add(f"S10.th.sync.{fw}", f"thesis one-worker throughput, {fw}, inference, c = 100 (Locust Requests/s)",
            statistics.median(th_rps[fw]), min(th_rps[fw]), max(th_rps[fw]), 5, "req/s",
            "median of the 5 per-run values; range: min and max of the 5", src)
    th_sync = statistics.mean([statistics.median(th_rps["flask"]), statistics.median(th_rps["django"])])
    all_th = th_rps["flask"] + th_rps["django"]
    add("S10.th.sync", "thesis one-worker throughput, inference, c = 100 (mean of the Flask and Django medians)",
        th_sync, min(all_th), max(all_th), "5+5", "req/s",
        "mean of S10.th.sync.flask and S10.th.sync.django (rule of P.v2sync); range: min and max of the 10 runs",
        "data/{flask,django}/inference/c100_run1..5_stats.csv")
    add("S10.th.sync.below", "thesis value below v2 (P.v2sync)", 100 * (1 - th_sync / v2sync), "", "", "", "%",
        f"(1 - S10.th.sync / P.v2sync) x 100, P.v2sync = {v2sync}", "numbers.csv v2.1 (P.v2sync)")
    add("S10.th.sync.diff", "v2 (P.v2sync) above the thesis value", 100 * (v2sync / th_sync - 1), "", "", "", "%",
        "(P.v2sync / S10.th.sync - 1) x 100", "numbers.csv v2.1 (P.v2sync)")
    v2_cr = [float(r["throughput_completion_rate"]) for r in per_run
             if r["endpoint"] == "inference" and r["concurrency"] == "100" and r["framework"] in ("flask", "django")
             and r["model"] == "sync_single"]
    v2_lr = [float(r["locust_rps"]) for r in per_run
             if r["endpoint"] == "inference" and r["concurrency"] == "100" and r["framework"] in ("flask", "django")
             and r["model"] == "sync_single"]
    add("S10.v2.sync.runs.cr", "v2 one-worker runs, inference, c = 100, completion rate (range of the 10 runs)",
        "", min(v2_cr), max(v2_cr), len(v2_cr), "req/s", "min and max of throughput_completion_rate",
        "results_v2/per_run_v2.csv")
    add("S10.v2.sync.runs.locust", "v2 one-worker runs, inference, c = 100, Locust Requests/s (range of the 10 runs)",
        "", min(v2_lr), max(v2_lr), len(v2_lr), "req/s", "min and max of locust_rps", "results_v2/per_run_v2.csv")
    add("S10.th.below.all", "every thesis run below every v2 run (both v2 estimators)",
        int(max(all_th) < min(v2_cr) and max(all_th) < min(v2_lr)), "", "", "", "1 = yes",
        "max(thesis runs) < min(v2 runs)", "as above")
    for fw in ["flask", "django"]:
        d = statistics.median(th_min[fw]) - statistics.median(v2_min[fw])
        add(f"S10.minlat.{fw}", f"shortest request per run, {fw}, inference, c = 100: thesis median - v2 median",
            d, min(th_min[fw]) - max(v2_min[fw]), max(th_min[fw]) - min(v2_min[fw]), "5+5", "ms",
            "median of the 5 thesis per-run minima - median of the 5 v2 per-run minima; range: smallest and largest "
            f"difference of a thesis and a v2 run (thesis {min(th_min[fw]):.1f} to {max(th_min[fw]):.1f} ms, "
            f"v2 {min(v2_min[fw]):.1f} to {max(v2_min[fw]):.1f} ms)",
            f"data/{fw}/inference/c100_run1..5_stats.csv and data_v2/{fw}/inference/c100_run1..5_stats.csv "
            "(Aggregated, Min Response Time)")

    # (b4) thesis FastAPI RSS before each simulated run
    import glob
    before = []
    for f in glob.glob(os.path.join(ROOT, "data", "fastapi", "*", "c*_run*_resources.csv")):
        c = int(os.path.basename(f).split("_")[0][1:])
        if c < 25:
            continue
        r0 = read(f)[0]
        before.append((float(r0["timestamp"]), os.path.relpath(f, ROOT), float(r0["rss_mb"])))
    before.sort()
    mx = max(before, key=lambda x: x[2])
    add("S10.th.rssbefore.fastapi.first", "thesis FastAPI RSS before its first simulated run", before[0][2], "", "", 1,
        "MiB", "first sample (rss_mb) of the earliest simulated run", before[0][1])
    add("S10.th.rssbefore.fastapi.max", f"thesis FastAPI RSS before a simulated run, maximum over {len(before)} runs",
        mx[2], min(b[2] for b in before), mx[2], len(before), "MiB",
        "max of the first samples (rss_mb); range: min and max over the runs", mx[1])

    # (c5) simulator CPU
    for ep, short in [("inference", "inf"), ("stream", "str"), ("pipeline", "pip")]:
        for fw in ["fastapi", "tornado"]:
            v = [float(r["sim_cpu_mean_pct"]) for r in per_run
                 if r["endpoint"] == ep and r["concurrency"] == "100" and r["framework"] == fw]
            add(f"S10.simcpu.{short}.{fw}.c100", f"simulator CPU, {fw} runs, {ep}, c = 100",
                statistics.median(v), min(v), max(v), len(v), "% of one core",
                "median of the 5 per-run sim_cpu_mean_pct; range: min and max of the 5",
                "results_v2/per_run_v2.csv (sim_cpu_mean_pct; data_v2/*/*/c100_run*_sim_monitor.csv)")

    # (c7) Phase C chunk counts
    for fw in FWS:
        pooled, per = [], []
        for k in range(1, 4):
            rr = [int(float(r["token_count"])) for r in
                  read(os.path.join(ROOT, "data_v2_real", "phase_c", fw, "stream", f"c1_run{k}_stream_metrics.csv"))
                  if r["success"] == "True"]
            pooled += rr
            per.append(statistics.median(rr))
        add(f"S10.vc.chunks.{fw}", f"live text chunks per stream, Phase C, {fw}, c = 1",
            statistics.median(pooled), min(per), max(per), 3, "chunks",
            f"median pooled over the {len(pooled)} successful streams of the 3 runs; range: min and max of the 3 "
            "per-run medians", f"data_v2_real/phase_c/{fw}/stream/c1_run1..3_stream_metrics.csv (token_count)")

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"{r['id']:28s} {r['value']!s:>22s} [{r['range_low']!s}, {r['range_high']!s}] {r['unit']}")


if __name__ == "__main__":
    main()
