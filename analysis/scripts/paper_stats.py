"""
Paper statistics for the v2 benchmark (read-only: no server, no Locust, no simulator, no API call).

Every number planned for the paper is recomputed from run-level values with the estimator of
RESULTS_FINAL.md, and given a 95 % confidence interval across runs plus the run range.

Estimators (value column), as in RESULTS_FINAL:
  simulated cells   median of the 5 per-run values (scripts/aggregate_v2.py rule); throughput =
                    completion rate, or the cycle estimator of final_mw.py for 17 workers at c > 17
  sync steady state rule A of final_steady_state.py (drop requests started before
                    t0 + ceil(c / w) S), statistics pooled over the 5 runs' requests
  censored sync     R = N/X = c / X per run, median of 5 (one worker, c >= 25)
  real API          statistics pooled over the runs' per-request values (validate_real_v2.py,
                    final_real.py); per-run CPU and memory medians (final_real_per_run.csv)
  ratios            as defined in RESULTS_FINAL (for example mean(FastAPI, Tornado) / mean(Flask,
                    Django) of the per-configuration medians)

Confidence intervals (ci_low, ci_high):
  one group of runs  t-interval of the mean of the per-run values: mean +/- t(0.975, n - 1) SD / sqrt(n)
                     (n = 5, df = 4, t = 2.7764; real API n = 3, df = 2, t = 4.3027). The value is
                     the RESULTS_FINAL estimator (a median or a pooled statistic), so it can lie
                     outside this interval; such rows are flagged.
  ratios and any statistic that combines several groups of runs: percentile bootstrap over runs,
                     runs resampled with replacement within each group, 10,000 resamples, seed
                     20260929 combined with crc32(id) (numpy default_rng).
  min, max           range of the per-run values; for multi-group statistics the range over all
                     combinations of one run per group.
  constants (calibration, thesis values, counts) have no CI.

Outputs
  analysis/out/paper/numbers.csv       id, description, value, unit, ci_low, ci_high, min, max, n_runs,
                                       method, source_files
  analysis/out/paper/numbers_meta.csv  id, section, used_in, decimals, flag
  (NUMBERS.md, the LaTeX tables and the figures are written from these files by paper_numbers_md.py,
  paper_tables.py and paper_figures.py.)

Usage: venv/bin/python analysis/scripts/paper_stats.py [--boot 10000] [--seed 20260929]
"""

import argparse
import csv
import glob
import itertools
import json
import math
import os
import statistics
import sys
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "analysis", "scripts"))
import final_mw  # noqa: E402  cycle estimator
import final_real  # noqa: E402  real-run discovery, thesis c = 1 streams, permutation test
import validate_real_v2 as vr  # noqa: E402  prefixes and thesis Locust values

OUT = os.path.join(ROOT, "analysis", "out", "paper")
AOUT = os.path.join(ROOT, "analysis", "out")
CAL = json.load(open(os.path.join(ROOT, "simulated_endpoint", "calibration_v2.json")))["values"]
S = {k: float(v) for k, v in CAL["service_time_s"].items()}
EPS = ["inference", "stream", "pipeline"]
EA = {"inference": "inf", "stream": "str", "pipeline": "pip"}
CFGS = ["flask", "django", "flask_mw", "django_mw", "fastapi", "tornado"]
CA = {"flask": "flask", "django": "django", "flask_mw": "flask17w", "django_mw": "django17w",
      "fastapi": "fastapi", "tornado": "tornado"}
LABEL = {"flask": "Flask", "django": "Django", "flask_mw": "Flask 17w", "django_mw": "Django 17w",
         "fastapi": "FastAPI", "tornado": "Tornado"}
SYNC1, MW, ASYNC = ("flask", "django"), ("flask_mw", "django_mw"), ("fastapi", "tornado")
CS = [1, 5, 10, 25, 50, 100]
W = 17
N_SIM, N_NEW = 12, 92  # chunks per stream: simulator calibration, real API today (final_stream_cpu.py)
CMD = "venv/bin/python analysis/scripts/paper_stats.py"

SRC_PR = "results_v2/per_run_v2.csv (scripts/aggregate_v2.py)"
SRC_CYC = "data_v2/{cfg}/{ep}/c{c}_run{{1..5}}_requests.csv and _locust_meta.json (cycle estimator, final_mw.py)"
SRC_SS = "data_v2/{cfg}/{ep}/c{c}_run{{1..5}}_requests.csv and _locust_meta.json (rule A, final_steady_state.py)"
SRC_REAL = "data_v2_real/fastapi/{ep}/c{{1,25}}_run{{1..3}}_requests.csv, _stream_metrics.csv, _locust_meta.json"
SRC_SIMFA = "data_v2/fastapi/{ep}/c{{1,25}}_run{{1..5}}_requests.csv, _stream_metrics.csv, _locust_meta.json"
SRC_THESIS_INF = "data/fastapi/inference/c1_run{1..5}_stats.csv (Locust Aggregated median and 95 %)"
SRC_THESIS_STR = "data/{fw}/stream/c1_run{{1..5}}_stream_metrics.csv"
SRC_PC = "data_v2_real/phase_c/{fw}/stream/c1_run{{1..3}}_stream_metrics.csv"
SRC_RPR = "analysis/out/final_real_per_run.csv (analysis/scripts/final_real.py)"
SRC_THESIS_PDF = "~/paper_context/thesis.pdf printed p. {p} (RESULTS_FINAL section 8; check: python3 analysis/scripts/final_thesis_text.py \"{q}\")"


# ---------------------------------------------------------------- t quantiles (closed forms, no scipy)
def t975(df):
    p = 0.975
    if df == 2:
        return (2 * p - 1) / math.sqrt(2 * p * (1 - p))
    if df == 4:
        a = 4 * p * (1 - p)
        q = math.cos(math.acos(math.sqrt(a)) / 3) / math.sqrt(a)
        return 2 * math.sqrt(q - 1)
    raise ValueError(f"no t quantile for df = {df}")


T = {2: t975(2), 4: t975(4)}
assert abs(T[2] - 4.302653) < 1e-6 and abs(T[4] - 2.776445) < 1e-6, T


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x):
    return None if x in (None, "", "None", "N/A") else float(x)


def fmt(x, nd):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:,.{nd}f}"


# ---------------------------------------------------------------- registry
class Reg:
    def __init__(self, boot, seed):
        self.B, self.seed = boot, seed
        self.rows, self.by, self.checks = [], {}, []

    def _put(self, row, meta):
        assert row["id"] not in self.by, row["id"]
        row.update(meta)
        self.rows.append(row)
        self.by[row["id"]] = row
        return row

    def add(self, nid, desc, unit, groups, stat, *, section, used_in, src, nd, value_rule, ci="auto",
            check=None, note="", value=None, wide=True, seed_id=None):
        """groups: list of lists of run-level items; stat(groups) -> float."""
        v = stat(groups) if value is None else value
        sizes = [len(g) for g in groups]
        mn = mx = None
        if math.prod(sizes) <= 5000:
            cv = [stat([[x] for x in combo]) for combo in itertools.product(*groups)]
            cv = [x for x in cv if x is not None and math.isfinite(x)]
            if cv:
                mn, mx = min(cv), max(cv)
        kind = ci if ci != "auto" else ("t" if len(groups) == 1 else "boot")
        lo = hi = None
        if kind == "t":
            per = [stat([[x]]) for x in groups[0]]
            n = len(per)
            m, sd = statistics.mean(per), statistics.stdev(per)
            h = T[n - 1] * sd / math.sqrt(n)
            lo, hi = m - h, m + h
            cim = (f"95 % CI: mean of the {n} per-run values +/- t(0.975, {n - 1}) = {T[n - 1]:.4f} x SD / "
                   f"sqrt({n})")
        elif kind == "boot":
            rng = np.random.default_rng([self.seed, zlib.crc32((seed_id or nid).encode())])
            idx = [rng.integers(0, n, size=(self.B, n)) for n in sizes]
            reps = []
            for b in range(self.B):
                r = stat([[g[i] for i in ix[b]] for g, ix in zip(groups, idx)])
                if r is not None and math.isfinite(r):
                    reps.append(r)
            lo, hi = (float(x) for x in np.percentile(reps, [2.5, 97.5]))
            cim = (f"95 % CI: percentile bootstrap over runs, {self.B:,} resamples, runs resampled with "
                   f"replacement within each of {len(groups)} group(s) of {'/'.join(map(str, sizes))} runs, "
                   f"seed {self.seed} + crc32({seed_id or 'id'})" + (f", {self.B - len(reps)} undefined resamples dropped"
                                                        if len(reps) < self.B else ""))
        else:
            cim = f"no CI ({kind})"
        mm = "min/max: per-run values" if len(groups) == 1 else \
            "min/max: over all combinations of one run per group"
        row = dict(id=nid, description=desc, value=v, unit=unit, ci_low=lo, ci_high=hi, min=mn, max=mx,
                   n_runs="+".join(map(str, sizes)), method=f"{value_rule}; {cim}; {mm}", source_files=src)
        flags = []
        if wide and lo is not None and v not in (0, None):
            rel = (hi - lo) / 2 / abs(v)
            if rel > 0.10:
                flags.append(f"wide CI: half-width {rel * 100:.0f} % of the value")
        if kind == "t" and lo is not None and max(lo - v, v - hi) > 0.005 * abs(v):
            flags.append("value (median or pooled statistic) lies more than 0.5 % outside the t-interval of the "
                         "per-run mean")
        if check is not None and lo is not None:
            c = check(v, lo, hi)
            if c:
                flags.append(c)
        if note:
            flags.append(note)
        return self._put(row, dict(section=section, used_in=used_in, decimals=nd, flag="; ".join(flags)))

    def const(self, nid, desc, unit, value, *, section, used_in, src, nd, why, note="", n_runs="n/a",
              mn=None, mx=None):
        row = dict(id=nid, description=desc, value=value, unit=unit, ci_low=None, ci_high=None, min=mn, max=mx,
                   n_runs=n_runs, method=f"no CI: {why}", source_files=src)
        return self._put(row, dict(section=section, used_in=used_in, decimals=nd, flag=note))

    def rng_(self, nid, desc, unit, ids, *, section, used_in, nd, note="", check=None):
        rs = [self.by[i] for i in ids]
        vals = [r["value"] for r in rs]
        los = [r["ci_low"] for r in rs if r["ci_low"] is not None]
        his = [r["ci_high"] for r in rs if r["ci_high"] is not None]
        mns = [r["min"] for r in rs if r["min"] is not None]
        mxs = [r["max"] for r in rs if r["max"] is not None]
        srcs = list(dict.fromkeys(r["source_files"] for r in rs))
        lo, hi = (min(los) if los else None), (max(his) if his else None)
        vmin, vmax = min(vals), max(vals)
        flags = []
        if check is not None and lo is not None:
            c = check((vmin, vmax), lo, hi)
            if c:
                flags.append(c)
        if note:
            flags.append(note)
        row = dict(id=nid, description=desc, value=f"{fmt(vmin, nd)} to {fmt(vmax, nd)}".replace(",", ""),
                   unit=unit, ci_low=lo, ci_high=hi, min=min(mns) if mns else None, max=max(mxs) if mxs else None,
                   n_runs=";".join(sorted({r["n_runs"] for r in rs})),
                   method=f"range over {len(ids)} numbers ({compact(ids)}); CI: envelope (lowest lower and highest "
                          f"upper bound) of their 95 % CIs; min/max: envelope of their run ranges",
                   source_files=" | ".join(srcs[:3]) + (" | ..." if len(srcs) > 3 else ""))
        return self._put(row, dict(section=section, used_in=used_in, decimals=nd, flag="; ".join(flags),
                                   _vmin=vmin, _vmax=vmax))

    def expect(self, nid, ref, tol=1e-6, what=""):
        v = self.by[nid]["value"]
        ok = abs(v - ref) <= tol * max(1.0, abs(ref))
        self.checks.append((nid, v, ref, ok, what))


def compact(ids):
    return ", ".join(ids) if len(ids) <= 4 else f"{ids[0]}, {ids[1]}, ..., {ids[-1]}"


def med0(g):
    return statistics.median(g[0])


def pooled(fn):
    return lambda g: float(fn(np.concatenate(g[0])))


def p95(a):
    return np.percentile(a, 95)


def p50(a):
    return np.percentile(a, 50)


# ---------------------------------------------------------------- data
def load_main():
    pr = {}
    for r in read(os.path.join(ROOT, "results_v2", "per_run_v2.csv")):
        pr.setdefault((r["framework"], r["endpoint"], int(r["concurrency"])), []).append(r)
    for k in pr:
        pr[k].sort(key=lambda r: int(r["run"]))
    return pr


def prefix(cfg, ep, c, run):
    return os.path.join(ROOT, "data_v2", cfg, ep, f"c{c}_run{run}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20260929)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    reg = Reg(a.boot, a.seed)
    PR = load_main()

    def col(cfg, ep, c, key):
        return [fnum(r[key]) for r in PR[(cfg, ep, c)]]

    cyc = {}

    def xs(cfg, ep, c):
        if cfg in MW and c > W:
            if (cfg, ep, c) not in cyc:
                cyc[(cfg, ep, c)] = [final_mw.cycle_rate(prefix(cfg, ep, c, r["run"]), S[ep])[0] for r in PR[(cfg, ep, c)]]
            return cyc[(cfg, ep, c)]
        return col(cfg, ep, c, "throughput_completion_rate")

    def ceil_(cfg, ep, c):
        return (min(c, W) if cfg in MW else 1 if cfg in SYNC1 else c) / S[ep]

    def src_x(cfg, ep, c):
        return SRC_CYC.format(cfg=cfg, ep=ep, c=c) if (cfg in MW and c > W) else SRC_PR

    mwcsv = {(r["config"], r["endpoint"], int(r["concurrency"])): r for r in read(os.path.join(AOUT, "final_mw.csv"))}

    # ============================================================ T2 cells: throughput and share
    for ep in EPS:
        for cfg in CFGS:
            for c in CS:
                x = xs(cfg, ep, c)
                est = "cycle estimator" if (cfg in MW and c > W) else "completion rate"
                cl = ceil_(cfg, ep, c)
                cl_txt = "17/S" if (cfg in MW and c > W) else ("c/S" if cfg in ASYNC or cfg in MW else "1/S")
                if c == 1:
                    cl_txt = "1/S"
                base = f"{EA[ep]}.{CA[cfg]}.c{c}"
                reg.add(f"X.{base}", f"throughput ({est}), {LABEL[cfg]}, {ep}, c = {c}", "req/s", [x], med0,
                        section="T2", used_in="T2; F1", src=src_x(cfg, ep, c), nd=4,
                        value_rule="value: median of the 5 per-run values")
                reg.add(f"SH.{base}", f"share of the ceiling {cl_txt} = {cl:.4f} req/s, {LABEL[cfg]}, {ep}, c = {c}",
                        "fraction", [[v / cl for v in x]], med0, section="T2", used_in="T2; F1",
                        src=src_x(cfg, ep, c), nd=4, value_rule=f"value: median of the 5 per-run X / ({cl_txt})")
                reg.expect(f"X.{base}", float(mwcsv[(cfg, ep, c)]["x_best"]), what="final_mw.csv x_best")

    # ============================================================ T3 cells: latency
    ss = {(r["config"], r["endpoint"], int(r["concurrency"])): r
          for r in read(os.path.join(AOUT, "final_steady_state.csv"))}
    steady_items = {}

    def steady_runs(cfg, ep, c):
        w = W if cfg in MW else 1
        cut = math.ceil(c / w) * S[ep]
        out = []
        for r in PR[(cfg, ep, c)]:
            p = prefix(cfg, ep, c, r["run"])
            t0 = json.load(open(p + "_locust_meta.json"))["first_user_start_mono"]
            rows = read(p + "_requests.csv")
            out.append(np.array([float(x["response_time_ms"]) for x in rows
                                 if x["success"] == "True" and float(x["start_mono"]) >= t0 + cut]))
        return out

    for ep in EPS:
        for cfg in CFGS:
            for c in CS:
                base = f"{EA[ep]}.{CA[cfg]}.c{c}"
                cens = cfg in SYNC1 and c >= 25
                steady = (cfg in SYNC1 and c in (5, 10)) or (cfg in MW and c > W)
                if cens:
                    reg.add(f"LR.{base}", f"R = N/X = c / X (latency percentiles censored), {LABEL[cfg]}, {ep}, c = {c}",
                            "ms", [col(cfg, ep, c, "response_law_R_ms")], med0, section="T3", used_in="T3; F2",
                            src=SRC_PR, nd=0, value_rule="value: median of the 5 per-run c / X (completion rate)")
                    continue
                if steady:
                    k = steady_runs(cfg, ep, c)
                    steady_items[(cfg, ep, c)] = k
                    for nm, fn, lab in (("LM", np.mean, "steady-state mean"), ("L50", p50, "steady-state p50"),
                                        ("L95", p95, "steady-state p95")):
                        reg.add(f"{nm}.{base}", f"{lab} latency (rule A), {LABEL[cfg]}, {ep}, c = {c}", "ms", [k],
                                pooled(fn), section="T3", used_in="T3; F2" if nm == "LM" else "T3",
                                src=SRC_SS.format(cfg=cfg, ep=ep, c=c), nd=0,
                                value_rule=f"value: {lab.split()[-1]} pooled over the 5 runs' requests kept by rule A "
                                           f"(start >= t0 + ceil(c / w) S)")
                    reg.expect(f"LM.{base}", float(ss[(cfg, ep, c)]["A_mean"]), what="final_steady_state.csv A_mean")
                    continue
                for nm, key, lab in (("LM", "latency_mean_ms", "mean"), ("L50", "latency_p50_ms", "p50"),
                                     ("L95", "latency_p95_ms", "p95")):
                    reg.add(f"{nm}.{base}", f"{lab} latency (all requests; no queue), {LABEL[cfg]}, {ep}, c = {c}", "ms",
                            [col(cfg, ep, c, key)], med0, section="T3",
                            used_in="T3; F2" if nm == "LM" else "T3", src=SRC_PR, nd=0,
                            value_rule="value: median of the 5 per-run values")

    # ============================================================ resources, all cells (T4 at c = 100; F3, F6)
    for ep in EPS:
        for cfg in CFGS:
            for c in CS:
                base = f"{EA[ep]}.{CA[cfg]}.c{c}"
                t4 = "T4; " if c == 100 else ""
                for nm, key, lab, unit, nd, use in (
                        ("CPU", "cpu_mean_loaded_pct", "server CPU, mean over [t0, stop]", "% of one core", 2,
                         "T4; 5.3 text" if c == 100 else "5.3 text (range)"),
                        ("CPUMS", "cpu_ms_per_request", "server CPU per completed request", "ms", 1, t4 + "F6"),
                        ("USSI", "idle_uss_mb", "idle USS (post-warm-up)", "MiB", 1,
                         "T4" if c == 100 else ("5.3 text" if (ep, c) == ("inference", 1) else "5.3 text (range)")),
                        ("USSP", "peak_uss_mb", "peak USS", "MiB", 1, t4 + "F3")):
                    reg.add(f"{nm}.{base}", f"{lab}, {LABEL[cfg]}, {ep}, c = {c}", unit, [col(cfg, ep, c, key)], med0,
                            section="T4" if c == 100 else "figure data", used_in=use, src=SRC_PR, nd=nd,
                            value_rule="value: median of the 5 per-run values")
        for nm, key, lab in (("RSSP", "peak_rss_mb", "peak RSS"), ("USSG", "uss_growth_mb", "USS growth (peak - idle)")):
            for cfg in CFGS:
                reg.add(f"{nm}.{EA[ep]}.{CA[cfg]}.c100", f"{lab}, {LABEL[cfg]}, {ep}, c = 100", "MiB",
                        [col(cfg, ep, 100, key)], med0, section="5.3 Resources", used_in="5.3 text; T6", src=SRC_PR,
                        nd=2, value_rule="value: median of the 5 per-run values")

    # stream detail and pipeline Stage 2
    for cfg in CFGS:
        for c in CS:
            base = f"str.{CA[cfg]}.c{c}"
            cens = cfg in SYNC1 and c >= 25
            reg.add(f"TTFT.{base}", f"stream TTFT p50{' (censored by the 60 s window)' if cens else ''}, "
                                    f"{LABEL[cfg]}, c = {c}", "ms", [col(cfg, "stream", c, "ttft_p50_ms")], med0,
                    section="5.2 Latency", used_in="5.2 text; T6" if c in (1, 100) else "numbers.csv only", src=SRC_PR, nd=1,
                    value_rule="value: median of the 5 per-run TTFT p50",
                    note="censored: reflects the 60 s window, not the steady state" if cens else "")
            reg.add(f"TPOT.{base}", f"stream TPOT p50, {LABEL[cfg]}, c = {c}", "ms per chunk",
                    [col(cfg, "stream", c, "tpot_p50_ms")], med0, section="5.2 Latency",
                    used_in="5.2 text" if c in (1, 100) else "numbers.csv only", src=SRC_PR, nd=2,
                    value_rule="value: median of the 5 per-run TPOT p50")
            reg.add(f"ST2.{CA[cfg]}.c{c}", f"pipeline Stage 2 (0.05 s retrieval sleep) p50, {LABEL[cfg]}, c = {c}", "ms",
                    [col(cfg, "pipeline", c, "stage2_p50_ms")], med0, section="7 Pitfalls",
                    used_in="7 text; T6; F5" if c == 100 else "numbers.csv only", src=SRC_PR, nd=2,
                    value_rule="value: median of the 5 per-run Stage 2 p50")
        for key, nm in (("derived_ttft_ms", "TTFTD"), ("ttft_p95_ms", "TTFT95")):
            reg.add(f"{nm}.str.{CA[cfg]}.c100", f"stream {'derived steady-state TTFT' if nm == 'TTFTD' else 'TTFT p95'}, "
                                                 f"{LABEL[cfg]}, c = 100", "ms", [col(cfg, "stream", 100, key)], med0,
                    section="5.2 Latency", used_in="5.2 text; T6", src=SRC_PR, nd=0,
                    value_rule="value: median of the 5 per-run values" + (
                        " (derived TTFT = (R - service) + the framework's median c = 1 TTFT p50)" if nm == "TTFTD" else ""))
        if cfg in ASYNC:  # p99 needs >= 100 completions per run (one-worker sync: 21)
            reg.add(f"ST2P99.{CA[cfg]}.c100", f"pipeline Stage 2 p99, {LABEL[cfg]}, c = 100", "ms",
                    [col(cfg, "pipeline", 100, "stage2_p99_ms")], med0, section="7 Pitfalls", used_in="7 text",
                    src=SRC_PR, nd=2, value_rule="value: median of the 5 per-run values")

    # ============================================================ 4 Methodology constants
    sec = "4 Methodology"
    for ep in EPS:
        reg.const(f"M.S.{EA[ep]}", f"calibrated service time S, {ep}", "s", S[ep], section=sec, used_in="4 text; T1",
                  src="simulated_endpoint/calibration_v2.json values.service_time_s", nd=4, why="calibration constant")
        reg.const(f"M.invS.{EA[ep]}", f"ceiling 1/S, {ep}", "req/s", 1 / S[ep], section=sec, used_in="5.1 text; F1",
                  src="simulated_endpoint/calibration_v2.json", nd=4, why="1 / calibrated S")
        reg.const(f"M.17S.{EA[ep]}", f"ceiling 17/S, {ep}", "req/s", W / S[ep], section=sec, used_in="5.5 text; F1",
                  src="simulated_endpoint/calibration_v2.json", nd=3, why="17 / calibrated S")
    reg.const("M.first_chunk", "simulator first-chunk delay", "ms", CAL["stream_first_chunk_delay_s"] * 1000, section=sec,
              used_in="4 text; T1", src="simulated_endpoint/calibration_v2.json", nd=1, why="calibration constant")
    reg.const("M.chunk_gap", "simulator chunk interval", "ms", CAL["stream_chunk_interval_s"] * 1000, section=sec,
              used_in="4 text; T1; 8", src="simulated_endpoint/calibration_v2.json", nd=1, why="calibration constant")
    reg.const("M.chunks", "simulator chunks per stream", "chunks", CAL["stream_chunk_count"], section=sec,
              used_in="4 text; T1; 8", src="simulated_endpoint/calibration_v2.json", nd=0, why="calibration constant")
    reg.const("M.retrieval", "pipeline Stage 2 retrieval sleep", "ms", CAL["retrieval_delay_s"] * 1000, section=sec,
              used_in="4 text; T1; 7", src="simulated_endpoint/calibration_v2.json", nd=0, why="calibration constant")
    allpr = [r for v in PR.values() for r in v]
    rpr = read(os.path.join(AOUT, "final_real_per_run.csv"))
    reg.const("M.runs_sim", "simulated runs (main matrix 360 + 17-worker arm 180), all complete", "runs", len(allpr),
              section=sec, used_in="4 text; T1", src=SRC_PR, nd=0, why="count")
    reg.const("M.runs_real", "real-API runs (Phase A 6, B 6, C 12), all complete", "runs", len(rpr), section=sec,
              used_in="4 text; 6; T1", src=SRC_RPR, nd=0, why="count")
    reg.const("M.err", "largest error rate over the 540 simulated runs", "%",
              max(float(r["error_rate_pct"]) for r in allpr), section=sec, used_in="4 text; 5.1",
              src=SRC_PR, nd=1, why="maximum over runs")
    reg.const("M.err_real", "failed real-API requests over 24 runs", "requests",
              sum(int(r["failures"]) for r in rpr), section=sec, used_in="6 text", src=SRC_RPR, nd=0, why="count")
    rates = [float(r["clock_rate_ratio"]) for r in allpr] + [float(r["clock_rate_ratio"]) for r in rpr]
    steps = [float(r["clock_step_ms"]) for r in allpr] + [float(r["clock_step_ms"]) for r in rpr]
    reg.const("M.clock_min", "guest monotonic / host clock rate, minimum over 564 runs", "ratio", min(rates), section=sec,
              used_in="4 text; 9", src=SRC_PR + "; " + SRC_RPR, nd=6, why="minimum over runs")
    reg.const("M.clock_max", "guest monotonic / host clock rate, maximum over 564 runs", "ratio", max(rates), section=sec,
              used_in="4 text; 9", src=SRC_PR + "; " + SRC_RPR, nd=6, why="maximum over runs")
    reg.const("M.clock_step", "largest clock step over 564 runs", "ms", max(steps), section=sec, used_in="4 text; 9",
              src=SRC_PR + "; " + SRC_RPR, nd=3, why="maximum over runs")
    mon = [float(r["monitor_cpu_pct"]) for r in allpr if r["framework"] in MW]
    reg.const("M.mon17", "monitor CPU in the 17-worker arm, range over 180 runs", "% of one core",
              f"{min(mon):.2f} to {max(mon):.2f}", section="9 Threats", used_in="9 text", src=SRC_PR, nd=2,
              why="range over runs")
    idl = sum(1 for r in allpr if r["framework"] in MW and r["idle_drift"] == "True")
    reg.const("M.idle_drift", "17-worker runs flagged idle_drift (> 2 MB idle-memory difference)", "runs", idl,
              section="9 Threats", used_in="9 text", src=SRC_PR, nd=0, why="count")
    reg.const("M.cpu_step", "CPU sample quantisation step (10 ms jiffy / 250 ms sample)", "% of one core", 4.0,
              section="9 Threats", used_in="9 text", src="monitoring/resource_monitor_v2.py (PAPER_CONTEXT 21.4)", nd=0,
              why="arithmetic constant")

    # ============================================================ 5.1 capacity: ratios
    sec = "5.1 Capacity"

    def ratio_groups(num, den, ep, c, key=None):
        f = (lambda cfg: xs(cfg, ep, c)) if key is None else (lambda cfg: col(cfg, ep, c, key))
        return [f(x) for x in num] + [f(x) for x in den]

    def mean_ratio(nn):
        return lambda g: statistics.mean(statistics.median(x) for x in g[:nn]) / statistics.mean(
            statistics.median(x) for x in g[nn:])

    mwr = {(r["endpoint"], int(r["concurrency"])): r for r in read(os.path.join(AOUT, "final_mw_ratio.csv"))}
    for ep in EPS:
        for c in CS:
            use100 = c == 100
            reg.add(f"RA1.{EA[ep]}.c{c}", f"throughput ratio async / one-worker sync, {ep}, c = {c} "
                                          f"(mean(FastAPI, Tornado) / mean(Flask, Django), completion rate)", "x",
                    ratio_groups(ASYNC, SYNC1, ep, c, "throughput_completion_rate"), mean_ratio(2), section=sec,
                    used_in="Abstract; 1; 5.1 text; T6; F5" if use100 else "5.1 text (range)", src=SRC_PR, nd=2,
                    value_rule="value: ratio of the means over frameworks of the per-configuration medians")
            reg.expect(f"RA1.{EA[ep]}.c{c}", float(mwr[(ep, c)]["async_over_single_rate"]), what="final_mw_ratio")
            reg.add(f"RA17.{EA[ep]}.c{c}", f"throughput ratio async / 17-worker sync, {ep}, c = {c} "
                                           f"(17 workers: cycle estimator for c > 17)", "x",
                    ratio_groups(ASYNC, MW, ep, c), mean_ratio(2), section=sec,
                    used_in="Abstract; 1; 5.1 text; 5.5" if use100 else "5.5 text (range)",
                    src=SRC_PR + "; " + SRC_CYC.format(cfg="{flask_mw,django_mw}", ep=ep, c=c), nd=3,
                    value_rule="value: ratio of the means over frameworks of the per-configuration medians",
                    check=lambda v, lo, hi, t=c / min(c, W): (f"CI [{lo:.3f}, {hi:.3f}] reaches more than 1 % away "
                                                              f"from the theory c / min(c, 17) = {t:.3f}"
                                                              if (lo < 0.99 * t or hi > 1.01 * t) else None))
            reg.expect(f"RA17.{EA[ep]}.c{c}", float(mwr[(ep, c)]["ratio_best"]), what="final_mw_ratio")
            reg.add(f"R171.{EA[ep]}.c{c}", f"throughput ratio 17-worker / one-worker sync, {ep}, c = {c}", "x",
                    ratio_groups(MW, SYNC1, ep, c), mean_ratio(2), section="5.5 Multi-worker",
                    used_in="5.5 text" if use100 else "numbers.csv only",
                    src=SRC_PR + "; " + SRC_CYC.format(cfg="{flask_mw,django_mw}", ep=ep, c=c), nd=3,
                    value_rule="value: ratio of the means over frameworks of the per-configuration medians")
        reg.add(f"RA1F.{EA[ep]}.c100", f"throughput ratio async / one-worker sync, fixed-window estimator, {ep}, c = 100",
                "x", ratio_groups(ASYNC, SYNC1, ep, 100, "throughput_fixed_window"), mean_ratio(2), section="7 Pitfalls",
                used_in="7 text; T6", src=SRC_PR, nd=2,
                value_rule="value: ratio of the means over frameworks of the per-configuration medians")
    reg.rng_("N.RA1.c100", "async / one-worker sync throughput at c = 100, over the three endpoints", "x",
             [f"RA1.{EA[e]}.c100" for e in EPS], section=sec, used_in="Abstract; 1; 5.1 text", nd=2)
    reg.rng_("N.RA17.c100", "async / 17-worker sync throughput at c = 100, over the three endpoints (theory 5.882)", "x",
             [f"RA17.{EA[e]}.c100" for e in EPS], section=sec, used_in="Abstract; 1; 5.1 text; 5.5", nd=3)
    reg.rng_("N.RA17.le10", "async / 17-worker sync throughput at c <= 10 (theory 1)", "x",
             [f"RA17.{EA[e]}.c{c}" for e in EPS for c in (1, 5, 10)], section="5.5 Multi-worker", used_in="5.5 text", nd=3)
    reg.rng_("N.SH1", "one-worker sync (Flask, Django) share of 1/S, all endpoints and c", "fraction",
             [f"SH.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in SYNC1 for c in CS], section=sec,
             used_in="5.1 text", nd=3)
    reg.rng_("N.X1.inf", "one-worker sync throughput, inference, all c", "req/s",
             [f"X.inf.{CA[f]}.c{c}" for f in SYNC1 for c in CS], section=sec, used_in="Abstract; 5.1 text", nd=3)
    reg.rng_("N.SHA", "async (FastAPI, Tornado) share of c/S, all endpoints and c", "fraction",
             [f"SH.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in ASYNC for c in CS], section=sec,
             used_in="5.1 text", nd=3)
    for ep in EPS:
        reg.rng_(f"N.XA100.{EA[ep]}", f"async throughput at c = 100, {ep} (FastAPI, Tornado)", "req/s",
                 [f"X.{EA[ep]}.{CA[f]}.c100" for f in ASYNC], section=sec, used_in="5.1 text", nd=2)
    reg.rng_("N.SH17", "17-worker share of 17/S (cycle estimator), c = 25 to 100, all endpoints", "fraction",
             [f"SH.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in MW for c in (25, 50, 100)], section="5.5 Multi-worker",
             used_in="5.5 text", nd=4)
    reg.rng_("N.SH17le10", "17-worker share of c/S, c = 1 to 10, all endpoints", "fraction",
             [f"SH.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in MW for c in (1, 5, 10)], section="5.5 Multi-worker",
             used_in="5.5 text", nd=4)
    reg.rng_("N.R171.c100", "17-worker / one-worker sync throughput at c = 100 (theory 17)", "x",
             [f"R171.{EA[e]}.c100" for e in EPS], section="5.5 Multi-worker", used_in="5.5 text", nd=3)

    # biased estimators (pitfalls)
    for ep in EPS:
        for cfg in MW:
            for c in (25, 50, 100):
                cl = W / S[ep]
                reg.add(f"SHR.{EA[ep]}.{CA[cfg]}.c{c}", f"17-worker share of 17/S with the completion-rate estimator "
                                                        f"(biased by phase-locked clusters), {ep}, c = {c}", "fraction",
                        [[v / cl for v in col(cfg, ep, c, "throughput_completion_rate")]], med0, section="7 Pitfalls",
                        used_in="numbers.csv only", src=SRC_PR, nd=4, value_rule="value: median of the 5 per-run values")
        for cfg in SYNC1:
            for c in CS:
                reg.add(f"SHF.{EA[ep]}.{CA[cfg]}.c{c}", f"one-worker share of 1/S with the fixed-window estimator "
                                                        f"(lattice effect), {LABEL[cfg]}, {ep}, c = {c}", "fraction",
                        [col(cfg, ep, c, "share_of_ceiling")], med0, section="7 Pitfalls", used_in="numbers.csv only",
                        src=SRC_PR, nd=4, value_rule="value: median of the 5 per-run values")
    reg.rng_("N.SHR17", "17-worker completion-rate share of 17/S at c = 25 to 100 (biased estimator)", "fraction",
             [f"SHR.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in MW for c in (25, 50, 100)], section="7 Pitfalls",
             used_in="7 text; 5.5 text", nd=3)
    reg.rng_("N.SHF1", "one-worker fixed-window share of 1/S (biased estimator)", "fraction",
             [f"SHF.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in SYNC1 for c in CS], section="7 Pitfalls",
             used_in="7 text", nd=3)

    # ============================================================ 5.2 latency
    sec = "5.2 Latency"
    for (cfg, ep, c), k in steady_items.items():
        base = f"{EA[ep]}.{CA[cfg]}.c{c}"
        if cfg in MW:
            x = xs(cfg, ep, c)
            reg.add(f"LR.{base}", f"R = N/X = c / X_cycle, {LABEL[cfg]}, {ep}, c = {c}", "ms", [[c / v * 1000 for v in x]],
                    med0, section=sec, used_in="T3; F2; 5.5 text", src=SRC_CYC.format(cfg=cfg, ep=ep, c=c), nd=0,
                    value_rule="value: median of the 5 per-run c / X_cycle (= c / median X_cycle)")
            reg.expect(f"LR.{base}", float(mwcsv[(cfg, ep, c)]["R_best_ms"]), what="final_mw R_best_ms")
        else:
            x = col(cfg, ep, c, "throughput_completion_rate")
            reg.add(f"LR.{base}", f"R = N/X = c / X, {LABEL[cfg]}, {ep}, c = {c}", "ms",
                    [col(cfg, ep, c, "response_law_R_ms")], med0, section=sec, used_in="T3; F2", src=SRC_PR, nd=0,
                    value_rule="value: median of the 5 per-run c / X (completion rate)")
        items = [(kk, xx, fm) for kk, xx, fm in zip(k, x, col(cfg, ep, c, "latency_mean_ms"))]

        def mr(g, c=c):
            return float(np.mean(np.concatenate([i[0] for i in g[0]]))) / (
                c / statistics.median(i[1] for i in g[0]) * 1000)

        def us(g):
            return (1 - statistics.median(i[2] for i in g[0]) / float(np.mean(np.concatenate([i[0] for i in g[0]])))) * 100

        reg.add(f"SSR.{base}", f"steady-state mean / R, {LABEL[cfg]}, {ep}, c = {c}", "ratio", [items], mr, section=sec,
                used_in="5.2 text (range)", src=SRC_SS.format(cfg=cfg, ep=ep, c=c) + "; " + SRC_PR, nd=4, ci="boot",
                value_rule="value: pooled rule-A mean / (c / median X)")
        reg.expect(f"SSR.{base}", float(ss[(cfg, ep, c)]["A_mean_over_R"]), tol=1e-9, what="final_steady_state A_mean_over_R")
        reg.add(f"SSU.{base}", f"full-window mean understates the steady-state mean by, {LABEL[cfg]}, {ep}, c = {c}", "%",
                [items], us, section=sec, used_in="5.2 text; 7 (range)", src=SRC_SS.format(cfg=cfg, ep=ep, c=c) + "; " + SRC_PR,
                nd=1, ci="boot",
                value_rule="value: (1 - median of the per-run all-request means / pooled rule-A mean) x 100")
        reg.expect(f"SSU.{base}", float(ss[(cfg, ep, c)]["full_mean_understates_A_pct"]), tol=1e-6, what="final_steady_state")
    reg.rng_("N.SSR1", "one worker (c = 5, 10): steady-state mean / R", "ratio",
             [f"SSR.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in SYNC1 for c in (5, 10)], section=sec,
             used_in="5.2 text", nd=4)
    reg.rng_("N.SSR17", "17 workers (c = 25 to 100): steady-state mean / R", "ratio",
             [f"SSR.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in MW for c in (25, 50, 100)], section=sec,
             used_in="5.2 text; 5.5", nd=4)
    for cfgs, cc, nid, lab in ((SYNC1, (5,), "N.SSU1.c5", "one worker, c = 5"),
                               (SYNC1, (10,), "N.SSU1.c10", "one worker, c = 10"),
                               (MW, (25,), "N.SSU17.c25", "17 workers, c = 25"),
                               (MW, (50,), "N.SSU17.c50", "17 workers, c = 50"),
                               (MW, (100,), "N.SSU17.c100", "17 workers, c = 100")):
        reg.rng_(nid, f"full-window mean understates the steady state, {lab}, all endpoints", "%",
                 [f"SSU.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in cfgs for c in cc], section=sec,
                 used_in="5.2 text; 7 text", nd=1)
    reg.rng_("N.LR1.c100", "one-worker sync R = N/X at c = 100 (censored cells), all endpoints", "ms",
             [f"LR.{EA[e]}.{CA[f]}.c100" for e in EPS for f in SYNC1], section=sec, used_in="5.2 text; T3", nd=0)
    reg.rng_("N.LR1.c25", "one-worker sync R = N/X at c = 25 (censored cells), all endpoints", "ms",
             [f"LR.{EA[e]}.{CA[f]}.c25" for e in EPS for f in SYNC1], section=sec, used_in="5.2 text; T3", nd=0)
    reg.rng_("N.LA50.inf", "async latency p50, inference, all c", "ms",
             [f"L50.inf.{CA[f]}.c{c}" for f in ASYNC for c in CS], section=sec, used_in="5.2 text", nd=0)
    for ep in EPS:
        for cfg in ASYNC:
            reg.add(f"TAIL.{EA[ep]}.{CA[cfg]}.c100", f"simulated latency p95 / p50, {LABEL[cfg]}, {ep}, c = 100", "ratio",
                    [[(a, b) for a, b in zip(col(cfg, ep, 100, "latency_p95_ms"), col(cfg, ep, 100, "latency_p50_ms"))]],
                    lambda g: statistics.median(i[0] for i in g[0]) / statistics.median(i[1] for i in g[0]),
                    section="9 Threats", used_in="9 text (range)", src=SRC_PR, nd=4, ci="boot",
                    value_rule="value: median p95 / median p50 over the 5 runs")
    reg.rng_("N.TAILsim", "simulated async p95 / p50 at c = 100, all endpoints", "ratio",
             [f"TAIL.{EA[e]}.{CA[f]}.c100" for e in EPS for f in ASYNC], section="9 Threats", used_in="9 text", nd=4)
    for ep in EPS:
        for cfg in MW:
            k = f"{EA[ep]}.{CA[cfg]}.c100"
            x = xs(cfg, ep, 100)
            th = 100 * S[ep] / W * 1000
            reg.add(f"RTH.{k}", f"R = c / X_cycle over the theory c S / 17 = {th:,.0f} ms, {LABEL[cfg]}, {ep}, c = 100",
                    "ratio", [x], lambda g, th=th: 100 / statistics.median(g[0]) * 1000 / th, section="5.5 Multi-worker",
                    used_in="5.5 text (range)", src=SRC_CYC.format(cfg=cfg, ep=ep, c=100), nd=4, ci="boot",
                    value_rule="value: (c / median X_cycle) / (c S / 17)")
    reg.rng_("N.RTH", "17 workers: R / (c S / 17) at c = 100, all endpoints", "ratio",
             [f"RTH.{EA[e]}.{CA[f]}.c100" for e in EPS for f in MW], section="5.5 Multi-worker", used_in="5.5 text", nd=4)
    reg.rng_("N.TTFT.c1", "stream TTFT p50 at c = 1, six configurations (simulator, fixed upstream)", "ms",
             [f"TTFT.str.{CA[f]}.c1" for f in CFGS], section=sec, used_in="5.2 text; 6 (Phase C)", nd=1)
    reg.rng_("N.TTFTA.c100", "async stream TTFT p50 at c = 100", "ms",
             [f"TTFT.str.{CA[f]}.c100" for f in ASYNC], section=sec, used_in="5.2 text; T6; F5", nd=1)
    reg.rng_("N.TTFT1.c100", "one-worker sync stream TTFT p50 at c = 100 (measured, censored by the window)", "ms",
             [f"TTFT.str.{CA[f]}.c100" for f in SYNC1], section=sec, used_in="5.2 text; T6", nd=0)
    reg.rng_("N.TTFTD1.c100", "one-worker sync derived steady-state TTFT at c = 100", "ms",
             [f"TTFTD.str.{CA[f]}.c100" for f in SYNC1], section=sec, used_in="5.2 text; T6", nd=0)
    reg.rng_("N.TTFT17.c100", "17-worker stream TTFT p50 at c = 100", "ms",
             [f"TTFT.str.{CA[f]}.c100" for f in MW], section=sec, used_in="5.2 text; 5.5; T6", nd=0)
    reg.rng_("N.TPOT", "stream TPOT p50, all configurations and c", "ms per chunk",
             [f"TPOT.str.{CA[f]}.c{c}" for f in CFGS for c in CS], section=sec, used_in="5.2 text", nd=2)

    # ============================================================ 5.3 resources: ratios
    sec = "5.3 Resources"
    for ep in EPS:
        for key, nm, lab in (("peak_rss_mb", "MRSS", "peak RSS"), ("peak_uss_mb", "MUSS", "peak USS")):
            reg.add(f"{nm}.{EA[ep]}.c100", f"{lab} ratio async / one-worker sync at c = 100, {ep} "
                                           f"(mean(FastAPI, Tornado) / mean(Flask, Django))", "x",
                    ratio_groups(ASYNC, SYNC1, ep, 100, key), mean_ratio(2), section=sec,
                    used_in="Abstract; 1; 5.3 text; 7; T6; F5" if nm == "MRSS" else "5.3 text", src=SRC_PR, nd=3,
                    value_rule="value: ratio of the means over frameworks of the per-configuration medians")
    for cfg in ASYNC:
        reg.add(f"CPUSI.{CA[cfg]}.c100", f"CPU per request stream / inference at c = 100, {LABEL[cfg]}", "x",
                [col(cfg, "stream", 100, "cpu_ms_per_request"), col(cfg, "inference", 100, "cpu_ms_per_request")],
                lambda g: statistics.median(g[0]) / statistics.median(g[1]), section=sec, used_in="5.3 text; 8",
                src=SRC_PR, nd=2, value_rule="value: ratio of the per-configuration medians")
    for ep in EPS:
        for m in MW:
            for s_ in ASYNC:
                reg.add(f"M17A.{EA[ep]}.{CA[m]}.{CA[s_]}", f"peak USS {LABEL[m]} / {LABEL[s_]}, {ep}, c = 100", "x",
                        [col(m, ep, 100, "peak_uss_mb"), col(s_, ep, 100, "peak_uss_mb")],
                        lambda g: statistics.median(g[0]) / statistics.median(g[1]), section="5.5 Multi-worker",
                        used_in="5.5 text (range)", src=SRC_PR, nd=2, value_rule="value: ratio of the per-configuration medians")
    reg.rng_("N.M17A", "17-worker / async peak USS at c = 100 (all endpoints and pairs)", "x",
             [f"M17A.{EA[e]}.{CA[m]}.{CA[s_]}" for e in EPS for m in MW for s_ in ASYNC], section="5.5 Multi-worker",
             used_in="Abstract; 5.5 text; 8", nd=1)
    reg.rng_("N.MRSS", "async / one-worker sync peak RSS at c = 100, three endpoints", "x",
             [f"MRSS.{EA[e]}.c100" for e in EPS], section=sec, used_in="Abstract; 1; 5.3 text; 7", nd=2)
    reg.rng_("N.USSI1", "idle USS at inference c = 1, one-worker sync and async (four frameworks)", "MiB",
             [f"USSI.inf.{CA[f]}.c1" for f in SYNC1 + ASYNC], section=sec, used_in="5.3 text", nd=1)
    reg.rng_("N.USSG1", "one-worker sync USS growth at c = 100, all endpoints", "MiB",
             [f"USSG.{EA[e]}.{CA[f]}.c100" for e in EPS for f in SYNC1], section=sec, used_in="5.3 text", nd=2)
    reg.rng_("N.USSGA.infpip", "async USS growth at c = 100, inference and pipeline", "MiB",
             [f"USSG.{EA[e]}.{CA[f]}.c100" for e in ("inference", "pipeline") for f in ASYNC], section=sec,
             used_in="5.3 text", nd=1)
    reg.rng_("N.USSGA.str", "async USS growth at c = 100, stream", "MiB",
             [f"USSG.str.{CA[f]}.c100" for f in ASYNC], section=sec, used_in="5.3 text", nd=1)
    reg.rng_("N.CPU1", "one-worker sync CPU, all endpoints and c", "% of one core",
             [f"CPU.{EA[e]}.{CA[f]}.c{c}" for e in EPS for f in SYNC1 for c in CS], section=sec, used_in="5.3 text", nd=2)

    # ============================================================ 5.4 same-class differences
    sec = "5.4 Same-class"
    pairs = (("flask", "django", "Django relative to Flask"), ("tornado", "fastapi", "FastAPI relative to Tornado"),
             ("flask_mw", "django_mw", "Django 17w relative to Flask 17w"))
    metrics = (("X", None, "throughput"), ("L50", "latency_p50_ms", "latency p50"), ("USSI", "idle_uss_mb", "idle USS"),
               ("USSP", "peak_uss_mb", "peak USS"), ("CPU", "cpu_mean_loaded_pct", "CPU mean"),
               ("CPUMS", "cpu_ms_per_request", "CPU per request"))
    sc_ids = {}
    for base_cfg, other, lab in pairs:
        pa = f"{CA[other]}_{CA[base_cfg]}"
        for mk, key, mlab in metrics:
            for ep in EPS:
                for c in CS:
                    if mk == "L50" and ((base_cfg in SYNC1 and c >= 25) or (base_cfg in MW and c > W)):
                        continue  # censored (one worker) or rule-A cells (17 workers): see steady-state numbers
                    g = [xs(other, ep, c), xs(base_cfg, ep, c)] if key is None else \
                        [col(other, ep, c, key), col(base_cfg, ep, c, key)]
                    nid = f"SC.{mk}.{pa}.{EA[ep]}.c{c}"
                    tiny = mk in ("X", "L50")
                    reg.add(nid, f"{mlab}, {lab}, {ep}, c = {c}", "%", g,
                            lambda g: (statistics.median(g[0]) / statistics.median(g[1]) - 1) * 100, section=sec,
                            used_in="5.4 text (range)", src=SRC_PR if not (key is None and base_cfg in MW and c > W)
                            else SRC_CYC.format(cfg="{flask_mw,django_mw}", ep=ep, c=c), nd=3, wide=False,
                            value_rule="value: (median of the second / median of the first configuration - 1) x 100",
                            check=None if tiny else (lambda v, lo, hi: f"CI [{lo:.1f}, {hi:.1f}] % includes 0: difference "
                                                                        f"not resolved" if lo <= 0 <= hi else None))
                    sc_ids.setdefault((pa, mk), []).append(nid)
    for (pa, mk), ids in sc_ids.items():
        excl = [i for i in ids if reg.by[i]["ci_low"] > 0 or reg.by[i]["ci_high"] < 0]
        nd = 3 if mk in ("X", "L50") else 1
        note = "" if mk in ("X", "L50") or len(excl) == len(ids) else \
            f"CI includes 0 in {len(ids) - len(excl)} of {len(ids)} cells: " + ", ".join(
                i.split(".", 3)[3] for i in ids if i not in excl)
        r = reg.rng_(f"N.SC.{mk}.{pa}", f"same-class difference {mk} ({pa.replace('_', ' vs ')}), range over "
                                        f"{len(ids)} cells; CI excludes 0 in {len(excl)} cells", "%", ids, section=sec,
                     note=note,
                     used_in="5.4 text" + ("; Abstract" if (mk, pa) in (("USSP", "django_flask"),
                                                                        ("CPU", "fastapi_tornado")) else ""), nd=nd)
        r["_excl"] = len(excl)
    # the two single cells quoted for FastAPI CPU
    for c in (1, 100):
        reg.by[f"SC.CPU.fastapi_tornado.inf.c{c}"]["used_in"] = "5.4 text"

    # ============================================================ 6 validation (real API)
    sec = "6 Validation"
    real_root, sim_root, th_root = (os.path.join(ROOT, x) for x in ("data_v2_real", "data_v2", "data"))

    def load_runs(root, ep, c, thesis=False):
        out = []
        for p in vr.complete_prefixes(root, ep, c, require_meta=not thesis):
            d = {"prefix": p}
            if not thesis:
                req = read(p + "_requests.csv")
                ok = [x for x in req if x["success"] == "True"]
                d["lat"] = np.array([float(x["response_time_ms"]) for x in ok])
                lm = json.load(open(p + "_locust_meta.json"))
                d["ends"] = np.sort(np.array([float(x["end_mono"]) for x in ok]))
                d["t0"], d["stop"] = lm["first_user_start_mono"], lm["stop_mono"]
            if ep == "stream":
                sm = [x for x in read(p + "_stream_metrics.csv") if x["success"] == "True"]
                if thesis:
                    d["lat"] = np.array([float(x["total_time_ms"]) for x in sm])
                d["ttft"] = np.array([float(x["ttft_ms"]) for x in sm if fnum(x["ttft_ms"]) is not None])
                d["tpot"] = np.array([float(x["tpot_ms"]) for x in sm if fnum(x["tpot_ms"]) is not None])
                d["chunks"] = np.array([float(x["token_count"]) for x in sm])
                d["sm_lat"] = np.array([float(x["total_time_ms"]) for x in sm])
            if thesis and ep == "inference":
                agg = [r for r in read(p + "_stats.csv") if r["Name"] == "Aggregated"][0]
                d["loc_med"], d["loc_p95"] = float(agg["Median Response Time"]), float(agg["95%"])
            out.append(d)
        return out

    def rate(d, s):
        e = d["ends"][(d["ends"] >= d["t0"] + 2 * s) & (d["ends"] <= d["stop"])]
        return (len(e) - 1) / (e[-1] - e[0]) if len(e) >= 2 and e[-1] > e[0] else None

    def pm(g, i, key="lat", fn=np.median):
        return float(fn(np.concatenate([d[key] for d in g[i]])))

    vcsv = read(os.path.join(ROOT, "results_v2", "validation_real_v2.csv"))
    tcsv = read(os.path.join(ROOT, "results_v2", "validation_real_v2_throughput.csv"))

    def vref(ph, comp, metric, col_):
        return float([r for r in vcsv if r["phase"] == ph and r["comparison"].startswith(comp) and r["metric"] == metric][0][col_])

    for ph, ep in (("A", "inference"), ("B", "stream")):
        p = ph.lower()
        r1, r25 = load_runs(real_root, ep, 1), load_runs(real_root, ep, 25)
        s1, s25 = load_runs(sim_root, ep, 1), load_runs(sim_root, ep, 25)
        th = load_runs(th_root, ep, 1, thesis=True)
        srcr = SRC_REAL.format(ep=ep)
        srcs = SRC_SIMFA.format(ep=ep)
        srct = SRC_THESIS_INF if ep == "inference" else SRC_THESIS_STR.format(fw="fastapi")
        for c, rr in ((1, r1), (25, r25)):
            for key, lab, unit, nd in (("lat", "latency", "ms", 1), ("ttft", "TTFT", "ms", 1),
                                       ("tpot", "TPOT", "ms per chunk", 2), ("chunks", "chunks per stream", "chunks", 0)):
                if key not in rr[0]:
                    continue
                for stn, fn in (("p50", np.median), ("p95", p95)):
                    reg.add(f"V{ph}.{key}.{stn}.c{c}", f"Phase {ph} real FastAPI {ep} {lab} {stn}, c = {c}", unit, [rr],
                            lambda g, key=key, fn=fn: pm(g, 0, key, fn), section=sec,
                            used_in="6 text; T5; F4" if key == "lat" else "6 text; T5", src=srcr, nd=nd,
                            value_rule=f"value: {stn} pooled over the 3 runs' requests (validate_real_v2.py)",
                            check=(lambda v, lo, hi: f"CI [{lo:,.0f}, {hi:,.0f}] ms spans {hi / lo - 1:.0%} "
                                   f"(output-mode mix between runs)" if hi / lo > 1.10 else None)
                            if (key == "lat" and stn == "p50") else None)
        reg.expect(f"V{ph}.lat.p50.c1", vref(p, "2 load", "latency_ms", "b_median"), what="validation_real_v2 S_today")
        reg.expect(f"V{ph}.lat.p50.c25", vref(p, "2 load", "latency_ms", "a_median"), what="validation_real_v2")
        # drift vs thesis c = 1
        if ep == "inference":
            reg.add(f"V{ph}.drift.lat", f"Phase {ph} drift: real c = 1 median today / thesis April c = 1 median "
                                        f"(Locust 2 s.f. bucket)", "ratio",
                    [r1, [d["loc_med"] for d in th]], lambda g: pm(g, 0) / statistics.median(g[1]), section=sec,
                    used_in="6 text; T5; T6", src=srcr + "; " + srct, nd=3,
                    value_rule="value: pooled median today / median of the 5 thesis per-run Locust medians",
                    check=lambda v, lo, hi: (f"CI lower bound {lo:.3f}: a drift below {(lo - 1) * 100:.0f} % cannot be "
                                             f"excluded" if lo < 1.10 else None))
            reg.const("VA.thesis.lat.p50", "thesis April real FastAPI inference c = 1 median (Locust bucket, median of 5 runs)",
                      "ms", statistics.median(d["loc_med"] for d in th), section=sec, used_in="6 text; T5; T6", src=srct,
                      nd=0, why="2 significant-figure Locust bucket", n_runs=str(len(th)),
                      mn=min(d["loc_med"] for d in th), mx=max(d["loc_med"] for d in th))
            reg.expect(f"V{ph}.drift.lat", vref(p, "1 drift", "latency_ms", "median_ratio_a_over_b"), what="validation_real_v2")
        else:
            for key, lab, nd in (("lat", "latency", 3), ("ttft", "TTFT", 3), ("tpot", "TPOT", 3), ("chunks", "chunks", 3)):
                reg.add(f"V{ph}.drift.{key}", f"Phase {ph} drift: real c = 1 {lab} median today / thesis April c = 1",
                        "ratio", [r1, th], lambda g, key=key: pm(g, 0, key) / pm(g, 1, key), section=sec,
                        used_in="6 text; T5; T6", src=srcr + "; " + srct, nd=nd,
                        value_rule="value: pooled median today / pooled median of the 5 thesis runs")
                reg.add(f"V{ph}.thesis.{key}.p50", f"thesis April real FastAPI stream c = 1 {lab} median", "ms"
                        if key != "chunks" else "chunks", [th], lambda g, key=key: pm(g, 0, key), section=sec,
                        used_in="6 text; T5; T6", src=srct, nd=1 if key != "chunks" else 0,
                        value_rule="value: median pooled over the 5 thesis runs' streams")
            reg.expect("VB.drift.ttft", vref(p, "1 drift", "ttft_ms", "median_ratio_a_over_b"), what="validation_real_v2")
        # load ratios c = 25 / c = 1
        for key in (("lat", "ttft", "tpot", "chunks") if ep == "stream" else ("lat",)):
            for stn, fn in (("p50", np.median), ("p95", p95)):
                reg.add(f"V{ph}.load.{key}.{stn}", f"Phase {ph} load: real c = 25 / c = 1, {key} {stn}", "ratio", [r25, r1],
                        lambda g, key=key, fn=fn: pm(g, 0, key, fn) / pm(g, 1, key, fn), section=sec,
                        used_in="Abstract; 6 text; T5" if (key == "lat" and stn == "p50") else "6 text; T5",
                        src=srcr, nd=3, value_rule=f"value: pooled {stn} at c = 25 / pooled {stn} at c = 1",
                        check=(lambda v, lo, hi: f"CI [{lo:.3f}, {hi:.3f}] includes a load effect of "
                                                 f"{max(1 - lo, hi - 1) * 100:.0f} %" if max(1 - lo, hi - 1) > 0.05 else None)
                        if stn == "p50" else None)
        reg.expect(f"V{ph}.load.lat.p50", vref(p, "2 load", "latency_ms", "median_ratio_a_over_b"), what="validation_real_v2")
        # throughput at c = 25
        s_today = pm([r1], 0) / 1000
        reg.add(f"V{ph}.X.c25", f"Phase {ph} real throughput at c = 25 (completion rate in [t0 + 2 S_today, stop])", "req/s",
                [r25], lambda g, s=s_today: statistics.median(rate(d, s) for d in g[0]), section=sec,
                used_in="6 text; T5", src=srcr, nd=3, value_rule="value: median of the 3 per-run completion rates, "
                                                                  "window from the pooled c = 1 median S_today")
        reg.add(f"V{ph}.share.c25", f"Phase {ph} real throughput share of 25 / S_today at c = 25", "fraction", [r1, r25],
                lambda g: statistics.median(rate(d, pm(g, 0) / 1000) for d in g[1]) * (pm(g, 0) / 1000) / 25,
                section=sec, used_in="6 text; T5; F4", src=srcr, nd=3,
                value_rule="value: median per-run completion rate / (25 / S_today), S_today = pooled c = 1 median",
                check=lambda v, lo, hi: (f"CI [{lo:.3f}, {hi:.3f}] extends below 0.95 of the ceiling"
                                         if lo < 0.95 else None))
        reg.expect(f"V{ph}.share.c25", float([r for r in tcsv if r["phase"] == p and r["comparison"].startswith("3")][0]["share"]),
                   what="validation_real_v2_throughput")
        # simulator comparisons
        reg.add(f"V{ph}.factor", f"Phase {ph} scaling factor S_today / S_sim (S_sim = simulated c = 1 pooled median)",
                "ratio", [r1, s1], lambda g: pm(g, 0) / pm(g, 1), section=sec, used_in="6 text; T5; F4",
                src=srcr + "; " + srcs, nd=4, value_rule="value: pooled real c = 1 median / pooled simulated c = 1 median")
        for key in (("lat", "ttft") if ep == "stream" else ("lat",)):
            for stn, fn in (("p50", np.median), ("p95", p95)):
                reg.add(f"V{ph}.sim4a.{key}.{stn}", f"Phase {ph} real / simulated c = 25, absolute, {key} {stn}", "ratio",
                        [r25, s25], lambda g, key=key, fn=fn: pm(g, 0, key, fn) / pm(g, 1, key, fn), section=sec,
                        used_in="6 text; T5", src=srcr + "; " + srcs, nd=3, value_rule=f"value: pooled {stn} real / pooled {stn} sim")
                reg.add(f"V{ph}.sim4b.{key}.{stn}", f"Phase {ph} real / simulated c = 25 scaled by S_today / S_sim, {key} {stn}",
                        "ratio", [r25, s25, r1, s1],
                        lambda g, key=key, fn=fn: pm(g, 0, key, fn) / (pm(g, 1, key, fn) * pm(g, 2) / pm(g, 3)),
                        section=sec, used_in="6 text; T5; F4", src=srcr + "; " + srcs, nd=3,
                        value_rule=f"value: pooled {stn} real / (pooled {stn} sim x S_today / S_sim)")
                for c, rs_ in ((1, s1), (25, s25)):
                    if key == "lat":
                        reg.add(f"V{ph}.simsc.{key}.{stn}.c{c}", f"Phase {ph} simulated FastAPI {ep} {key} {stn}, c = {c}, "
                                                                 f"scaled by S_today / S_sim", "ms", [rs_, r1, s1],
                                lambda g, fn=fn: pm(g, 0, "lat", fn) * pm(g, 1) / pm(g, 2), section=sec,
                                used_in="F4", src=srcr + "; " + srcs, nd=1,
                                value_rule=f"value: pooled simulated {stn} x S_today / S_sim"
                                           + (" (equals the real c = 1 median by construction for p50)" if c == 1 and stn == "p50" else ""))
        reg.expect(f"V{ph}.sim4b.lat.p50", vref(p, "4b", "latency_ms", "median_ratio_a_over_b"), tol=1e-6, what="validation_real_v2")
        reg.add(f"V{ph}.simshare.c25", f"Phase {ph} simulated c = 25 throughput share after scaling (X_sim S_sim / 25)",
                "fraction", [s1, s25], lambda g: statistics.median(rate(d, pm(g, 0) / 1000) for d in g[1]) * pm(g, 0) / 1000 / 25,
                section=sec, used_in="6 text; T5", src=srcs, nd=3,
                value_rule="value: median per-run simulated completion rate (window t0 + 2 S_sim) x S_sim / 25")
        reg.expect(f"V{ph}.simshare.c25", float([r for r in tcsv if r["phase"] == p and r["comparison"].startswith("4")][0]["share"]),
                   what="validation_real_v2_throughput")
        reg.add(f"V{ph}.tail.c25", f"Phase {ph} real latency p95 / p50 at c = 25", "ratio", [r25],
                lambda g: pm(g, 0, "lat", p95) / pm(g, 0), section="9 Threats", used_in="9 text; 6 text", src=srcr,
                nd=3, ci="boot", value_rule="value: pooled p95 / pooled p50")
        # run-to-run spread of the per-run medians (output modes): max / min
        for c, rr in ((1, r1), (25, r25)):
            meds = [float(np.median(d["lat"])) for d in rr]
            reg.const(f"V{ph}.spread.c{c}", f"Phase {ph} c = {c}: largest / smallest per-run median latency (output-mode mix)",
                      "ratio", max(meds) / min(meds), section=sec, used_in="6 text; 9", src=srcr, nd=3,
                      why="this is itself the run-to-run spread", n_runs=str(len(rr)), mn=min(meds), mx=max(meds))
    a25 = load_runs(real_root, "inference", 25)
    reg.const("VA.maxrunp95", "largest per-run latency p95 among the real runs (Phase A c = 25 run 1)", "ms",
              max(float(p95(d["lat"])) for d in a25), section="9 Threats", used_in="9 text", src=SRC_REAL.format(ep="inference"),
              nd=0, why="maximum over runs", n_runs="3")

    # Phase C
    runs_all = final_real.real_runs()
    pc = {fw: [final_real.run_values(r["prefix"], "stream") for r in runs_all if r["phase"] == "C" and r["framework"] == fw]
          for fw in final_real.FWS}
    ap_ = {fw: [v for _run, _ts, v in final_real.thesis_c1(fw)] for fw in final_real.FWS}
    pcsv = {(r["framework"], r["metric"]): r for r in read(os.path.join(AOUT, "final_phase_c.csv"))}
    keymap = {"ttft": "ttft_ms", "tpot": "tpot_ms", "lat": "latency_ms"}

    def pmc(g, i, k):
        return float(np.median(np.concatenate([np.asarray(d[k], float) for d in g[i]])))

    for fw in final_real.FWS:
        for k, lab, unit, nd in (("ttft", "TTFT", "ms", 1), ("tpot", "TPOT", "ms per chunk", 2), ("lat", "latency", "ms", 0)):
            km = keymap[k]
            reg.add(f"VC.{fw}.{k}.today", f"Phase C real c = 1 stream {lab} median today, {fw}", unit, [pc[fw]],
                    lambda g, km=km: pmc(g, 0, km), section=sec, used_in="6 text; T5", src=SRC_PC.format(fw=fw), nd=nd,
                    value_rule="value: median pooled over the 3 runs' streams (final_real.py)")
            reg.add(f"VC.{fw}.{k}.april", f"thesis April real c = 1 stream {lab} median, {fw}", unit, [ap_[fw]],
                    lambda g, km=km: pmc(g, 0, km), section=sec, used_in="6 text; T5", src=SRC_THESIS_STR.format(fw=fw),
                    nd=nd, value_rule="value: median pooled over the 5 thesis runs' streams")
            reg.add(f"VC.{fw}.{k}.ratio", f"Phase C {lab} today / April, {fw}", "ratio", [pc[fw], ap_[fw]],
                    lambda g, km=km: pmc(g, 0, km) / pmc(g, 1, km), section=sec, used_in="T5",
                    src=SRC_PC.format(fw=fw) + "; " + SRC_THESIS_STR.format(fw=fw), nd=3,
                    value_rule="value: ratio of the pooled medians")
            reg.expect(f"VC.{fw}.{k}.today", float(pcsv[(fw, km)]["today_median"]), what="final_phase_c")
            reg.expect(f"VC.{fw}.{k}.april", float(pcsv[(fw, km)]["april_median"]), what="final_phase_c")
    for k, lab, unit, nd in (("ttft", "TTFT", "ms", 1), ("tpot", "TPOT", "ms per chunk", 2), ("lat", "latency", "ms", 1)):
        km = keymap[k]
        for era, grp, nr in (("today", pc, 3), ("april", ap_, 5)):
            reg.add(f"VC.spread.{k}.{era}", f"Phase C spread of the four framework {lab} medians (max - min), "
                                            f"{'today, interleaved' if era == 'today' else 'April, one block per framework'}",
                    unit, [grp[fw] for fw in final_real.FWS],
                    lambda g, km=km: max(pmc(g, i, km) for i in range(4)) - min(pmc(g, i, km) for i in range(4)),
                    section=sec, used_in="Abstract; 6 text; T5; T6; F5" if k == "ttft" else "6 text; T5",
                    src=(SRC_PC if era == "today" else SRC_THESIS_STR).format(fw="{flask,django,fastapi,tornado}"),
                    nd=nd, value_rule="value: largest minus smallest pooled framework median",
                    check=(lambda v, lo, hi: f"CI upper bound {hi:.1f} ms: a framework spread of this size cannot be "
                                             f"excluded" if hi > 2 * v else None) if (k == "ttft" and era == "today") else None)
    for era, grp in (("today", pc), ("april", ap_)):
        meds = [[float(np.median(d["ttft_ms"])) for d in grp[fw]] for fw in final_real.FWS]
        obs, pval, nperm = final_real.perm_test(meds)
        reg.const(f"VC.perm.{era}", f"Phase C permutation test on per-run TTFT medians ({era}; between-group sum of "
                                    f"squares, {nperm:,} permutations, seed 1)", "p", pval, section=sec,
                  used_in="6 text; T5", src=(SRC_PC if era == "today" else SRC_THESIS_STR).format(fw="{4 frameworks}") +
                  " (final_real.perm_test)", nd=6 if era == "april" else 3, why="p-value",
                  n_runs="+".join(str(len(m)) for m in meds))
    for fw in final_real.FWS:
        rr = [r for r in rpr if r["phase"] == "C" and r["framework"] == fw]
        for key, nm, lab, unit, nd in (("cpu_ms_per_request", "cpums", "CPU per request", "ms", 1),
                                       ("cpu_mean_loaded_pct", "cpu", "CPU mean", "% of one core", 2),
                                       ("peak_uss_mb", "uss", "peak USS", "MiB", 1)):
            reg.add(f"VC.{fw}.{nm}", f"Phase C real c = 1 stream {lab}, {fw}", unit, [[float(r[key]) for r in rr]], med0,
                    section=sec, used_in="6 text", src=SRC_RPR, nd=nd, value_rule="value: median of the 3 per-run values")
    vcg = [[float(r["cpu_ms_per_request"]) for r in rpr if r["phase"] == "C" and r["framework"] == fw]
           for fw in ("flask", "django", "fastapi", "tornado")]
    reg.add("VC.ratio.cpums", "Phase C CPU per real stream, sync (Flask, Django) / async (FastAPI, Tornado), c = 1", "x",
            vcg, mean_ratio(2), section=sec, used_in="6 text", src=SRC_RPR, nd=2,
            value_rule="value: mean of the Flask and Django medians / mean of the FastAPI and Tornado medians",
            check=lambda v, lo, hi: f"CI [{lo:.2f}, {hi:.2f}] includes 1" if lo <= 1 <= hi else None)
    reg.rng_("N.VC.cpums.sync", "Phase C CPU per request, Flask and Django", "ms",
             ["VC.flask.cpums", "VC.django.cpums"], section=sec, used_in="6 text", nd=1)
    reg.rng_("N.VC.cpums.async", "Phase C CPU per request, FastAPI and Tornado", "ms",
             ["VC.fastapi.cpums", "VC.tornado.cpums"], section=sec, used_in="6 text", nd=1)

    # ============================================================ 8 discussion: streaming CPU
    sec = "8 Discussion"
    rb = {c: [r for r in rpr if r["phase"] == "B" and r["concurrency"] == str(c)] for c in (1, 25)}
    for c in (1, 25):
        for key, nm, lab, unit, nd in (("cpu_ms_per_request", "cpums", "CPU per request", "ms", 1),
                                       ("cpu_mean_loaded_pct", "cpu", "CPU mean", "% of one core", 1),
                                       ("cpu_max_loaded_pct", "cpumax", "CPU maximum sample", "% of one core", 1)):
            reg.add(f"D.real.{nm}.c{c}", f"real FastAPI stream (Phase B) {lab}, c = {c}", unit,
                    [[float(r[key]) for r in rb[c]]], med0, section=sec, used_in="8 text; 6 text; T5" if c == 25 else "8 text",
                    src=SRC_RPR, nd=nd, value_rule="value: median of the 3 per-run values")
    r25b = load_runs(real_root, "stream", 25)
    reg.const("D.real.chunks.c25", "mean chunks per stream, real FastAPI stream c = 25", "chunks",
              float(np.mean(np.concatenate([d["chunks"] for d in r25b]))), section=sec, used_in="8 text",
              src=SRC_REAL.format(ep="stream"), nd=2, why="mean over 1,262 streams (projection input)", n_runs="3")
    reg.add("D.ratio.cpums.c25", "CPU per request real / simulated, FastAPI stream c = 25", "x",
            [[float(r["cpu_ms_per_request"]) for r in rb[25]], col("fastapi", "stream", 25, "cpu_ms_per_request")],
            lambda g: statistics.median(g[0]) / statistics.median(g[1]), section=sec, used_in="8 text; 6 text",
            src=SRC_RPR + "; " + SRC_PR, nd=2, value_rule="value: ratio of the medians")
    r1b = load_runs(real_root, "stream", 1)
    ch25 = float(np.mean(np.concatenate([d["chunks"] for d in r25b])))
    for fw in ASYNC:
        for c in (50, 100):
            reg.add(f"D.m1.{fw}.c{c}", f"Method 1 projected CPU with 92 chunks at X = c / S_today, {LABEL[fw]}, c = {c} "
                                       f"(INFERRED projection)", "% of one core",
                    [col(fw, "inference", c, "cpu_ms_per_request"), col(fw, "stream", c, "cpu_ms_per_request"), r1b],
                    lambda g, c=c: (c / (pm(g, 2, "sm_lat") / 1000)) * (statistics.median(g[0]) + N_NEW * (
                        statistics.median(g[1]) - statistics.median(g[0])) / N_SIM) / 10,
                    section=sec, used_in="8 text", src=SRC_PR + "; " + SRC_REAL.format(ep="stream"), nd=0,
                    value_rule="value: X x (inference ms + 92 x (stream ms - inference ms) / 12) / 10, X = c / S_today "
                               "(final_stream_cpu.py Method 1)",
                    check=lambda v, lo, hi: "CI includes 100 % (one core)" if lo <= 100 <= hi else None)
            if fw == "fastapi":
                g = [[float(r["cpu_ms_per_request"]) for r in rb[25]], col("fastapi", "stream", 25, "cpu_ms_per_request"),
                     col("fastapi", "stream", c, "cpu_ms_per_request"), r1b]
                f2 = (lambda g, c=c: (c / (pm(g, 3, "sm_lat") / 1000)) * statistics.median(g[0]) * statistics.median(g[2])
                      / statistics.median(g[1]) / 10)
            else:
                g = [[float(r["cpu_ms_per_request"]) for r in rb[25]], col("fastapi", "stream", 25, "cpu_ms_per_request"),
                     col("fastapi", "stream", c, "cpu_ms_per_request"), col("tornado", "stream", c, "cpu_ms_per_request"), r1b]
                f2 = (lambda g, c=c: (c / (pm(g, 4, "sm_lat") / 1000)) * statistics.median(g[0]) * statistics.median(g[2])
                      / statistics.median(g[1]) * statistics.median(g[3]) / statistics.median(g[2]) / 10)
            reg.add(f"D.m2.{fw}.c{c}", f"Method 2 projected CPU (anchored on real c = 25) at X = c / S_today, {LABEL[fw]}, "
                                       f"c = {c} (INFERRED projection)", "% of one core", g, f2, section=sec,
                    used_in="8 text", src=SRC_RPR + "; " + SRC_PR + "; " + SRC_REAL.format(ep="stream"), nd=0,
                    value_rule="value: real c = 25 CPU ms x simulated load efficiency (x Tornado / FastAPI) x c / S_today / 10 "
                               "(final_stream_cpu.py Method 2)",
                    check=lambda v, lo, hi: "CI includes 100 % (one core)" if lo <= 100 <= hi else None)
    reg.add("D.m1.check.c25", "Method 1 prediction / measured CPU per request, FastAPI stream c = 25 (92.08 chunks)", "x",
            [col("fastapi", "inference", 25, "cpu_ms_per_request"), col("fastapi", "stream", 25, "cpu_ms_per_request"),
             [float(r["cpu_ms_per_request"]) for r in rb[25]]],
            lambda g: (statistics.median(g[0]) + ch25 * (statistics.median(g[1]) - statistics.median(g[0])) / N_SIM)
            / statistics.median(g[2]), section=sec, used_in="8 text", src=SRC_PR + "; " + SRC_RPR, nd=2,
            value_rule="value: (inference ms + 92.08 x (stream ms - inference ms) / 12) / measured real ms")
    fsc = {(r["method"], r["framework"], int(r["concurrency"])): r for r in read(os.path.join(AOUT, "final_stream_cpu.csv"))}
    for fw in ASYNC:
        for c in (50, 100):
            reg.expect(f"D.m1.{fw}.c{c}", float(fsc[("1", fw, c)]["proj_pct_92_xtoday"]), what="final_stream_cpu")
            reg.expect(f"D.m2.{fw}.c{c}", float(fsc[("2", fw, c)]["proj_pct_92_xtoday"]), what="final_stream_cpu")

    # ============================================================ 7 pitfalls: thesis constants and v2 differences
    sec = "7 Pitfalls"
    thesis = [
        ("P.th.ratio", "thesis async / sync throughput at c = 100 (inference)", "x", 64, "72", "64", 0),
        ("P.th.sync", "thesis single-worker sync ceiling (inference)", "req/s", 0.34, "62", "0.34", 2),
        ("P.th.fastapiX", "thesis FastAPI throughput at c = 100 (inference)", "req/s", 21.74, "62", "21.74", 2),
        ("P.th.ttft.flask", "thesis Flask TTFT at c = 100", "ms", 28163, "89", "28,163", 0),
        ("P.th.ttft.django", "thesis Django TTFT at c = 100", "ms", 28113, "89", "28,113", 0),
        ("P.th.ttft.fastapi", "thesis FastAPI TTFT at c = 100", "ms", 1787, "65", "1,787", 0),
        ("P.th.ttft.tornado", "thesis Tornado TTFT at c = 100", "ms", 2003, "65", "2,003", 0),
        ("P.th.st2.fastapi", "thesis FastAPI Stage 2 at c = 100", "ms", 643.9, "69", "643.9", 1),
        ("P.th.st2.tornado", "thesis Tornado Stage 2 at c = 100", "ms", 468.6, "70", "468.6", 1),
        ("P.th.mem.inf", "thesis async / sync peak RSS (inference, 210 vs 73 MB)", "x", 2.9, "73", "2.9", 1),
        ("P.th.mem.str", "thesis async / sync peak RSS (stream)", "x", 4.5, "75", "4.5", 1),
        ("P.th.fastapiRSS", "thesis FastAPI peak RSS, stream, c = 100", "MiB", 332.2, "73", "332.2", 1),
        ("P.th.asynclat", "thesis async latency at c = 100 (inference)", "ms", 4500, "61", "4,500", 0),
    ]
    for nid, desc, unit, v, page, q, nd in thesis:
        reg.const(nid, desc, unit, v, section=sec, used_in="7 text; T6; F5", src=SRC_THESIS_PDF.format(p=page, q=q),
                  nd=nd, why="value printed in the thesis (RESULTS_FINAL 8)")

    def pct_vs(v2id, th, nid, desc):
        r = reg.by[v2id]
        g = [[r2 for r2 in reg_runs[v2id]]]
        reg.add(nid, desc, "%", g, lambda g: (statistics.median(g[0]) / th - 1) * 100, section=sec, used_in="T6",
                src=r["source_files"] + "; thesis value", nd=0, value_rule="value: (v2 median / thesis value - 1) x 100")

    reg_runs = {"X.inf.fastapi.c100": xs("fastapi", "inference", 100),
                "ST2.fastapi.c100": col("fastapi", "pipeline", 100, "stage2_p50_ms"),
                "ST2.tornado.c100": col("tornado", "pipeline", 100, "stage2_p50_ms"),
                "RSSP.str.fastapi.c100": col("fastapi", "stream", 100, "peak_rss_mb"),
                "TTFT.str.fastapi.c100": col("fastapi", "stream", 100, "ttft_p50_ms"),
                "TTFT.str.tornado.c100": col("tornado", "stream", 100, "ttft_p50_ms")}
    pct_vs("X.inf.fastapi.c100", 21.74, "P.d.fastapiX", "v2 vs thesis FastAPI throughput at c = 100")
    pct_vs("ST2.fastapi.c100", 643.9, "P.d.st2.fastapi", "v2 vs thesis FastAPI Stage 2 at c = 100")
    pct_vs("ST2.tornado.c100", 468.6, "P.d.st2.tornado", "v2 vs thesis Tornado Stage 2 at c = 100")
    pct_vs("RSSP.str.fastapi.c100", 332.2, "P.d.fastapiRSS", "v2 vs thesis FastAPI peak RSS, stream, c = 100")
    pct_vs("TTFT.str.fastapi.c100", 1787, "P.d.ttft.fastapi", "v2 vs thesis FastAPI TTFT at c = 100")
    pct_vs("TTFT.str.tornado.c100", 2003, "P.d.ttft.tornado", "v2 vs thesis Tornado TTFT at c = 100")
    reg.add("P.d.ratio", "v2 vs thesis async / sync throughput ratio at c = 100 (inference)", "%",
            ratio_groups(ASYNC, SYNC1, "inference", 100, "throughput_completion_rate"),
            lambda g: (mean_ratio(2)(g) / 64 - 1) * 100, section=sec, used_in="T6", src=SRC_PR + "; thesis value", nd=0,
            seed_id="RA1.inf.c100", value_rule="value: (v2 ratio / 64 - 1) x 100")
    reg.add("P.d.mem.inf", "v2 vs thesis async / sync peak RSS ratio (inference)", "%",
            ratio_groups(ASYNC, SYNC1, "inference", 100, "peak_rss_mb"), lambda g: (mean_ratio(2)(g) / 2.9 - 1) * 100,
            section=sec, used_in="T6", src=SRC_PR + "; thesis value", nd=0, seed_id="MRSS.inf.c100", value_rule="value: (v2 ratio / 2.9 - 1) x 100")
    reg.add("P.d.mem.str", "v2 vs thesis async / sync peak RSS ratio (stream)", "%",
            ratio_groups(ASYNC, SYNC1, "stream", 100, "peak_rss_mb"), lambda g: (mean_ratio(2)(g) / 4.5 - 1) * 100,
            section=sec, used_in="T6", src=SRC_PR + "; thesis value", nd=0, seed_id="MRSS.str.c100", value_rule="value: (v2 ratio / 4.5 - 1) x 100")
    reg.add("P.v2sync", "v2 one-worker sync throughput, inference, c = 100 (mean of Flask and Django)", "req/s",
            [xs("flask", "inference", 100), xs("django", "inference", 100)],
            lambda g: statistics.mean(statistics.median(x) for x in g), section=sec, used_in="7 text; T6", src=SRC_PR,
            nd=4, value_rule="value: mean of the two per-configuration medians")
    reg.add("P.d.sync", "v2 vs thesis single-worker sync ceiling (0.34 req/s), inference", "%",
            [xs("flask", "inference", 100), xs("django", "inference", 100)],
            lambda g: (statistics.mean(statistics.median(x) for x in g) / 0.34 - 1) * 100, section=sec, used_in="T6",
            src=SRC_PR + "; thesis value", nd=1, seed_id="P.v2sync", value_rule="value: (v2 / 0.34 - 1) x 100")
    reg_runs["TTFT.str.flask.c100"] = col("flask", "stream", 100, "ttft_p50_ms")
    reg_runs["TTFT.str.django.c100"] = col("django", "stream", 100, "ttft_p50_ms")
    pct_vs("TTFT.str.flask.c100", 28163, "P.d.ttft.flask", "v2 (censored) vs thesis Flask TTFT at c = 100")
    pct_vs("TTFT.str.django.c100", 28113, "P.d.ttft.django", "v2 (censored) vs thesis Django TTFT at c = 100")
    reg.add("P.d.asynclat", "v2 vs thesis async latency at c = 100 (4,500 ms), inference", "%",
            [col("fastapi", "inference", 100, "latency_p50_ms"), col("tornado", "inference", 100, "latency_p50_ms")],
            lambda g: (statistics.mean(statistics.median(x) for x in g) / 4500 - 1) * 100, section=sec, used_in="T6",
            src=SRC_PR + "; thesis value", nd=0, seed_id="P.asynclat", value_rule="value: (v2 / 4,500 - 1) x 100")
    reg.add("P.d.spread", "Phase C TTFT spread today / April spread, minus 1", "%",
            [pc[fw] for fw in final_real.FWS] + [ap_[fw] for fw in final_real.FWS],
            lambda g: ((max(pmc(g, i, "ttft_ms") for i in range(4)) - min(pmc(g, i, "ttft_ms") for i in range(4)))
                       / (max(pmc(g, i, "ttft_ms") for i in range(4, 8)) - min(pmc(g, i, "ttft_ms") for i in range(4, 8)))
                       - 1) * 100, section=sec, used_in="T6", src=SRC_PC.format(fw="{4 frameworks}") + "; " +
            SRC_THESIS_STR.format(fw="{4 frameworks}"), nd=0,
            value_rule="value: (spread today / spread April - 1) x 100")
    reg.add("P.ttft.growth", "one-worker sync derived steady-state TTFT / measured (window-censored) TTFT at c = 100", "x",
            [col(f, "stream", 100, "derived_ttft_ms") for f in SYNC1] + [col(f, "stream", 100, "ttft_p50_ms") for f in SYNC1],
            mean_ratio(2), section=sec, used_in="7 text; T6", src=SRC_PR, nd=1,
            value_rule="value: mean(Flask, Django) derived TTFT / mean(Flask, Django) measured TTFT p50 (medians)")
    reg.add("P.asynclat", "v2 async latency p50 at c = 100, inference (mean of FastAPI and Tornado)", "ms",
            [col("fastapi", "inference", 100, "latency_p50_ms"), col("tornado", "inference", 100, "latency_p50_ms")],
            lambda g: statistics.mean(statistics.median(x) for x in g), section=sec, used_in="7 text; T6", src=SRC_PR, nd=0,
            value_rule="value: mean of the two per-configuration medians")
    sq = [d["loc_med"] for d in load_runs(th_root, "inference", 1, thesis=True)]
    reg.add("P.d.S", "real inference service time today (c = 1 pooled median) vs the April thesis bucket 2,800 ms", "%",
            [load_runs(real_root, "inference", 1), sq], lambda g: (pm(g, 0) / statistics.median(g[1]) - 1) * 100,
            section=sec, used_in="6 text; T6", src=SRC_REAL.format(ep="inference") + "; " + SRC_THESIS_INF, nd=1,
            value_rule="value: (pooled median today / median of the thesis per-run Locust medians - 1) x 100",
            check=lambda v, lo, hi: (f"CI [{lo:.1f}, {hi:.1f}] %: the size of the drift is uncertain"
                                     if hi - lo > 10 else None))

    # ============================================================ outputs
    with open(os.path.join(OUT, "numbers.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "description", "value", "unit", "ci_low", "ci_high", "min", "max", "n_runs", "method",
                    "source_files"])
        for r in reg.rows:
            w.writerow([r["id"], r["description"], num(r["value"]), r["unit"], num(r["ci_low"]), num(r["ci_high"]),
                        num(r["min"]), num(r["max"]), r["n_runs"], r["method"], r["source_files"]])
    with open(os.path.join(OUT, "numbers_meta.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "section", "used_in", "decimals", "flag"])
        for r in reg.rows:
            w.writerow([r["id"], r["section"], r["used_in"], r["decimals"], r["flag"]])
    bad = [c for c in reg.checks if not c[3]]
    print(f"{len(reg.rows)} numbers; {len(reg.checks)} consistency checks against RESULTS_FINAL outputs, "
          f"{len(bad)} failed")
    for c in bad:
        print(f"  CHECK FAILED {c[0]}: {c[1]!r} vs {c[2]!r} ({c[4]})")
    print(f"flagged: {sum(1 for r in reg.rows if r['flag'])}")
    print(f"Saved {os.path.relpath(OUT, ROOT)}/numbers.csv, numbers_meta.csv")


def num(x):
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    return f"{x:.10g}"


if __name__ == "__main__":
    main()
