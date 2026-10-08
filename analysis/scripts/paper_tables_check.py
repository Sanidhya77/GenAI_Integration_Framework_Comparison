"""
Check the hand-edited paper tables against numbers.csv (Step 7, 8 Oct 2026; read-only).

The paper's table files t2 to t6 were edited by hand after 1 Oct 2026 (panels, columns, captions, typographic
minus), so paper_tables.py no longer reproduces their layout. This script renders the tables from
analysis/out/paper_v2.1/numbers.csv with paper_tables.py into a temporary folder and compares, row by row, every
number of every body row (values and both bounds of each bracket) with the paper's file. Rows are matched in
order after dropping header and panel-label rows; t3_latency in the paper holds the generator's t3 and t3b
panels; for t6 the generator's last (cause) column is ignored, because the paper dropped it. The caption
footnote of t6 (steady-state TTFT growth) is checked against its numbers.csv row.

Usage: venv/bin/python analysis/scripts/paper_tables_check.py [--paper-dir ~/paper_context/paper]
Exit status 0 when every row matches.
"""

import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NUM = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


def body_rows(path, drop_last_col=False):
    rows = []
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if s.startswith("%") or "&" not in s or s.startswith("\\multicolumn"):
            continue
        cells = [c.strip() for c in s.rstrip("\\").split("&")]
        if drop_last_col:
            cells = cells[:-1]
        txt = " & ".join(cells[1:]).replace("$-$", "-")
        txt = re.sub(r"\$\^\{?[^$]*\}?\$", "", txt)  # footnote marks
        txt = re.sub(r"\$[ck]=\d+\$", "", txt)
        if not NUM.search(txt):
            continue  # header row
        if cells[0].startswith(("Configuration", "Quantity", "Phase", "Phases")):
            continue
        rows.append((cells[0], NUM.findall(txt)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper-dir", default=os.path.expanduser("~/paper_context/paper"))
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="tables_check_")
    subprocess.run([sys.executable, os.path.join(ROOT, "analysis", "scripts", "paper_tables.py"), "--paper-dir", tmp],
                   check=True, stdout=subprocess.DEVNULL)
    gen = os.path.join(tmp, "tables")
    pairs = [("t2_throughput.tex", ["t2_throughput.tex"], False),
             ("t3_latency.tex", ["t3_latency.tex", "t3b_latency_stream_pipeline.tex"], False),
             ("t4_resources.tex", ["t4_resources.tex"], False),
             ("t5_validation.tex", ["t5_validation.tex"], False),
             ("t6_thesis_vs_v2.tex", ["t6_thesis_vs_v2.tex"], True)]
    bad = 0
    total_rows = total_nums = 0
    for paper, gens, drop in pairs:
        p = body_rows(os.path.join(a.paper_dir, "tables", paper))
        g = [r for f in gens for r in body_rows(os.path.join(gen, f), drop)]
        if len(p) != len(g):
            print(f"{paper}: {len(p)} body rows in the paper, {len(g)} generated")
            bad += 1
            continue
        nb = 0
        for (lp, vp), (lg, vg) in zip(p, g):
            total_rows += 1
            total_nums += len(vp)
            if vp != vg:
                nb += 1
                print(f"{paper}: row '{lp}' differs\n  paper:     {vp}\n  numbers.csv: {vg}")
        bad += nb
        print(f"{paper}: {len(p)} body rows, {sum(len(v) for _, v in p)} numbers, {nb} mismatches")
    # t6 caption footnote
    n = {r["id"]: r for r in csv.DictReader(open(os.path.join(ROOT, "analysis", "out", "paper_v2.1", "numbers.csv")))}
    cap = open(os.path.join(a.paper_dir, "tables", "t6_thesis_vs_v2.tex"), encoding="utf-8").read()
    m = re.search(r"steady-state TTFT is ([\d.]+) \[([\d.]+), ([\d.]+)\]", cap)
    r = n["P.ttft.growth"]
    want = [f"{float(r[k]):.1f}" for k in ("value", "ci_low", "ci_high")]
    ok = m is not None and list(m.groups()) == want
    print(f"t6 caption footnote P.ttft.growth: paper {m.groups() if m else None}, numbers.csv {want}: "
          f"{'match' if ok else 'MISMATCH'}")
    bad += 0 if ok else 1
    print(f"total: {total_rows} body rows, {total_nums} numbers compared; {bad} problems")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
