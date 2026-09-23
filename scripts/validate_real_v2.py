"""
Analysis of the real-API validation (data_v2_real/, written by scripts/run_real_validation.py).

Per phase (A = FastAPI inference, B = FastAPI stream):
  1. drift        c = 1 today (data_v2_real) vs c = 1 in the thesis data (data/)
  2. load         c = 25 today vs c = 1 today (load dependence of API latency and TTFT)
  3. throughput   c = 25 today, completion rate in the steady window [first user start + 2 S, stop]
                  and Locust Requests/s, vs the ceiling 25 / S_today (S_today = c = 1 today median)
  4. sim vs real  c = 25 real vs v2 simulated c = 25 (data_v2/), absolute and after scaling the
                  simulated latencies by S_today / S_sim (throughput by S_sim / S_today);
                  S_sim = simulated c = 1 median latency if data_v2 has it, else the calibrated
                  service time

Statistics are pooled over the runs' per-request rows (median and p95, linear interpolation),
with n requests and n runs stated. Exception: the thesis inference data has no per-request log,
so its c = 1 latency is the median over runs of Locust's per-run median / 95 % values (Locust
buckets to about 2 significant figures); this is labelled in the output.

Runs whose meta.json is not "complete" (for example "invalid" after a retry) are excluded.

Usage:
  venv/bin/python scripts/validate_real_v2.py [--phase a|b|all] [--real data_v2_real]
      [--sim data_v2] [--thesis data] [--out results_v2]
"""

import argparse
import csv
import glob
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIBRATION = os.path.join(ROOT, "simulated_endpoint", "calibration_v2.json")
FRAMEWORK = "fastapi"
PHASES = {"a": "inference", "b": "stream"}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(values, p):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def fnum(x):
    return None if x in (None, "", "None", "N/A") else float(x)


def complete_prefixes(root, ep, c, require_meta=True):
    out = []
    for stats in sorted(glob.glob(os.path.join(root, FRAMEWORK, ep, f"c{c}_run*_stats.csv"))):
        prefix = stats[:-len("_stats.csv")]
        meta = prefix + "_meta.json"
        if os.path.exists(meta):
            if json.load(open(meta)).get("status") != "complete":
                continue
        elif require_meta:
            continue
        out.append(prefix)
    return out


class Sample:
    """Pooled per-request values from a set of runs."""

    def __init__(self, label, prefixes, ep, source):
        self.label, self.runs, self.source = label, len(prefixes), source
        self.lat, self.ttft, self.tpot, self.tokens = [], [], [], []
        self.locust_median, self.locust_p95, self.locust_n = [], [], 0
        for p in prefixes:
            if source == "per_request":
                self.lat += [float(r["response_time_ms"]) for r in read_csv(p + "_requests.csv")
                             if r["success"] == "True"]
            elif source == "thesis_stream":
                pass  # filled from stream_metrics below
            else:  # thesis inference: Locust per-run aggregates only
                agg = [r for r in read_csv(p + "_stats.csv") if r["Name"] == "Aggregated"][0]
                self.locust_median.append(float(agg["Median Response Time"]))
                self.locust_p95.append(float(agg["95%"]))
                self.locust_n += int(agg["Request Count"])
            if ep == "stream":
                sm = [r for r in read_csv(p + "_stream_metrics.csv") if r["success"] == "True"]
                if source == "thesis_stream":
                    self.lat += [float(r["total_time_ms"]) for r in sm]
                self.ttft += [fnum(r["ttft_ms"]) for r in sm if fnum(r["ttft_ms"]) is not None]
                self.tpot += [fnum(r["tpot_ms"]) for r in sm if fnum(r["tpot_ms"]) is not None]
                self.tokens += [int(r["token_count"]) for r in sm]

    def empty(self):
        return self.runs == 0

    def latency(self):
        if self.source == "thesis_inference":
            return (statistics.median(self.locust_median), statistics.median(self.locust_p95), self.locust_n,
                    "Locust per-run median / 95 %, median over runs (2 s.f. buckets)")
        return statistics.median(self.lat), pct(self.lat, 95), len(self.lat), "per-request pooled"

    def metric(self, name):
        if name == "latency_ms":
            return self.latency()
        vals = {"ttft_ms": self.ttft, "tpot_ms": self.tpot, "token_count": self.tokens}[name]
        if not vals:
            return None
        return statistics.median(vals), pct(vals, 95), len(vals), "per-request pooled"


def throughput(prefixes, s):
    """Pooled over runs: median of per-run completion rate in [t0 + 2 s, stop], and Locust RPS."""
    rates, locust = [], []
    for p in prefixes:
        lm = json.load(open(p + "_locust_meta.json"))
        lo, hi = lm["first_user_start_ts"] + 2 * s, lm["stop_ts"]
        ends = sorted(float(r["end_ts"]) for r in read_csv(p + "_requests.csv")
                      if r["success"] == "True" and lo <= float(r["end_ts"]) <= hi)
        if len(ends) >= 2 and ends[-1] > ends[0]:
            rates.append((len(ends) - 1) / (ends[-1] - ends[0]))
        agg = [r for r in read_csv(p + "_stats.csv") if r["Name"] == "Aggregated"][0]
        locust.append(float(agg["Requests/s"]))
    return (statistics.median(rates) if rates else None, statistics.median(locust) if locust else None, len(rates))


def fmt(x, nd=1):
    return "n/a" if x is None else f"{x:.{nd}f}"


def compare(rows, phase, comparison, metric, a, b, scale_b=1.0):
    ma, mb = a.metric(metric), b.metric(metric)
    if ma is None or mb is None:
        return
    rows.append({
        "phase": phase, "comparison": comparison, "metric": metric,
        "a": a.label, "a_median": ma[0], "a_p95": ma[1], "a_n": ma[2], "a_runs": a.runs, "a_method": ma[3],
        "b": b.label, "b_median": mb[0] * scale_b, "b_p95": mb[1] * scale_b, "b_n": mb[2], "b_runs": b.runs,
        "b_method": mb[3] + (f", scaled x{scale_b:.4f}" if scale_b != 1.0 else ""),
        "median_ratio_a_over_b": ma[0] / (mb[0] * scale_b) if mb[0] else None,
        "p95_ratio_a_over_b": ma[1] / (mb[1] * scale_b) if mb[1] else None,
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="all", choices=["a", "b", "all"])
    ap.add_argument("--real", default="data_v2_real")
    ap.add_argument("--sim", default="data_v2")
    ap.add_argument("--thesis", default="data")
    ap.add_argument("--out", default="results_v2")
    a = ap.parse_args()
    real, sim, thesis = (os.path.join(ROOT, x) for x in (a.real, a.sim, a.thesis))
    cal = json.load(open(CALIBRATION))["values"]
    phases = ["a", "b"] if a.phase == "all" else [a.phase]
    rows, tp_rows = [], []

    for ph in phases:
        ep = PHASES[ph]
        today1 = Sample("real c1 today", complete_prefixes(real, ep, 1), ep, "per_request")
        today25 = Sample("real c25 today", complete_prefixes(real, ep, 25), ep, "per_request")
        thesis1 = Sample("real c1 thesis", complete_prefixes(thesis, ep, 1, require_meta=False), ep,
                         "thesis_stream" if ep == "stream" else "thesis_inference")
        sim1_p, sim25_p = complete_prefixes(sim, ep, 1), complete_prefixes(sim, ep, 25)
        sim1 = Sample("sim c1 v2", sim1_p, ep, "per_request")
        sim25 = Sample("sim c25 v2", sim25_p, ep, "per_request")
        print(f"\n===== PHASE {ph.upper()}: {FRAMEWORK} {ep}  (runs: today c1 {today1.runs}, today c25 {today25.runs}, "
              f"thesis c1 {thesis1.runs}, sim c1 {sim1.runs}, sim c25 {sim25.runs})")
        if today1.empty() or today25.empty():
            print("  real-API data missing for this phase; nothing to compare")
            continue
        metrics = ["latency_ms"] + (["ttft_ms", "tpot_ms", "token_count"] if ep == "stream" else [])

        for m in metrics:
            compare(rows, ph, "1 drift: c1 today vs c1 thesis", m, today1, thesis1)
            compare(rows, ph, "2 load: c25 today vs c1 today", m, today25, today1)

        s_today = today1.latency()[0] / 1000
        rate, locust_rps, n_rate = throughput(complete_prefixes(real, ep, 25), s_today)
        ceiling = 25 / s_today
        tp_rows.append({"phase": ph, "comparison": "3 throughput: c25 today vs 25 / S_today",
                        "S_today_s": s_today, "ceiling_rps": ceiling, "completion_rate_rps": rate,
                        "share": rate / ceiling if rate else None, "locust_rps": locust_rps, "runs": n_rate})

        if not sim25.empty():
            if not sim1.empty():
                s_sim, s_sim_src = sim1.latency()[0] / 1000, "sim c1 v2 median latency"
            else:
                s_sim, s_sim_src = cal["service_time_s"][ep], "calibrated service time"
            factor = s_today / s_sim
            for m in metrics:
                compare(rows, ph, "4a real vs sim c25 (absolute)", m, today25, sim25)
                if m != "token_count":
                    compare(rows, ph, f"4b real vs sim c25 (sim scaled by S_today/S_sim, S_sim = {s_sim_src})",
                            m, today25, sim25, scale_b=factor)
            sim_rate, sim_locust, sim_n = throughput(sim25_p, s_sim)
            tp_rows.append({"phase": ph, "comparison": "4 throughput: sim c25 v2, scaled by S_sim / S_today",
                            "S_today_s": s_today, "S_sim_s": s_sim, "ceiling_rps": ceiling,
                            "completion_rate_rps": sim_rate * s_sim / s_today if sim_rate else None,
                            "share": (sim_rate * s_sim / s_today) / ceiling if sim_rate else None,
                            "locust_rps": sim_locust * s_sim / s_today if sim_locust else None, "runs": sim_n})
        else:
            print("  simulated c25 data (data_v2) missing; comparison 4 skipped")

        for r in [x for x in rows if x["phase"] == ph]:
            print(f"  {r['comparison']}\n    {r['metric']:12s} {r['a']}: median {fmt(r['a_median'])} p95 {fmt(r['a_p95'])} "
                  f"(n={r['a_n']}, runs={r['a_runs']})  |  {r['b']}: median {fmt(r['b_median'])} p95 {fmt(r['b_p95'])} "
                  f"(n={r['b_n']}, runs={r['b_runs']}; {r['b_method']})  |  ratio median {fmt(r['median_ratio_a_over_b'], 3)} "
                  f"p95 {fmt(r['p95_ratio_a_over_b'], 3)}")
        for t in [x for x in tp_rows if x["phase"] == ph]:
            print(f"  {t['comparison']}: completion rate {fmt(t['completion_rate_rps'], 3)} rps, Locust "
                  f"{fmt(t['locust_rps'], 3)} rps, ceiling 25 / {t['S_today_s']:.3f} s = {t['ceiling_rps']:.3f} rps, "
                  f"share {fmt(t['share'], 3)} (runs={t['runs']})")

    os.makedirs(os.path.join(ROOT, a.out), exist_ok=True)
    if rows:
        path = os.path.join(ROOT, a.out, "validation_real_v2.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\nSaved {os.path.relpath(path, ROOT)}")
    if tp_rows:
        path = os.path.join(ROOT, a.out, "validation_real_v2_throughput.csv")
        keys = sorted({k for t in tp_rows for k in t}, key=lambda k: (k not in ("phase", "comparison"), k))
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(tp_rows)
        print(f"Saved {os.path.relpath(path, ROOT)}")


if __name__ == "__main__":
    main()
