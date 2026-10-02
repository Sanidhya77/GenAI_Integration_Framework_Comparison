"""
Publication figures F1 to F6 (+ appendix FA) for the paper, from analysis/out/paper/numbers.csv (paper_stats.py).
Read-only on data. Vector PDF (Type 42 fonts) and PNG (300 dpi), width 3.33 in (one ACM column) unless noted,
text 8 to 9 pt. Also writes captions.md with a draft caption per figure; whether the 95 % CI error bars are
visible is measured on the rendered figure and stated in the caption.

Style: one colour, marker and fill per configuration in every figure (Okabe-Ito colours; checked with the
dataviz palette validator in light mode on white: adjacent CVD dE >= 9.6, all-pairs CVD dE 7.6 = WARN band, so
secondary encoding is mandatory and provided); line style per execution model (one sync worker solid,
17 workers dashed, async dash-dot); first framework of a class filled and small, second hollow and larger,
so overlapping series stay visible and the figures read in black and white.

Output: <paper dir>/figures/F*.pdf, F*.png, captions.md
Usage:  venv/bin/python analysis/scripts/paper_figures.py [--paper-dir DIR]
"""

import argparse
import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IN = os.path.join(ROOT, "analysis", "out", "paper")
EPS = [("inference", "inf"), ("stream", "str"), ("pipeline", "pip")]
CS = [1, 5, 10, 25, 50, 100]
W_IN = 3.33
INK, INK2, GRID, REF = "#0b0b0b", "#52514e", "#e4e3de", "#8a8984"
STYLE = {
    "flask": dict(label="Flask", color="#0072B2", marker="o", ms=3.6, fill=True, ls="-"),
    "django": dict(label="Django", color="#56B4E9", marker="s", ms=5.2, fill=False, ls="-"),
    "flask17w": dict(label="Flask 17w", color="#D55E00", marker="D", ms=3.2, fill=True, ls="--"),
    "django17w": dict(label="Django 17w", color="#E69F00", marker="v", ms=5.6, fill=False, ls="--"),
    "fastapi": dict(label="FastAPI", color="#009E73", marker="^", ms=3.8, fill=True, ls="-."),
    "tornado": dict(label="Tornado", color="#CC79A7", marker="p", ms=5.6, fill=False, ls="-."),
}
ORDER = ["flask", "django", "flask17w", "django17w", "fastapi", "tornado"]

plt.rcParams.update({
    "pdf.fonttype": 42, "ps.fonttype": 42, "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8.5,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8, "figure.dpi": 100, "savefig.dpi": 300,
    "axes.edgecolor": "#8a8984", "axes.linewidth": 0.6, "axes.labelcolor": INK, "xtick.color": INK2,
    "ytick.color": INK2, "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5,
    "ytick.major.size": 2.5, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "lines.linewidth": 1.0,
    "savefig.pad_inches": 0.02, "figure.facecolor": "white", "axes.facecolor": "white",
})


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Nums:
    def __init__(self):
        self.n = {r["id"]: r for r in read(os.path.join(IN, "numbers.csv"))}

    def v(self, i):
        return float(self.n[i]["value"])

    def ci(self, i):
        r = self.n[i]
        return (float(r["ci_low"]), float(r["ci_high"])) if r["ci_low"] else (None, None)


class Bars:
    """Collects plotted CI extents in points to decide whether error bars are visible."""

    def __init__(self):
        self.items = []

    def add(self, ax, x, lo, hi, size_pt):
        self.items.append((ax, x, lo, hi, size_pt))

    def visible(self, fig):
        fig.canvas.draw()
        vis = 0
        for ax, x, lo, hi, size in self.items:
            (x0, y0), (x1, y1) = ax.transData.transform([(x, lo), (x, hi)])
            if abs(y1 - y0) / fig.dpi * 72 > size:
                vis += 1
        return vis, len(self.items)


def logx(ax):
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(FixedLocator(CS))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_xlim(0.8, 125)


def logy(ax, ticks):
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))


def series(ax, cfg, xs, ys, cis, bars, line=True, lw=1.0, marker=True):
    st = STYLE[cfg]
    if line:
        ax.plot(xs, ys, color=st["color"], ls=st["ls"], lw=1.5 if st["fill"] else 0.8, zorder=2 if st["fill"] else 2.5)
    for x, y, (lo, hi) in zip(xs, ys, cis):
        if lo is not None:
            ax.errorbar([x], [y], yerr=[[y - lo], [hi - y]], fmt="none", ecolor=st["color"], elinewidth=0.7, capsize=1.5,
                        capthick=0.7, zorder=3)
            bars.add(ax, x, lo, hi, st["ms"])
        if marker:
            ax.plot([x], [y], ls="none", marker=st["marker"], ms=st["ms"], mew=0.8, color=st["color"],
                    mfc=st["color"] if st["fill"] else "none", zorder=4 if st["fill"] else 4.5)


def legend_handles(extra=()):
    hs = [plt.Line2D([], [], color=STYLE[c]["color"], ls=STYLE[c]["ls"], lw=1.5 if STYLE[c]["fill"] else 0.8,
                     marker=STYLE[c]["marker"], ms=STYLE[c]["ms"], mew=0.8,
                     mfc=STYLE[c]["color"] if STYLE[c]["fill"] else "none",
                     label=STYLE[c]["label"]) for c in ORDER]
    return hs + list(extra)


def save(fig, d, name):
    fig.savefig(os.path.join(d, name + ".pdf"))
    fig.savefig(os.path.join(d, name + ".png"), dpi=300)
    plt.close(fig)


def bar_note(vis, tot):
    if vis == 0:
        return (f"Error bars show the 95 % CI of each point ({tot} points); all are smaller than the markers, so none "
                f"is visible.")
    if vis == tot:
        return f"Error bars show the 95 % CI; all {tot} are visible."
    return (f"Error bars show the 95 % CI; {vis} of {tot} extend beyond the marker, the rest are smaller than the "
            f"marker.")


# ---------------------------------------------------------------- panels
def throughput_panel(ax, n, ea, S, bars, title=None):
    for cfg in ORDER:
        ys = [n.v(f"X.{ea}.{cfg}.c{c}") for c in CS]
        series(ax, cfg, CS, ys, [n.ci(f"X.{ea}.{cfg}.c{c}") for c in CS], bars)
    ax.plot(CS, [c / S for c in CS], color=REF, ls=":", lw=0.8, zorder=1)
    ax.axhline(1 / S, color=REF, ls=":", lw=0.8, zorder=1)
    ax.axhline(17 / S, color=REF, ls=":", lw=0.8, zorder=1)
    ax.text(125, 1 / S * 1.12, "1/S", color=INK2, ha="right", va="bottom", fontsize=8)
    ax.text(125, 17 / S * 1.12, "17/S", color=INK2, ha="right", va="bottom", fontsize=8)
    ax.text(30, 30 / S * 1.45, "c/S", color=INK2, ha="right", va="bottom", fontsize=8)
    logx(ax)
    logy(ax, [0.3, 1, 3, 10, 30])
    ax.set_ylim(0.25, 55)
    ax.set_xlabel("concurrent users c")
    ax.set_ylabel("throughput (req/s)")
    if title:
        ax.set_title(title)


def latency_panel(ax, n, ea, bars, title=None):
    for cfg in ORDER:
        st = STYLE[cfg]
        r = [c / n.v(f"X.{ea}.{cfg}.c{c}") for c in CS]
        ax.plot(CS, r, color=st["color"], ls=st["ls"], lw=1.5 if st["fill"] else 0.8, zorder=2 if st["fill"] else 2.5)
        pts = [(c, f"LM.{ea}.{cfg}.c{c}") for c in CS if f"LM.{ea}.{cfg}.c{c}" in n.n]
        series(ax, cfg, [c for c, _ in pts], [n.v(i) / 1000 for _, i in pts],
               [tuple(x / 1000 for x in n.ci(i)) for _, i in pts], bars, line=False)
    logx(ax)
    logy(ax, [3, 10, 30, 100, 300])
    ax.set_ylim(2.2, 420)
    ax.set_xlabel("concurrent users c")
    ax.set_ylabel("mean latency (s)")
    if title:
        ax.set_title(title)


def uss_panel(ax, n, ea, bars, title=None):
    for cfg in ORDER:
        series(ax, cfg, CS, [n.v(f"USSP.{ea}.{cfg}.c{c}") for c in CS], [n.ci(f"USSP.{ea}.{cfg}.c{c}") for c in CS], bars)
    logx(ax)
    logy(ax, [40, 60, 100, 200, 400, 800])
    ax.set_ylim(36, 1000)
    ax.set_xlabel("concurrent users c")
    ax.set_ylabel("peak USS (MiB)")
    if title:
        ax.set_title(title)


def cpu_panel(ax, n, ea, bars, title=None):
    for cfg in ORDER:
        series(ax, cfg, CS, [n.v(f"CPUMS.{ea}.{cfg}.c{c}") for c in CS], [n.ci(f"CPUMS.{ea}.{cfg}.c{c}") for c in CS], bars)
    logx(ax)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("concurrent users c")
    ax.set_ylabel("CPU per request (ms)")
    if title:
        ax.set_title(title)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper-dir", default=os.path.expanduser("~/paper_context/paper"))
    a = ap.parse_args()
    d = os.path.join(a.paper_dir, "figures")
    os.makedirs(d, exist_ok=True)
    n = Nums()
    S = {ea: n.v(f"M.S.{ea}") for _, ea in EPS}
    cap = {}

    # F1 throughput vs c, inference
    fig, ax = plt.subplots(figsize=(W_IN, 2.9), layout="constrained")
    b = Bars()
    throughput_panel(ax, n, "inf", S["inf"], b)
    fig.legend(handles=legend_handles(), loc="outside lower center", ncol=3, handlelength=2.6, columnspacing=1.0)
    vis, tot = b.visible(fig)
    save(fig, d, "F1_throughput")
    cap["F1_throughput"] = (
        "Throughput versus concurrency for the inference endpoint (median of 5 runs; log-log). Dotted reference "
        f"lines: 1/S = {1 / S['inf']:.3f} req/s, 17/S = {17 / S['inf']:.2f} req/s and c/S (S = {S['inf']:.3f} s). "
        f"The async servers follow c/S up to c = 100 ({n.v('X.inf.fastapi.c100'):.2f} and "
        f"{n.v('X.inf.tornado.c100'):.2f} req/s), one sync worker stays at 1/S and 17 workers at 17/S, whichever "
        "framework runs on them. " + bar_note(vis, tot) + " Stream and pipeline: Figure FA (rows a).")

    # F2 latency vs c
    ssr = [float(r["value"]) for i, r in n.n.items() if i.startswith("SSR.") and i.split(".")[1] == "inf"]
    dev_ssr = max(abs(1 - x) for x in ssr) * 100
    fig, ax = plt.subplots(figsize=(W_IN, 2.9), layout="constrained")
    b = Bars()
    latency_panel(ax, n, "inf", b)
    ax.text(0.03, 0.97, "markers: measured mean\nlines: R = N/X = c/X", transform=ax.transAxes, ha="left", va="top",
            fontsize=8, color=INK2)
    fig.legend(handles=legend_handles(), loc="outside lower center", ncol=3, handlelength=2.6, columnspacing=1.0)
    vis, tot = b.visible(fig)
    save(fig, d, "F2_latency")
    cap["F2_latency"] = (
        "Mean latency versus concurrency, inference (log-log). Markers: measured mean, for sync servers the steady "
        "state (requests started after the first queue cycle, pooled over 5 runs); lines: the response-time law "
        "R = N/X = c/X from the measured throughput. One sync worker at c >= 25 has no marker: no steady-state request "
        "completes in the 60 s window, and R reaches "
        f"{n.v('LR.inf.flask.c100') / 1000:.0f} s at c = 100. Measured steady-state means lie on R within "
        f"{dev_ssr:.2f} %, while async latency stays at S. " + bar_note(vis, tot))

    # F3 peak USS vs c
    fig, ax = plt.subplots(figsize=(W_IN, 2.9), layout="constrained")
    b = Bars()
    uss_panel(ax, n, "inf", b)
    fig.legend(handles=legend_handles(), loc="outside lower center", ncol=3, handlelength=2.6, columnspacing=1.0)
    vis, tot = b.visible(fig)
    save(fig, d, "F3_peak_uss")
    cap["F3_peak_uss"] = (
        "Peak unique set size (USS) of the server process tree versus concurrency, inference (median of 5 runs; log "
        "y axis; 17 workers summed over 18 processes). Within a class the frameworks differ by a constant "
        f"(Django {n.n['N.SC.USSP.django_flask']['value']} % above Flask); async servers grow by "
        f"{n.n['N.USSGA.infpip']['value']} MiB up to c = 100, one sync worker by less than 0.3 MiB, and 17 sync "
        f"workers hold {n.n['N.M17A']['value']} times the async peak USS. " + bar_note(vis, tot) +
        " Stream and pipeline: Figure FA (rows c).")

    # F6 CPU per request vs c, inference and stream
    fig, axs = plt.subplots(2, 1, figsize=(W_IN, 4.1), sharex=True, layout="constrained")
    b = Bars()
    cpu_panel(axs[0], n, "inf", b, title="inference")
    cpu_panel(axs[1], n, "str", b, title="stream (12 chunks per response)")
    axs[0].set_xlabel("")
    fig.legend(handles=legend_handles(), loc="outside lower center", ncol=3, handlelength=2.6, columnspacing=1.0)
    vis, tot = b.visible(fig)
    save(fig, d, "F6_cpu_per_request")
    cap["F6_cpu_per_request"] = (
        "Server CPU time per completed request versus concurrency (median of 5 runs), inference (top) and stream "
        "(bottom, simulator with 12 chunks per response). All configurations spend a few milliseconds per request; "
        f"at c = 100 FastAPI uses {n.v('CPUMS.inf.fastapi.c100'):.1f} and Tornado {n.v('CPUMS.inf.tornado.c100'):.1f} ms "
        f"per inference request, and a stream costs {n.v('CPUSI.fastapi.c100'):.1f} (FastAPI) and "
        f"{n.v('CPUSI.tornado.c100'):.1f} (Tornado) times an inference request. Low-concurrency values are noisy "
        "because CPU samples are quantised in 4 % steps. " + bar_note(vis, tot))

    # F4 validation. Real API: no error bar; the three per-run values are drawn as dots (top: run medians, bottom:
    # run p95s), read from final_real_per_run.csv and checked against the numbers.csv row of the bar (n = 3, min,
    # max, and mean = centre of the t-interval). Scaled simulator: bootstrap CI over runs as error bars.
    per_run = {}
    for r in read(os.path.join(ROOT, "analysis", "out", "final_real_per_run.csv")):
        if r["phase"] in ("A", "B") and r["framework"] == "fastapi":
            per_run.setdefault((r["phase"], int(r["concurrency"])), []).append(r)

    def run_values(ph, c, stn, idx):
        rows = sorted(per_run[(ph, c)], key=lambda r: int(r["run"]))
        xs = [float(r["latency_ms_median" if stn == "p50" else "latency_ms_p95"]) for r in rows]
        row = n.n[idx]
        mean = sum(xs) / len(xs)
        assert len(xs) == int(row["n_runs"]) == 3, idx
        assert abs(min(xs) - float(row["min"])) < 1e-6 and abs(max(xs) - float(row["max"])) < 1e-6, idx
        assert abs(mean - (float(row["ci_low"]) + float(row["ci_high"])) / 2) < 1e-3, idx
        return xs

    fig, axs = plt.subplots(2, 1, figsize=(W_IN, 3.7), sharex=True, layout="constrained")
    b = Bars()
    groups = [("A", "inference", 1), ("A", "inference", 25), ("B", "stream", 1), ("B", "stream", 25)]
    col = STYLE["fastapi"]["color"]
    for ax, stn, lab in ((axs[0], "p50", "median latency (s)"), (axs[1], "p95", "p95 latency (s)")):
        for k, (ph, ep, c) in enumerate(groups):
            idx = f"V{ph}.lat.{stn}.c{c}"
            ax.bar(k - 0.19, n.v(idx) / 1000, width=0.36, color=col, edgecolor=col, lw=0.8, zorder=2)
            ax.plot([k - 0.19 + dx for dx in (-0.09, 0.0, 0.09)], [x / 1000 for x in run_values(ph, c, stn, idx)],
                    ls="none", marker="o", ms=2.8, mfc="white", mec=INK, mew=0.6, zorder=4)
            idx = f"V{ph}.simsc.lat.{stn}.c{c}"
            v = n.v(idx) / 1000
            lo, hi = (x / 1000 for x in n.ci(idx))
            ax.bar(k + 0.19, v, width=0.36, color="white", edgecolor=col, lw=0.8, hatch="////", zorder=2)
            ax.errorbar([k + 0.19], [v], yerr=[[v - lo], [hi - v]], fmt="none", ecolor=INK, elinewidth=0.7,
                        capsize=1.8, capthick=0.7, zorder=3)
            b.add(ax, k + 0.19, lo, hi, 2.0)
        ax.set_ylabel(lab)
        ax.grid(axis="x", visible=False)
        ax.set_ylim(0, 10.5 if stn == "p95" else 4.6)
        # Fixed ticks (as rendered before the two-row legend shortened the axes and the auto locator changed them).
        ax.yaxis.set_major_locator(FixedLocator([0, 2, 4, 6, 8, 10] if stn == "p95" else [0, 1, 2, 3, 4]))
    axs[1].set_xticks(range(4))
    axs[1].set_xticklabels(["c = 1", "c = 25", "c = 1", "c = 25"])
    axs[1].text(0.5, -0.2, "inference (Phase A)", transform=axs[1].get_xaxis_transform(), ha="center", va="top",
                fontsize=8, color=INK)
    axs[1].text(2.5, -0.2, "stream (Phase B)", transform=axs[1].get_xaxis_transform(), ha="center", va="top",
                fontsize=8, color=INK)
    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, fc=col, ec=col, label="real API, 3 runs"),
                        plt.Line2D([], [], ls="none", marker="o", ms=2.8, mfc="white", mec=INK, mew=0.6,
                                   label="per run"),
                        plt.Rectangle((0, 0), 1, 1, fc="white", ec=col, hatch="////", label="simulator scaled, 5 runs")],
               loc="outside upper center", ncol=2, handlelength=1.4, columnspacing=1.0)  # 2 rows: 3 columns clip
    vis, tot = b.visible(fig)
    save(fig, d, "F4_validation")
    cap["F4_validation"] = (
        "Real API (FastAPI, 28 Sep 2026, 3 runs per level) versus the simulator scaled to today's service time "
        f"(x{n.v('VA.factor'):.4f} for inference, x{n.v('VB.factor'):.4f} for stream), at c = 1 and c = 25; top: median, "
        "bottom: p95 latency, pooled over the runs' requests. The scaled c = 1 medians are equal by construction "
        f"(the scale factor is defined from them); at c = 25 real / simulated median is {n.v('VA.sim4b.lat.p50'):.3f} "
        f"(inference) and {n.v('VB.sim4b.lat.p50'):.3f} (stream), while the deterministic simulator has no tail "
        f"(one real inference run at c = 25 has a p95 of {n.v('VA.maxrunp95'):,.0f} ms). Real API: the three per-run "
        "values (dots; top: run medians, bottom: run p95s); scaled simulator: 95 % bootstrap CI over runs (error "
        "bars); " + (
            f"{vis} of {tot} are longer than 2 pt." if vis else "all are shorter than 2 pt."))

    # F5 thesis vs v2
    items = [
        ("Async/sync throughput", "P.th.ratio", "RA1.inf.c100", "{:.0f}", "{:.1f}"),
        ("FastAPI throughput", "P.th.fastapiX", "X.inf.fastapi.c100", "{:.2f} req/s", "{:.2f} req/s"),
        ("Async latency", "P.th.asynclat", "P.asynclat", "{:,.0f} ms", "{:,.0f} ms"),
        ("FastAPI TTFT", "P.th.ttft.fastapi", "TTFT.str.fastapi.c100", "{:,.0f} ms", "{:.0f} ms"),
        ("Tornado TTFT", "P.th.ttft.tornado", "TTFT.str.tornado.c100", "{:,.0f} ms", "{:.0f} ms"),
        ("FastAPI Stage 2", "P.th.st2.fastapi", "ST2.fastapi.c100", "{:.0f} ms", "{:.1f} ms"),
        ("Tornado Stage 2", "P.th.st2.tornado", "ST2.tornado.c100", "{:.0f} ms", "{:.1f} ms"),
        ("Async/sync RSS, inference", "P.th.mem.inf", "MRSS.inf.c100", "{:.1f}x", "{:.2f}x"),
        ("Async/sync RSS, stream", "P.th.mem.str", "MRSS.str.c100", "{:.1f}x", "{:.2f}x"),
        ("FastAPI RSS, stream", "P.th.fastapiRSS", "RSSP.str.fastapi.c100", "{:.0f} MiB", "{:.0f} MiB"),
    ]
    fig, ax = plt.subplots(figsize=(W_IN, 3.6), layout="constrained")
    b = Bars()
    for k, (lab, th, v2, fth, fv2) in enumerate(items):
        y = len(items) - 1 - k
        t, v = n.v(th), n.v(v2)
        lo, hi = n.ci(v2)
        ax.barh(y + 0.19, t / v, height=0.36, color="#bdbcb5", edgecolor=INK2, lw=0.6, hatch="////", zorder=2)
        ax.barh(y - 0.19, 1.0, height=0.36, color=INK2, edgecolor=INK2, lw=0.6, zorder=2)
        ax.errorbar([1.0], [y - 0.19], xerr=[[1 - lo / v], [hi / v - 1]], fmt="none", ecolor="white", elinewidth=0.7,
                    capsize=1.2, zorder=3)
        (x0, _), (x1, _) = ax.transData.transform([(lo / v, 0), (hi / v, 0)])
        b.items.append((ax, None, lo / v, hi / v, None))
        # Both labels start right of the longer bar of the pair: next to its own bar, a label ran into the other bar.
        xl = max(t / v, 1.0) * 1.08
        ax.text(xl, y + 0.19, fth.format(t), va="center", ha="left", fontsize=7.5, color=INK)
        ax.text(xl, y - 0.19, fv2.format(v), va="center", ha="left", fontsize=7.5, color=INK)
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(FixedLocator([0.5, 1, 3, 10, 30]))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v_, _: f"{v_:g}"))
    ax.set_xlim(0.4, 60)
    ax.axvline(1, color=INK2, lw=0.6, zorder=1)
    ax.set_yticks(range(len(items)))
    ax.set_yticklabels([it[0] for it in items][::-1])
    ax.grid(axis="y", visible=False)
    # Centred under the whole figure: centred under the axes, the label ran past the right edge (clipped).
    fig.supxlabel("relative to v2 (v2 = 1, log scale)", fontsize=plt.rcParams["axes.labelsize"], color=INK)
    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, fc="#bdbcb5", ec=INK2, hatch="////", label="thesis (April 2026)"),
                        plt.Rectangle((0, 0), 1, 1, fc=INK2, ec=INK2, label="v2 (corrected harness)")],
               loc="outside upper center", ncol=2, handlelength=1.4, columnspacing=1.0)
    fig.canvas.draw()
    wmax = 0.0
    for _, _, lo_, hi_, _ in b.items:
        (x0, _), (x1, _) = ax.transData.transform([(lo_, 0), (hi_, 0)])
        wmax = max(wmax, abs(x1 - x0) / fig.dpi * 72)
    rel = [n.v(th) / n.v(v2) for _, th, v2, _, _ in items]
    under = sorted((1 - r) * 100 for r in rel[:2])
    over = (min(rel[2:]), max(rel[2:]))
    save(fig, d, "F5_pitfalls")
    cap["F5_pitfalls"] = (
        "Thesis headline numbers versus the corrected harness (v2), all at c = 100, normalised to v2 = 1 (log scale); labels give "
        f"the absolute values. The thesis understated async throughput by {under[0]:.0f} to {under[1]:.0f} % and "
        f"overstated async latency, first-token time, the Stage 2 sleep and async memory by {over[0]:.1f} to "
        f"{over[1]:.1f} times; the causes were a new API "
        "client per request, synchronised user bursts and memory carried between runs (Table T6). The v2 bars carry "
        f"their 95 % CI as a white error bar; the widest is {wmax:.1f} pt, i.e. "
        f"{'not visible' if wmax < 2 else 'visible'} at this size.")

    # FA appendix: stream and pipeline
    fig, axs = plt.subplots(4, 2, figsize=(7.0, 9.0), layout="constrained")
    b = Bars()
    for j, (ep, ea) in enumerate(EPS[1:]):
        throughput_panel(axs[0, j], n, ea, S[ea], b, title=f"(a) {ep}: throughput")
        latency_panel(axs[1, j], n, ea, b, title=f"(b) {ep}: mean latency, lines R = N/X")
        uss_panel(axs[2, j], n, ea, b, title=f"(c) {ep}: peak USS")
        cpu_panel(axs[3, j], n, ea, b, title=f"(d) {ep}: CPU per request")
    for ax in axs[:3].flat:
        ax.set_xlabel("")
    fig.legend(handles=legend_handles(), loc="outside lower center", ncol=6, handlelength=2.6)
    vis, tot = b.visible(fig)
    save(fig, d, "FA_stream_pipeline")
    cap["FA_stream_pipeline"] = (
        "Appendix (two-column width): stream (left) and pipeline (right) endpoints; rows (a) throughput with 1/S, "
        "17/S and c/S, (b) mean latency (sync: steady state) with R = N/X lines, (c) peak USS, (d) CPU per request. "
        f"S = {S['str']:.4f} s (stream) and {S['pip']:.4f} s (pipeline); the patterns of the inference endpoint hold "
        "on both. " + bar_note(vis, tot))

    with open(os.path.join(d, "captions.md"), "w", encoding="utf-8") as fh:
        fh.write("# Figure captions (drafts)\n\nGenerated by `venv/bin/python analysis/scripts/paper_figures.py` from "
                 "analysis/out/paper/numbers.csv; numbers in the captions are numbers.csv values. Files: "
                 "<name>.pdf (vector, Type 42 fonts) and <name>.png (300 dpi). Width 3.33 in (one ACM column) unless "
                 "noted. Colours (Okabe-Ito), markers and line styles are the same for each configuration in every "
                 "figure: Flask blue filled circle, Django sky-blue hollow square (one sync worker, solid line); "
                 "Flask 17w vermillion filled diamond, Django 17w orange hollow triangle (17 workers, dashed); FastAPI "
                 "green filled triangle, Tornado purple hollow pentagon (async, dash-dot).\n\n")
        for name in ("F1_throughput", "F2_latency", "F3_peak_uss", "F4_validation", "F5_pitfalls",
                     "F6_cpu_per_request", "FA_stream_pipeline"):
            text = cap[name]
            assert "\u2014" not in text and "\u2013" not in text
            fh.write(f"## {name}\n\n{text}\n\n")
    print(f"Saved figures and captions.md in {d}")


if __name__ == "__main__":
    main()
