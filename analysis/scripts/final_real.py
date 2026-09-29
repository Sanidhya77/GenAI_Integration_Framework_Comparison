"""
Real-API analysis for RESULTS_FINAL (read-only; no server, no API call).

Inputs
  data_v2_real/fastapi/{inference,stream}/c{1,25}_run{1..3}   Phases A and B (28 Sep 2026)
  data_v2_real/phase_c/{flask,django,fastapi,tornado}/stream/c1_run{1..3}   Phase C
  data/{fw}/stream/c1_run{1..5}_stream_metrics.csv             thesis real c = 1 stream (April 2026)
  results_v2/summary_v2_long.csv                               simulated c = 1 TTFT per framework

Per run: median and p95 (linear interpolation, as aggregate_v2.pct) of latency, TTFT, TPOT and
chunk count over successful requests; CPU and memory via aggregate_v2.run_metrics (same windows
as the main matrix). Per level: the same statistics pooled over the runs' requests, plus the
max / min ratio of the per-run values (run-to-run spread).

Phase C question (framework effect vs API drift): spread of framework medians today (interleaved
runs, 20 min) vs April (each framework's 5 runs in one block on a different day or time), and a
permutation test on per-run TTFT medians (statistic: between-group sum of squares).

Outputs: analysis/out/final_real_per_run.csv, final_real_levels.csv, final_phase_c.csv,
final_phase_c_test.csv, final_real_modes.csv. Console summary to stdout.
"""

import csv
import datetime
import glob
import itertools
import json
import os
import random
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import aggregate_v2 as ag  # noqa: E402

OUT = os.path.join(ROOT, "analysis", "out")
FWS = ["flask", "django", "fastapi", "tornado"]
CAL = json.load(open(ag.CALIBRATION))["values"]


def pct(v, p):
    return ag.pct(v, p)


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def utc(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")


def stats(vals):
    if not vals:
        return None, None, 0
    return statistics.median(vals), pct(vals, 95), len(vals)


def run_values(prefix, ep):
    """Per-request lists for one run (successful requests only)."""
    d = {}
    if ep == "stream":
        sm = [r for r in read(prefix + "_stream_metrics.csv") if r["success"] == "True"]
        d["latency_ms"] = [float(r["total_time_ms"]) for r in sm]
        d["ttft_ms"] = [float(r["ttft_ms"]) for r in sm if r["ttft_ms"] not in ("", "None")]
        d["tpot_ms"] = [float(r["tpot_ms"]) for r in sm if r["tpot_ms"] not in ("", "None")]
        d["chunks"] = [int(r["token_count"]) for r in sm]
        d["attempts"] = len(read(prefix + "_stream_metrics.csv"))
    else:
        req = read(prefix + "_requests.csv")
        d["latency_ms"] = [float(r["response_time_ms"]) for r in req if r["success"] == "True"]
        d["attempts"] = len(req)
    return d


def real_runs():
    """(phase, framework, endpoint, c, run, prefix) for every real run, meta status complete."""
    out = []
    for ep, ph in (("inference", "A"), ("stream", "B")):
        for p in sorted(glob.glob(os.path.join(ROOT, "data_v2_real", "fastapi", ep, "c*_run*_meta.json"))):
            if p.endswith("_locust_meta.json"):
                continue
            out.append((ph, "fastapi", ep, p))
    for fw in FWS:
        for p in sorted(glob.glob(os.path.join(ROOT, "data_v2_real", "phase_c", fw, "stream", "c*_run*_meta.json"))):
            if p.endswith("_locust_meta.json"):
                continue
            out.append(("C", fw, "stream", p))
    runs = []
    for ph, fw, ep, p in out:
        meta = json.load(open(p))
        if meta.get("status") != "complete":
            print(f"skip {p}: status {meta.get('status')}")
            continue
        prefix = p[:-len("_meta.json")]
        runs.append(dict(phase=ph, framework=fw, endpoint=ep, concurrency=int(meta["concurrency"]),
                         run=int(meta["run"]), prefix=prefix, meta=meta))
    return runs


def per_run_row(r):
    meta, prefix = r["meta"], r["prefix"]
    vals = run_values(prefix, r["endpoint"])
    m = ag.run_metrics(prefix, r["framework"], r["endpoint"], r["concurrency"], meta["service_time_s"], CAL, meta)
    row = {k: r[k] for k in ("phase", "framework", "endpoint", "concurrency", "run")}
    row["start_utc"] = utc(meta["run_start_ts"])
    row["attempts"] = vals["attempts"]
    for k in ("latency_ms", "ttft_ms", "tpot_ms", "chunks"):
        if k in vals:
            med, p95, n = stats(vals[k])
            row[f"{k}_median"], row[f"{k}_p95"], row[f"{k}_n"] = med, p95, n
    if "chunks" in vals:
        row["chunks_min"], row["chunks_max"] = min(vals["chunks"]), max(vals["chunks"])
    for k in ("throughput_completion_rate", "cpu_mean_loaded_pct", "cpu_max_loaded_pct", "cpu_ms_per_request",
              "idle_uss_mb", "peak_uss_mb", "idle_rss_mb", "peak_rss_mb", "error_rate_pct", "failures",
              "clock_rate_ratio", "clock_step_ms"):
        row[k] = m.get(k)
    rs = meta.get("retry_scan") or {}
    row["retry_lines"], row["http_429"], row["http_5xx"] = rs.get("retry_lines"), rs.get("http_429"), rs.get("http_5xx")
    row["_vals"], row["_prefix"] = vals, prefix
    return row


def thesis_c1(fw):
    """Thesis real c = 1 stream runs of one framework: [(run, first UTC, vals)]."""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", fw, "stream", "c1_run*_stream_metrics.csv"))):
        rows = read(p)
        sm = [r for r in rows if r["success"] == "True"]
        vals = {"latency_ms": [float(r["total_time_ms"]) for r in sm],
                "ttft_ms": [float(r["ttft_ms"]) for r in sm if r["ttft_ms"] not in ("", "None")],
                "tpot_ms": [float(r["tpot_ms"]) for r in sm if r["tpot_ms"] not in ("", "None")],
                "chunks": [int(float(r["token_count"])) for r in sm], "attempts": len(rows)}
        run = int(os.path.basename(p).split("_run")[1].split("_")[0])
        out.append((run, utc(min(float(r["timestamp"]) for r in rows)), vals))
    return out


def ss_between(groups):
    allv = [x for g in groups for x in g]
    gm = statistics.mean(allv)
    return sum(len(g) * (statistics.mean(g) - gm) ** 2 for g in groups)


def perm_test(groups, n_perm=200000, seed=1):
    """Permutation p-value for the between-group sum of squares (exact if small)."""
    obs = ss_between(groups)
    sizes = [len(g) for g in groups]
    pool = [x for g in groups for x in g]
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(pool)
        gs, i = [], 0
        for s in sizes:
            gs.append(pool[i:i + s])
            i += s
        if ss_between(gs) >= obs - 1e-12:
            hits += 1
    return obs, (hits + 1) / (n_perm + 1), n_perm


def main():
    os.makedirs(OUT, exist_ok=True)
    runs = [per_run_row(r) for r in real_runs()]

    # ---- per-run file
    keys = [k for k in runs[0] if not k.startswith("_")]
    for r in runs:
        for k in r:
            if k not in keys and not k.startswith("_"):
                keys.append(k)
    with open(os.path.join(OUT, "final_real_per_run.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(runs)

    # ---- per-level pooled + run-to-run spread
    levels = {}
    for r in runs:
        levels.setdefault((r["phase"], r["framework"], r["endpoint"], r["concurrency"]), []).append(r)
    lrows = []
    print("== Real-API levels: pooled median / p95 (n, runs); per-run medians and p95; max/min spread")
    for key, rs in levels.items():
        ph, fw, ep, c = key
        for k in ("latency_ms", "ttft_ms", "tpot_ms", "chunks"):
            if k not in rs[0]["_vals"]:
                continue
            pooled = [x for r in rs for x in r["_vals"][k]]
            med, p95, n = stats(pooled)
            meds = [r[f"{k}_median"] for r in rs]
            p95s = [r[f"{k}_p95"] for r in rs]
            row = dict(phase=ph, framework=fw, endpoint=ep, concurrency=c, metric=k, runs=len(rs),
                       pooled_median=med, pooled_p95=p95, pooled_n=n,
                       run_medians=";".join(f"{x:.3f}" for x in meds), run_p95s=";".join(f"{x:.3f}" for x in p95s),
                       run_n=";".join(str(r[f"{k}_n"]) for r in rs),
                       median_spread_ratio=max(meds) / min(meds), p95_spread_ratio=max(p95s) / min(p95s),
                       median_spread_abs=max(meds) - min(meds), p95_spread_abs=max(p95s) - min(p95s))
            lrows.append(row)
            print(f"  {ph} {fw:8} {ep:9} c{c:<3} {k:10} pooled {med:9.2f} / {p95:9.2f} (n={n}, runs={len(rs)}) | "
                  f"run medians {row['run_medians']} | run p95 {row['run_p95s']} | spread med x{row['median_spread_ratio']:.4f} "
                  f"p95 x{row['p95_spread_ratio']:.4f}")
    with open(os.path.join(OUT, "final_real_levels.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(lrows[0]))
        w.writeheader()
        w.writerows(lrows)

    # ---- resources per level (median over runs)
    print("\n== Real-API resources (median over runs [min, max])")
    for key, rs in levels.items():
        parts = []
        for k in ("cpu_mean_loaded_pct", "cpu_max_loaded_pct", "cpu_ms_per_request", "idle_uss_mb", "peak_uss_mb",
                  "throughput_completion_rate"):
            v = [r[k] for r in rs if r[k] is not None]
            if v:
                parts.append(f"{k} {statistics.median(v):.3f} [{min(v):.3f}, {max(v):.3f}]")
        print(f"  {key}: " + "; ".join(parts))
    bad = [f"{r['phase']}/{r['framework']}/c{r['concurrency']}/run{r['run']}: fail {r['failures']} retry "
           f"{r['retry_lines']} 429 {r['http_429']} 5xx {r['http_5xx']}"
           for r in runs if (r['failures'] or r['retry_lines'] or r['http_429'] or r['http_5xx'])]
    print("  errors: " + (", ".join(bad) if bad else
                          f"none (failures, retry lines, 429 and 5xx all 0 in all {len(runs)} real runs)"))
    print("  requests: " + ", ".join(f"{k[0]}/{k[1]}/c{k[3]}: {sum(r['latency_ms_n'] for r in rs)} ok of "
                                     f"{sum(r['attempts'] for r in rs)} logged" for k, rs in levels.items()))

    # ---- output modes: the API returned two kinds of response (see RESULTS_FINAL 5.4)
    print("\n== Output modes (inference: body 1,190 B vs other; stream: 101 chunks vs 16 to 100 vs <= 15)")
    mrows = []
    for key, rs in levels.items():
        ph, fw, ep, c = key
        for r in rs:
            prefix = r["_prefix"]
            if ep == "inference":
                req = [x for x in read(prefix + "_requests.csv") if x["success"] == "True"]
                groups = {"1190 B": [float(x["response_time_ms"]) for x in req if x["response_length"] == "1190"],
                          "other": [float(x["response_time_ms"]) for x in req if x["response_length"] != "1190"]}
            else:
                sm = [x for x in read(prefix + "_stream_metrics.csv") if x["success"] == "True"]
                groups = {"101 chunks": [float(x["total_time_ms"]) for x in sm if int(x["token_count"]) == 101],
                          "16-100 chunks": [float(x["total_time_ms"]) for x in sm if 16 <= int(x["token_count"]) <= 100],
                          "<=15 chunks": [float(x["total_time_ms"]) for x in sm if int(x["token_count"]) <= 15]}
            for g, v in groups.items():
                mrows.append(dict(phase=ph, framework=fw, endpoint=ep, concurrency=c, run=r["run"], mode=g, n=len(v),
                                  latency_median=statistics.median(v) if v else None,
                                  latency_p95=pct(v, 95) if v else None))
    for key in levels:
        ph, fw, ep, c = key
        for g in sorted({m["mode"] for m in mrows if (m["phase"], m["framework"], m["endpoint"], m["concurrency"]) == key}):
            rr = [m for m in mrows if (m["phase"], m["framework"], m["endpoint"], m["concurrency"]) == key and m["mode"] == g]
            print(f"  {ph} {fw:8} {ep:9} c{c:<3} {g:13}: per run n " + ",".join(str(m["n"]) for m in rr) +
                  " | median " + ",".join("-" if m["latency_median"] is None else f"{m['latency_median']:.0f}" for m in rr))
    # pooled by mode, Phase A and B, c1 vs c25
    for ep, g in (("inference", "1190 B"), ("inference", "other"), ("stream", "101 chunks"), ("stream", "16-100 chunks")):
        line = []
        for c in (1, 25):
            vals = []
            for r in runs:
                if not (r["phase"] in ("A", "B") and r["endpoint"] == ep and r["concurrency"] == c):
                    continue
                if ep == "inference":
                    req = [x for x in read(r["_prefix"] + "_requests.csv") if x["success"] == "True"]
                    vals += [float(x["response_time_ms"]) for x in req if (x["response_length"] == "1190") == (g == "1190 B")]
                else:
                    sm = [x for x in read(r["_prefix"] + "_stream_metrics.csv") if x["success"] == "True"]
                    vals += [float(x["total_time_ms"]) for x in sm
                             if (int(x["token_count"]) == 101 if g == "101 chunks" else 16 <= int(x["token_count"]) <= 100)]
            line.append((c, statistics.median(vals), len(vals)))
        print(f"  pooled {ep:9} {g:13}: c1 {line[0][1]:.1f} ms (n={line[0][2]}), c25 {line[1][1]:.1f} ms "
              f"(n={line[1][2]}), c25/c1 {line[1][1] / line[0][1]:.4f}")
    with open(os.path.join(OUT, "final_real_modes.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(mrows[0]))
        w.writeheader()
        w.writerows(mrows)

    # ---- Phase C vs thesis April c = 1, per framework
    sim = {}
    for r in read(os.path.join(ROOT, "results_v2", "summary_v2_long.csv")):
        if r["endpoint"] == "stream" and r["concurrency"] == "1" and r["framework"] in FWS:
            sim[(r["framework"], r["metric"])] = float(r["median"])
    crow, today_meds, april_meds = [], {}, {}
    print("\n== Phase C (today, 28 Sep 2026) vs thesis real c = 1 stream (April 2026), per framework")
    for fw in FWS:
        t_runs = [r for r in runs if r["phase"] == "C" and r["framework"] == fw]
        a_runs = thesis_c1(fw)
        today_meds[fw] = [r["ttft_ms_median"] for r in t_runs]
        april_meds[fw] = [statistics.median(v["ttft_ms"]) for _run, _ts, v in a_runs]
        for k in ("ttft_ms", "tpot_ms", "chunks", "latency_ms"):
            tv = [x for r in t_runs for x in r["_vals"][k]]
            av = [x for _run, _ts, v in a_runs for x in v[k]]
            tm, tp, tn = stats(tv)
            am, ap, an = stats(av)
            row = dict(framework=fw, metric=k,
                       today_median=tm, today_p95=tp, today_n=tn, today_runs=len(t_runs),
                       today_run_medians=";".join(f"{r[k + '_median']:.3f}" for r in t_runs),
                       today_first_utc=min(r["start_utc"] for r in t_runs),
                       april_median=am, april_p95=ap, april_n=an, april_runs=len(a_runs),
                       april_run_medians=";".join(f"{statistics.median(v[k]):.3f}" for _r, _t, v in a_runs),
                       april_first_utc=min(t for _r, t, _v in a_runs),
                       today_over_april_median=tm / am, today_over_april_p95=tp / ap,
                       sim_v2_c1_p50=sim.get((fw, {"ttft_ms": "ttft_p50_ms", "tpot_ms": "tpot_p50_ms",
                                                   "chunks": "token_count_p50", "latency_ms": "latency_p50_ms"}[k])))
            crow.append(row)
            print(f"  {fw:8} {k:10} today {tm:9.2f} / {tp:9.2f} (n={tn}, runs={len(t_runs)}) | April {am:9.2f} / "
                  f"{ap:9.2f} (n={an}, runs={len(a_runs)}, from {row['april_first_utc']}) | today/April "
                  f"{tm / am:.3f} / {tp / ap:.3f} | sim v2 c1 p50 {row['sim_v2_c1_p50']}")
    with open(os.path.join(OUT, "final_phase_c.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(crow[0]))
        w.writeheader()
        w.writerows(crow)

    # ---- spread across frameworks and permutation tests
    print("\n== Spread across the four frameworks (pooled medians)")
    trows = []
    for k in ("ttft_ms", "tpot_ms", "chunks", "latency_ms"):
        for era in ("today", "april"):
            meds = {r["framework"]: r[f"{era}_median"] for r in crow if r["metric"] == k}
            lo, hi = min(meds, key=meds.get), max(meds, key=meds.get)
            print(f"  {k:10} {era:5}: min {meds[lo]:.2f} ({lo}), max {meds[hi]:.2f} ({hi}), max - min "
                  f"{meds[hi] - meds[lo]:.2f}, max / min {meds[hi] / meds[lo]:.4f}")
            trows.append(dict(metric=k, era=era, min_fw=lo, min=meds[lo], max_fw=hi, max=meds[hi],
                              range=meds[hi] - meds[lo], ratio=meds[hi] / meds[lo]))
    for era, groups in (("today", today_meds), ("april", april_meds)):
        g = [groups[fw] for fw in FWS]
        within = [max(x) - min(x) for x in g]
        obs, p, n = perm_test(g)
        print(f"  TTFT run medians {era}: " + "; ".join(f"{fw} " + ",".join(f"{x:.1f}" for x in groups[fw]) for fw in FWS))
        print(f"    within-framework run range {min(within):.1f} to {max(within):.1f} ms; permutation test "
              f"(between-group SS {obs:.1f}, {n} permutations): p = {p:.4f}")
        trows.append(dict(metric="ttft_run_medians_perm_test", era=era, min_fw="", min=min(within), max_fw="",
                          max=max(within), range=obs, ratio=p))
    # FastAPI c = 1 stream within the day: Phase B anchor (16:25 to 16:30) vs Phase C (16:41 to 16:57)
    b1 = [r for r in runs if r["phase"] == "B" and r["concurrency"] == 1]
    c1 = [r for r in runs if r["phase"] == "C" and r["framework"] == "fastapi"]
    for k in ("ttft_ms", "tpot_ms", "chunks", "latency_ms"):
        bm = stats([x for r in b1 for x in r["_vals"][k]])
        cm = stats([x for r in c1 for x in r["_vals"][k]])
        print(f"  FastAPI c1 {k:10} Phase B {bm[0]:.2f} (n={bm[2]}) vs Phase C {cm[0]:.2f} (n={cm[2]}): ratio "
              f"{cm[0] / bm[0]:.4f}")
    with open(os.path.join(OUT, "final_phase_c_test.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trows[0]))
        w.writeheader()
        w.writerows(trows)
    print("\nSaved analysis/out/final_real_per_run.csv, final_real_levels.csv, final_phase_c.csv, final_phase_c_test.csv, "
          "final_real_modes.csv")


if __name__ == "__main__":
    main()
