"""
Steady-state latency of the sync servers for RESULTS_FINAL (read-only, data_v2/).

Configurations: single-worker Flask and Django at c = 5, 10 (and 25, 50, 100 to show that no request
qualifies), and 17-worker flask_mw and django_mw at c = 25, 50, 100 (c > 17).

Rule A (primary, as specified): drop every request that STARTED before t0 + ceil(c / w) x S, where
  t0 = first_user_start_mono (locust_meta), w = 1 (single worker) or 17 (multi-worker), S = the
  calibrated service time of the endpoint. ceil(c / w) x S is the time needed to serve the c
  requests issued during the paced ramp once (the first queue cycle): c x S for one worker.
Rule B (sensitivity): drop only each user's first request (the c requests issued during the ramp,
  which see a partly empty queue); keep everything else.
Both keep successful requests that completed before Locust stopped (requests still in flight at stop
are right-censored; the number started after the rule A cut and still in flight is reported).

Statistics pooled over the 5 runs' requests (median, p95, p99 linear; mean), plus the median over
runs of the per-run mean. Compared with R = N / X (aggregate_v2 response_law_R_ms from the completion
rate; for multi-worker c > 17 from the cycle estimator of final_mw.py) and with the full-window
values (all successful requests, as in the main tables).

Output: analysis/out/final_steady_state.csv
"""

import csv
import json
import math
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "analysis", "out")
W = 17


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(v, p):
    v = sorted(v)
    if not v:
        return None
    k = (len(v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def summ(v):
    if not v:
        return dict(n=0, mean=None, p50=None, p95=None, p99=None)
    return dict(n=len(v), mean=statistics.mean(v), p50=pct(v, 50), p95=pct(v, 95),
                p99=pct(v, 99) if len(v) >= 100 else None)


def main():
    per_run = read(os.path.join(ROOT, "results_v2", "per_run_v2.csv"))
    mw = {(r["config"], r["endpoint"], int(r["concurrency"])): r for r in read(os.path.join(OUT, "final_mw.csv"))}
    summ_long = {}
    for r in read(os.path.join(ROOT, "results_v2", "summary_v2_long.csv")):
        summ_long[(r["framework"], r["endpoint"], int(r["concurrency"]), r["metric"])] = float(r["median"])
    configs = [(fw, c) for fw in ("flask", "django") for c in (5, 10, 25, 50, 100)] + \
              [(fw, c) for fw in ("flask_mw", "django_mw") for c in (25, 50, 100)]
    rows = []
    for ep in ("inference", "stream", "pipeline"):
        for fw, c in configs:
            w = W if fw.endswith("_mw") else 1
            runs = [r for r in per_run if r["framework"] == fw and r["endpoint"] == ep and int(r["concurrency"]) == c]
            s = float(runs[0]["service_time_s"])
            cut_s = math.ceil(c / w) * s
            full, ra, rb, ra_means, rb_means, ra_inflight = [], [], [], [], [], 0
            for r in runs:
                prefix = os.path.join(ROOT, "data_v2", fw, ep, f"c{c}_run{r['run']}")
                lm = json.load(open(prefix + "_locust_meta.json"))
                t0 = lm["first_user_start_mono"]
                req = [x for x in read(prefix + "_requests.csv")]
                ok = [x for x in req if x["success"] == "True"]
                full += [float(x["response_time_ms"]) for x in ok]
                a = [float(x["response_time_ms"]) for x in ok if float(x["start_mono"]) >= t0 + cut_s]
                seen, b = set(), []
                for x in sorted(req, key=lambda x: float(x["start_mono"])):
                    first = x["user"] not in seen
                    seen.add(x["user"])
                    if not first and x["success"] == "True":
                        b.append(float(x["response_time_ms"]))
                ra += a
                rb += b
                if a:
                    ra_means.append(statistics.mean(a))
                if b:
                    rb_means.append(statistics.mean(b))
                ra_inflight += sum(1 for x in read(prefix + "_inflight.csv") if float(x["issued_mono"]) >= t0 + cut_s)
            if fw.endswith("_mw"):
                r_ms = float(mw[(fw, ep, c)]["R_best_ms"])
                r_src = "c / X_cycle (final_mw.csv)"
            else:
                r_ms = summ_long[(fw, ep, c, "response_law_R_ms")]
                r_src = "aggregate_v2 response_law_R_ms (completion rate)"
            f, a, b = summ(full), summ(ra), summ(rb)
            row = dict(endpoint=ep, config=fw, concurrency=c, workers=w, S_s=s, cut_s=cut_s, runs=len(runs),
                       R_ms=r_ms, R_source=r_src,
                       full_n=f["n"], full_mean=f["mean"], full_p50=f["p50"], full_p95=f["p95"], full_p99=f["p99"],
                       full_mean_agg=summ_long[(fw, ep, c, "latency_mean_ms")],
                       A_n=a["n"], A_mean=a["mean"], A_p50=a["p50"], A_p95=a["p95"], A_p99=a["p99"],
                       A_run_mean_median=statistics.median(ra_means) if ra_means else None,
                       A_runs_with_data=len(ra_means), A_inflight_at_stop=ra_inflight,
                       B_n=b["n"], B_mean=b["mean"], B_p50=b["p50"], B_p95=b["p95"], B_p99=b["p99"],
                       B_run_mean_median=statistics.median(rb_means) if rb_means else None)
            row["A_mean_over_R"] = row["A_mean"] / r_ms if row["A_mean"] else None
            row["B_mean_over_R"] = row["B_mean"] / r_ms if row["B_mean"] else None
            row["full_mean_over_R"] = row["full_mean"] / r_ms
            row["full_mean_agg_over_R"] = row["full_mean_agg"] / r_ms
            row["full_mean_understates_A_pct"] = ((1 - row["full_mean_agg"] / row["A_mean"]) * 100
                                                  if row["A_mean"] else None)
            row["consistency_agg"] = summ_long.get((fw, ep, c, "closed_system_consistency"))
            rows.append(row)

    def f(x, nd=0):
        return "-" if x is None else f"{x:,.{nd}f}"

    print("Rule A: drop requests started before t0 + ceil(c / w) x S; Rule B: drop each user's first request.")
    print("ms; pooled over 5 runs; R = N / X.")
    for r in rows:
        print(f"  {r['endpoint']:9} {r['config']:9} c{r['concurrency']:<3} cut {r['cut_s']:6.2f} s | R {f(r['R_ms'])} | "
              f"full n {r['full_n']} mean {f(r['full_mean'])} (agg {f(r['full_mean_agg'])}) p50 {f(r['full_p50'])} "
              f"p95 {f(r['full_p95'])} | A n {r['A_n']} (runs {r['A_runs_with_data']}, in flight {r['A_inflight_at_stop']}) "
              f"mean {f(r['A_mean'])} p50 {f(r['A_p50'])} p95 {f(r['A_p95'])} p99 {f(r['A_p99'])} | B n {r['B_n']} "
              f"mean {f(r['B_mean'])} p50 {f(r['B_p50'])} p95 {f(r['B_p95'])} p99 {f(r['B_p99'])} | A/R "
              f"{f(r['A_mean_over_R'], 4)} B/R {f(r['B_mean_over_R'], 4)} agg-full/R {f(r['full_mean_agg_over_R'], 4)} "
              f"understatement {f(r['full_mean_understates_A_pct'], 1)} % | consistency {f(r['consistency_agg'], 3)}")
    with open(os.path.join(OUT, "final_steady_state.csv"), "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print("Saved analysis/out/final_steady_state.csv")


if __name__ == "__main__":
    main()
