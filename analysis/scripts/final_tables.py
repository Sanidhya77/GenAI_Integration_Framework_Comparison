"""
Markdown tables for the RESULTS_FINAL appendix (read-only) -> analysis/out/final_tables.md.
Source: results_v2/summary_v2_long.csv, summary_v2.csv (aggregate_v2.py, 540 runs) and
analysis/out/final_mw.csv (cycle throughput for multi-worker c > 17).
"""

import csv
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "analysis", "out")
CFGS = ["flask", "django", "flask_mw", "django_mw", "fastapi", "tornado"]
NAME = {"flask": "Flask", "django": "Django", "flask_mw": "Flask 17w", "django_mw": "Django 17w",
        "fastapi": "FastAPI", "tornado": "Tornado"}
EPS = ["inference", "stream", "pipeline"]
CS = [1, 5, 10, 25, 50, 100]


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    L = {}
    for r in read(os.path.join(ROOT, "results_v2", "summary_v2_long.csv")):
        L[(r["framework"], r["endpoint"], int(r["concurrency"]), r["metric"])] = (
            float(r["median"]), float(r["min"]), float(r["max"]))
    wide = {(r["framework"], r["endpoint"], int(r["concurrency"])): r
            for r in read(os.path.join(ROOT, "results_v2", "summary_v2.csv"))}
    mw = {(r["config"], r["endpoint"], int(r["concurrency"])): r for r in read(os.path.join(OUT, "final_mw.csv"))}

    def v(fw, ep, c, k, i=0):
        x = L.get((fw, ep, c, k))
        return None if x is None else x[i]

    def f(x, nd=0, comma=True):
        if x is None:
            return "n/a"
        return f"{x:,.{nd}f}" if comma else f"{x:.{nd}f}"

    out = []
    for ep in EPS:
        s = float(mw[("flask", ep, 1)]["S_s"])
        out.append(f"\n#### A.1.{EPS.index(ep) + 1} {ep} (S = {s} s)\n")
        out.append("| cfg | c | X, req/s | share | mean, ms | p50, ms | p95, ms | p99, ms | cens | R = N/X, s |")
        out.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for fw in CFGS:
            for c in CS:
                m = mw[(fw, ep, c)]
                if m["x_cycle"]:
                    x, lo, hi = float(m["x_cycle"]), float(m["x_cycle_min"]), float(m["x_cycle_max"])
                    tag = "c"
                else:
                    x, lo, hi = (v(fw, ep, c, "throughput_completion_rate", i) for i in range(3))
                    tag = ""
                share = x / float(m["ceiling_rps"])
                out.append(f"| {NAME[fw]} | {c} | {x:.3f}{tag} | {share:.3f} | "
                           f"{f(v(fw, ep, c, 'latency_mean_ms'))} | {f(v(fw, ep, c, 'latency_p50_ms'))} | "
                           f"{f(v(fw, ep, c, 'latency_p95_ms'))} | {f(v(fw, ep, c, 'latency_p99_ms'))} | "
                           f"{wide[(fw, ep, c)]['percentiles_censored_runs']}/5 | {c / x:.1f} |")
    out.append("\n#### A.2 stream detail (ms)\n")
    out.append("| cfg | c | TTFT p50 | TTFT p95 | TTFT p99 | derived TTFT | TPOT p50 | TPOT p95 |")
    out.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for fw in CFGS:
        for c in CS:
            out.append(f"| {NAME[fw]} | {c} | {f(v(fw, 'stream', c, 'ttft_p50_ms'), 1)} | "
                       f"{f(v(fw, 'stream', c, 'ttft_p95_ms'), 1)} | {f(v(fw, 'stream', c, 'ttft_p99_ms'), 1)} | "
                       f"{f(v(fw, 'stream', c, 'derived_ttft_ms'))} | {f(v(fw, 'stream', c, 'tpot_p50_ms'), 2)} | "
                       f"{f(v(fw, 'stream', c, 'tpot_p95_ms'), 2)} |")
    out.append("\n#### A.3 pipeline stages (ms)\n")
    out.append("| cfg | c | Stage 2 p50 / p95 | Stage 3 p50 / p95 | server E2E p50 |")
    out.append("|---|--:|--:|--:|--:|")
    for fw in CFGS:
        for c in CS:
            out.append(f"| {NAME[fw]} | {c} | {f(v(fw, 'pipeline', c, 'stage2_p50_ms'), 2)} / "
                       f"{f(v(fw, 'pipeline', c, 'stage2_p95_ms'), 2)} | {f(v(fw, 'pipeline', c, 'stage3_p50_ms'), 1)} / "
                       f"{f(v(fw, 'pipeline', c, 'stage3_p95_ms'), 1)} | {f(v(fw, 'pipeline', c, 'e2e_server_p50_ms'), 1)} |")
    out.append("\n#### A.4 resources: server CPU mean (% of one core) / CPU ms per request / peak USS (MiB)\n")
    out.append("| ep | c | " + " | ".join(NAME[fw] for fw in CFGS) + " |")
    out.append("|---|--:|" + "--:|" * len(CFGS))
    for ep in EPS:
        for c in CS:
            out.append(f"| {ep} | {c} | " + " | ".join(
                f"{f(v(fw, ep, c, 'cpu_mean_loaded_pct'), 2)} / {f(v(fw, ep, c, 'cpu_ms_per_request'), 1)} / "
                f"{f(v(fw, ep, c, 'peak_uss_mb'), 1)}" for fw in CFGS) + " |")
    out.append("\nIdle USS at inference c = 1 (MiB, median of 5 runs; other cells in final_mw.csv): " +
               "; ".join(f"{NAME[fw]} {f(v(fw, 'inference', 1, 'idle_uss_mb'), 1)}" for fw in CFGS) + ".")
    text = "\n".join(out) + "\n"
    with open(os.path.join(OUT, "final_tables.md"), "w") as fh:
        fh.write(text)
    print(f"wrote analysis/out/final_tables.md ({len(text.encode())} bytes)")


if __name__ == "__main__":
    main()


def body_tables():
    """Section tables for RESULTS_FINAL -> analysis/out/tables/{mw,steady,real_runs,phase_c,modes}.md"""
    tdir = os.path.join(OUT, "tables")
    os.makedirs(tdir, exist_ok=True)
    mw = {(r["config"], r["endpoint"], int(r["concurrency"])): r for r in read(os.path.join(OUT, "final_mw.csv"))}
    ratio = {(r["endpoint"], int(r["concurrency"])): r for r in read(os.path.join(OUT, "final_mw_ratio.csv"))}
    ss = {(r["config"], r["endpoint"], int(r["concurrency"])): r for r in read(os.path.join(OUT, "final_steady_state.csv"))}

    def n(x, nd=0):
        return "n/a" if x in (None, "", "None") else f"{float(x):,.{nd}f}"

    t = ["| ep | c | ceiling 17/S, req/s | X_cycle, req/s (share) | async / 17w | p50, ms | steady mean, ms | "
         "R = N/X, ms | full mean, ms | CPU, % of 1 core | peak USS, MiB |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for ep in EPS:
        for c in (25, 50, 100):
            a, b = mw[("flask_mw", ep, c)], mw[("django_mw", ep, c)]
            sa, sb = ss[("flask_mw", ep, c)], ss[("django_mw", ep, c)]
            t.append(f"| {ep} | {c} | {n(a['ceiling_rps'], 4)} | {n(a['x_cycle'], 4)} ({n(a['share_cycle'], 4)}) / "
                     f"{n(b['x_cycle'], 4)} ({n(b['share_cycle'], 4)}) | {n(ratio[(ep, c)]['ratio_best'], 3)} | "
                     f"{n(a['latency_p50_ms'])} / {n(b['latency_p50_ms'])} | {n(sa['A_mean'])} / {n(sb['A_mean'])} | "
                     f"{n(a['R_best_ms'])} / {n(b['R_best_ms'])} | {n(a['latency_mean_ms'])} / {n(b['latency_mean_ms'])} | "
                     f"{n(a['cpu_mean_loaded_pct'], 2)} / {n(b['cpu_mean_loaded_pct'], 2)} | "
                     f"{n(a['peak_uss_mb'], 1)} / {n(b['peak_uss_mb'], 1)} |")
    open(os.path.join(tdir, "mw.md"), "w").write("\n".join(t) + "\n")

    t = ["| ep | c | async / 17w (X_cycle) [4 pairs] | theory c / min(c, 17) | async / 17w, rate / rate | "
         "async / 1-worker (rate) [4 pairs] | 17w / 1-worker |",
         "|---|--:|--:|--:|--:|--:|--:|"]
    for ep in EPS:
        for c in CS:
            r = ratio[(ep, c)]
            t.append(f"| {ep} | {c} | {n(r['ratio_best'], 3)} [{n(r['ratio_best_min'], 3)}, {n(r['ratio_best_max'], 3)}] | "
                     f"{n(r['theory'], 3)} | {n(r['ratio_rate'], 3)} | {n(r['async_over_single_rate'], 2)} "
                     f"[{n(r['async_over_single_rate_min'], 2)}, {n(r['async_over_single_rate_max'], 2)}] | "
                     f"{n(r['mw_over_single_sync'], 3)} |")
    open(os.path.join(tdir, "ratio.md"), "w").write("\n".join(t) + "\n")

    t = ["| ep | cfg | c | cut, s | n kept (A) | steady mean, ms | p50, ms | p95, ms | p99, ms | R = N/X, ms | "
         "mean / R | rule B mean, ms (n) | full mean, ms | understated by, % |",
         "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for ep in EPS:
        for fw, cs in (("flask", (5, 10)), ("flask_mw", (25, 50, 100))):
            for c in cs:
                r = ss[(fw, ep, c)]
                t.append(f"| {ep} | {NAME[fw]} | {c} | {n(r['cut_s'], 2)} | {r['A_n']} | {n(r['A_mean'])} | {n(r['A_p50'])} | "
                         f"{n(r['A_p95'])} | {n(r['A_p99'])} | {n(r['R_ms'])} | {n(r['A_mean_over_R'], 4)} | "
                         f"{n(r['B_mean'])} ({r['B_n']}) | {n(r['full_mean_agg'])} | "
                         f"{n(r['full_mean_understates_A_pct'], 1)} |")
    open(os.path.join(tdir, "steady.md"), "w").write("\n".join(t) + "\n")

    lv = read(os.path.join(OUT, "final_real_levels.csv"))
    t = ["| phase | fw | c | metric | pooled median / p95 (n) | run 1 / 2 / 3 median | run 1 / 2 / 3 p95 | "
         "max/min median | max/min p95 |",
         "|---|---|--:|---|--:|--:|--:|--:|--:|"]
    unit = {"latency_ms": "latency, ms", "ttft_ms": "TTFT, ms", "tpot_ms": "TPOT, ms", "chunks": "chunks"}
    for r in [x for x in lv if not (x["phase"] == "C" and x["metric"] == "chunks")]:
        nd = 0 if r["metric"] in ("latency_ms", "chunks") else (1 if r["metric"] == "ttft_ms" else 2)
        meds = " / ".join(n(x, nd) for x in r["run_medians"].split(";"))
        p95s = " / ".join(n(x, nd) for x in r["run_p95s"].split(";"))
        t.append(f"| {r['phase']} | {r['framework']} | {r['concurrency']} | {unit[r['metric']]} | "
                 f"{n(r['pooled_median'], nd)} / {n(r['pooled_p95'], nd)} ({r['pooled_n']}) | {meds} | {p95s} | "
                 f"{n(r['median_spread_ratio'], 3)} | {n(r['p95_spread_ratio'], 3)} |")
    open(os.path.join(tdir, "real_runs.md"), "w").write("\n".join(t) + "\n")

    pc = read(os.path.join(OUT, "final_phase_c.csv"))
    t = ["| fw | metric | today median / p95 (n, runs) | April median / p95 (n, runs) | today / April median | "
         "today run medians | April run medians | April block start (UTC) | simulated c = 1 p50 |",
         "|---|---|--:|--:|--:|--:|--:|---|--:|"]
    for r in [x for x in pc if x["metric"] != "chunks"]:
        nd = 0 if r["metric"] in ("latency_ms", "chunks") else (1 if r["metric"] == "ttft_ms" else 2)
        t.append(f"| {r['framework']} | {unit[r['metric']]} | {n(r['today_median'], nd)} / {n(r['today_p95'], nd)} "
                 f"({r['today_n']}, {r['today_runs']}) | {n(r['april_median'], nd)} / {n(r['april_p95'], nd)} "
                 f"({r['april_n']}, {r['april_runs']}) | {n(r['today_over_april_median'], 3)} | "
                 f"{', '.join(n(x, nd) for x in r['today_run_medians'].split(';'))} | "
                 f"{', '.join(n(x, nd) for x in r['april_run_medians'].split(';'))} | {r['april_first_utc'][:16]} | "
                 f"{n(r['sim_v2_c1_p50'], nd)} |")
    open(os.path.join(tdir, "phase_c.md"), "w").write("\n".join(t) + "\n")
    print("wrote analysis/out/tables/{mw,ratio,steady,real_runs,phase_c}.md")


body_tables()


def validate_sim_table():
    """Flagged rows of results_v2/validation_sim_vs_real.csv -> analysis/out/tables/validate_sim.md.
    Cause codes (INFERRED, as in RESULTS_V2 e): J jitter / right skew, Q sync queueing, P pooled TTFT,
    B Locust 2 s.f. bucket."""
    rows = [r for r in read(os.path.join(ROOT, "results_v2", "validation_sim_vs_real.csv")) if r["flag"] == "True"]

    def cause(r):
        m, c, ep = r["metric"], int(r["concurrency"]), r["endpoint"]
        if m.startswith("ttft"):
            return "Q, P" if (r["framework"] in ("flask", "django") and c > 1) else "P"
        if m.startswith("median") and ep in ("inference", "pipeline"):
            return "B"
        if m.startswith("mean") and r["framework"] in ("flask", "django") and c > 1:
            return "Q"
        return "J"

    t = ["| fw | endpoint | c | metric | sim | real (thesis) | diff, % | cause (INFERRED) |",
         "|---|---|--:|---|--:|--:|--:|---|"]
    for r in rows:
        nd = 3 if "throughput" in r["metric"] else 1
        met = {"mean_latency_ms": "mean, ms", "median_latency_ms": "median, ms", "throughput_rps": "X, req/s",
               "ttft_ms": "TTFT, ms"}.get(r["metric"], r["metric"])
        t.append(f"| {r['framework']} | {r['endpoint']} | {r['concurrency']} | {met} | {float(r['sim']):,.{nd}f} | "
                 f"{float(r['real']):,.{nd}f} | {float(r['delta_pct']):+.2f} | {cause(r)} |")
    open(os.path.join(OUT, "tables", "validate_sim.md"), "w").write("\n".join(t) + "\n")
    print(f"wrote analysis/out/tables/validate_sim.md ({len(rows)} flagged rows)")


validate_sim_table()
