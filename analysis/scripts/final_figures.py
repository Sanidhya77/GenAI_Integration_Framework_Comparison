"""
Figures for RESULTS_FINAL (matplotlib, PNG, 150 dpi) -> analysis/out/figures/. Read-only on data.

Inputs: analysis/out/final_mw.csv, final_steady_state.csv, final_real_levels.csv, final_phase_c.csv
(from final_mw.py, final_steady_state.py, final_real.py), results_v2/summary_v2.csv (censoring counts),
data_v2/fastapi/{inference,stream}/c{1,25}_run*_requests.csv / _stream_metrics.csv (simulated pooled
values for figure e).

Colour: execution model = categorical slots 1 to 3 of the dataviz reference palette (blue, orange,
aqua; documented as passing all-pairs CVD checks in light mode); framework within a model = line
style and marker (solid circle vs dashed square). Reference lines are grey.
"""

import csv
import glob
import os
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "analysis", "out")
FIG = os.path.join(OUT, "figures")
EPS = ["inference", "stream", "pipeline"]
CS = [1, 5, 10, 25, 50, 100]
W = 17
BLUE, ORANGE, AQUA, GREY, INK, INK2 = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984", "#0b0b0b", "#52514e"
STYLE = {
    "flask": dict(color=BLUE, ls="-", marker="o", label="Flask (1 sync worker)"),
    "django": dict(color=BLUE, ls="--", marker="s", label="Django (1 sync worker)"),
    "flask_mw": dict(color=ORANGE, ls="-", marker="o", label="Flask (17 sync workers)"),
    "django_mw": dict(color=ORANGE, ls="--", marker="s", label="Django (17 sync workers)"),
    "fastapi": dict(color=AQUA, ls="-", marker="o", label="FastAPI (async)"),
    "tornado": dict(color=AQUA, ls="--", marker="s", label="Tornado (async)"),
}
ORDER = ["flask", "django", "flask_mw", "django_mw", "fastapi", "tornado"]

plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "savefig.facecolor": "#fcfcfb",
    "axes.edgecolor": "#b5b4ad", "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.grid": True, "grid.color": "#e4e3de", "grid.linewidth": 0.6, "axes.spines.top": False,
    "axes.spines.right": False, "font.size": 9, "axes.titlesize": 10, "legend.fontsize": 8,
    "legend.frameon": False, "lines.linewidth": 1.4, "lines.markersize": 5,
})


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x):
    return None if x in (None, "", "None") else float(x)


def pct(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def logx(ax):
    ax.set_xscale("log")
    ax.set_xticks(CS)
    ax.set_xticklabels([str(c) for c in CS])
    ax.minorticks_off()


def yticks(ax, ticks):
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"{t:g}" for t in ticks])
    ax.minorticks_off()
    ax.set_xticks(CS)


def plot_series(ax, fw, xs, ys, hollow=None, **kw):
    st = STYLE[fw]
    ax.plot(xs, ys, color=st["color"], ls=st["ls"], lw=1.4, label=st["label"], zorder=3, **kw)
    for x, y, h in zip(xs, ys, hollow or [False] * len(xs)):
        ax.plot([x], [y], marker=st["marker"], ms=5, color=st["color"], mfc="#fcfcfb" if h else st["color"],
                mew=1.2, ls="none", zorder=4)


def save(fig, name):
    path = os.path.join(FIG, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", os.path.relpath(path, ROOT))


def main():
    os.makedirs(FIG, exist_ok=True)
    mw = {(r["config"], r["endpoint"], int(r["concurrency"])): r for r in read(os.path.join(OUT, "final_mw.csv"))}
    ss = {(r["config"], r["endpoint"], int(r["concurrency"])): r for r in read(os.path.join(OUT, "final_steady_state.csv"))}
    cens = {(r["framework"], r["endpoint"], int(r["concurrency"])): int(r["percentiles_censored_runs"])
            for r in read(os.path.join(ROOT, "results_v2", "summary_v2.csv"))}

    # (a) throughput vs c
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.9), sharey=True)
    for ax, ep in zip(axes, EPS):
        s = float(mw[("flask", ep, 1)]["S_s"])
        for fw in ORDER:
            plot_series(ax, fw, CS, [float(mw[(fw, ep, c)]["x_best"]) for c in CS])
        ax.plot(CS, [c / s for c in CS], color=GREY, ls=":", lw=1, zorder=2)
        ax.axhline(1 / s, color=GREY, ls=":", lw=1, zorder=2)
        ax.axhline(W / s, color=GREY, ls=":", lw=1, zorder=2)
        ax.text(1.05, 1 / s * 1.12, f"1/S = {1 / s:.3f}", color=INK2, fontsize=7.5)
        ax.text(1.05, W / s * 1.12, f"17/S = {W / s:.2f}", color=INK2, fontsize=7.5)
        ax.text(40, 40 / s * 1.35, "c/S", color=INK2, fontsize=7.5)
        logx(ax)
        ax.set_yscale("log")
        yticks(ax, [0.3, 1, 3, 10, 30])
        ax.set_title(f"{ep} (S = {s} s)")
        ax.set_xlabel("concurrency c (users)")
    axes[0].set_ylabel("throughput X (req/s, log scale)")
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.2), ncol=6, fontsize=7.5)
    fig.suptitle("(a) Throughput vs concurrency: sync capped at 1/S or 17/S, async follows c/S (median of 5 runs)",
                 fontsize=10.5, y=1.02)
    save(fig, "a_throughput_vs_c.png")

    # (b) mean latency vs c, steady state for sync, R = N/X lines
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.9), sharey=True)
    for ax, ep in zip(axes, EPS):
        for fw in ORDER:
            xs, ys, hol = [], [], []
            for c in CS:
                if fw in ("flask", "django") and c >= 25:
                    xs.append(c)
                    ys.append(float(mw[(fw, ep, c)]["latency_mean_ms"]) / 1000)
                    hol.append(True)
                    continue
                r = ss.get((fw, ep, c))
                v = fnum(r["A_mean"]) if r else None
                xs.append(c)
                ys.append((v if v is not None else float(mw[(fw, ep, c)]["latency_mean_ms"])) / 1000)
                hol.append(False)
            st = STYLE[fw]
            ax.plot(CS, [float(mw[(fw, ep, c)]["R_best_ms"]) / 1000 for c in CS], color=st["color"], ls=st["ls"],
                    lw=1.0, alpha=0.55, zorder=2)
            for x, y, h in zip(xs, ys, hol):
                ax.plot([x], [y], marker=st["marker"], ms=5, color=st["color"], mfc="#fcfcfb" if h else st["color"],
                        mew=1.2, ls="none", zorder=4, label=None)
        logx(ax)
        ax.set_yscale("log")
        yticks(ax, [3, 10, 30, 100, 300])
        ax.set_title(ep)
        ax.set_xlabel("concurrency c (users)")
    axes[0].set_ylabel("mean latency (s, log scale)")
    handles = [plt.Line2D([], [], color=STYLE[f]["color"], ls=STYLE[f]["ls"], marker=STYLE[f]["marker"],
                          label=STYLE[f]["label"]) for f in ORDER]
    handles += [plt.Line2D([], [], color=GREY, ls="-", alpha=0.55, label="line: R = N/X"),
                plt.Line2D([], [], color=GREY, marker="o", ls="none", label="filled: measured mean (sync: steady state)"),
                plt.Line2D([], [], color=GREY, marker="o", mfc="#fcfcfb", ls="none",
                           label="hollow: full-window mean, censored (1 worker, c >= 25)")]
    axes[0].legend(handles=handles, loc="upper left", bbox_to_anchor=(0, -0.2), ncol=5, fontsize=7.5)
    fig.suptitle("(b) Mean latency vs concurrency: steady-state means match R = N/X; 1-worker c >= 25 is censored",
                 fontsize=10.5, y=1.02)
    save(fig, "b_latency_vs_c.png")

    # (c) TTFT p50 and p95 vs c, stream
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), sharey=True)
    for ax, (k, name) in zip(axes, (("ttft_p50_ms", "p50"), ("ttft_p95_ms", "p95"))):
        for fw in ORDER:
            plot_series(ax, fw, CS, [float(mw[(fw, "stream", c)][k]) / 1000 for c in CS],
                        hollow=[cens.get((fw, "stream", c), 0) > 0 for c in CS])
        logx(ax)
        ax.set_yscale("log")
        yticks(ax, [0.5, 1, 3, 10, 30, 60])
        ax.set_title(f"TTFT {name}")
        ax.set_xlabel("concurrency c (users)")
    axes[0].set_ylabel("time to first token (s, log scale)")
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.2), ncol=3, fontsize=7.5)
    axes[1].text(1.05, 60, "hollow = percentiles censored (5 of 5 runs)", color=INK2, fontsize=7.5)
    fig.suptitle("(c) Stream TTFT vs concurrency (simulated, median of 5 runs): async flat near 0.57 s",
                 fontsize=10.5, y=1.02)
    save(fig, "c_ttft_vs_c.png")

    # (d) peak USS vs c
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.9), sharey=True)
    for ax, ep in zip(axes, EPS):
        for fw in ORDER:
            plot_series(ax, fw, CS, [float(mw[(fw, ep, c)]["peak_uss_mb"]) for c in CS])
        logx(ax)
        ax.set_yscale("log")
        yticks(ax, [40, 60, 100, 200, 400, 800])
        ax.set_title(ep)
        ax.set_xlabel("concurrency c (users)")
    axes[0].set_ylabel("peak USS (MiB, log scale)")
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.2), ncol=6, fontsize=7.5)
    fig.suptitle("(d) Peak unique memory (USS) vs concurrency (median of 5 runs; 17 workers = sum of 18 processes)", fontsize=10.5, y=1.02)
    save(fig, "d_peak_uss_vs_c.png")

    # (e) real vs simulated (scaled to S_today), Phases A and B
    lv = {(r["phase"], r["concurrency"], r["metric"]): r for r in read(os.path.join(OUT, "final_real_levels.csv"))}

    def sim_pooled(ep, c, metric):
        vals = []
        for p in sorted(glob.glob(os.path.join(ROOT, "data_v2", "fastapi", ep, f"c{c}_run*_requests.csv"))):
            if metric == "latency_ms":
                vals += [float(r["response_time_ms"]) for r in read(p) if r["success"] == "True"]
            else:
                sm = p.replace("_requests.csv", "_stream_metrics.csv")
                vals += [float(r["ttft_ms"]) for r in read(sm) if r["success"] == "True" and r["ttft_ms"]]
        return statistics.median(vals), pct(vals, 95)

    panels = [("A", "inference", "latency_ms", "Phase A inference: latency"),
              ("B", "stream", "latency_ms", "Phase B stream: latency"),
              ("B", "stream", "ttft_ms", "Phase B stream: TTFT")]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.9))
    for ax, (ph, ep, metric, title) in zip(axes, panels):
        s_today = float(lv[(ph, "1", "latency_ms")]["pooled_median"])
        s_sim = sim_pooled(ep, 1, "latency_ms")[0]
        f = s_today / s_sim
        labels, real_v, sim_v = [], [], []
        for c in (1, 25):
            r = lv[(ph, str(c), metric)]
            sm, sp = sim_pooled(ep, c, metric)
            for stat, rv, sv in (("p50", float(r["pooled_median"]), sm * f), ("p95", float(r["pooled_p95"]), sp * f)):
                labels.append(f"c = {c}\n{stat}")
                real_v.append(rv / 1000)
                sim_v.append(sv / 1000)
        x = range(len(labels))
        ax.bar([i - 0.19 for i in x], real_v, width=0.36, color=BLUE, label="real API, 28 Sep 2026 (3 runs)")
        ax.bar([i + 0.19 for i in x], sim_v, width=0.36, color=ORANGE,
               label="simulator scaled by S_today / S_sim (5 runs)")
        for i, (rv, sv) in enumerate(zip(real_v, sim_v)):
            ax.text(i - 0.19, rv, f"{rv:.2f}", ha="center", va="bottom", fontsize=6.8, color=INK)
            ax.text(i + 0.19, sv, f"{sv:.2f}", ha="center", va="bottom", fontsize=6.8, color=INK)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels)
        ax.set_title(f"{title} (sim x{f:.4f})")
        ax.grid(axis="x", visible=False)
        ax.set_ylabel("seconds (pooled over runs)")
        ax.set_ylim(0, max(real_v + sim_v) * 1.18)
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.2), ncol=2, fontsize=7.5)
    fig.suptitle("(e) Real API vs simulator scaled to today's service time, FastAPI, c = 1 and c = 25",
                 fontsize=10.5, y=1.02)
    save(fig, "e_real_vs_sim.png")

    # (f) Phase C: c = 1 real stream TTFT per framework, today vs April
    pc = [r for r in read(os.path.join(OUT, "final_phase_c.csv")) if r["metric"] == "ttft_ms"]
    fws = ["flask", "django", "fastapi", "tornado"]
    fig, ax = plt.subplots(figsize=(7.5, 4))
    for i, fw in enumerate(fws):
        r = [x for x in pc if x["framework"] == fw][0]
        for off, era, col, lab in ((-0.18, "april", BLUE, "April 2026 (thesis, 5 runs, one block per framework)"),
                                   (0.18, "today", ORANGE, "28 Sep 2026 (Phase C, 3 runs, interleaved)")):
            med = float(r[f"{era}_median"])
            runs = [float(v) for v in r[f"{era}_run_medians"].split(";")]
            ax.bar(i + off, med, width=0.34, color=col, label=lab if i == 0 else None, zorder=2)
            ax.plot([i + off] * len(runs), runs, ls="none", marker="o", ms=4, mfc="#fcfcfb", mec=INK, mew=0.9,
                    zorder=3, label="per-run median" if (i == 0 and era == "today") else None)
            ax.text(i + off, max(runs + [med]) + 12, f"{med:.0f}", ha="center", va="bottom", fontsize=7.5, color=INK)
    ax.set_xticks(range(len(fws)))
    ax.set_xticklabels(["Flask", "Django", "FastAPI", "Tornado"])
    ax.set_ylabel("TTFT, pooled median (ms)")
    ax.grid(axis="x", visible=False)
    ax.set_ylim(0, 1000)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.1), ncol=1, fontsize=7.5)
    ax.set_title("(f) Real c = 1 stream TTFT per framework: April spread 187 ms, today 22 ms", fontsize=10.5)
    save(fig, "f_phase_c_ttft.png")


if __name__ == "__main__":
    main()
