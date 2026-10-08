# PROVENANCE: analysis/out/paper_v2.1 (analysis v2.1, Step 7 Part 1)

Date: 8 Oct 2026. No new run, API call or measurement: every file here is recomputed from the raw data and
aggregates that the v2.0 release already holds.

## Scripts

Commit `065e4a9352bb2f565f00f90dbec04ad0017d717a` (8 Oct 2026, "Analysis v2.1: interval method per Step 7"),
on top of tag `v2.0` (`335d8cd4a08394d69d6e5e37f1d1a2f275d80aa8`).

| Output | Command (from the repository root) |
|---|---|
| numbers.csv, numbers_meta.csv | `venv/bin/python analysis/scripts/paper_stats.py` (10,000 resamples, seed 20260929 + crc32 of the id) |
| step7_stream_cpu.csv, step7_ranges.csv | `venv/bin/python analysis/scripts/paper_step7_extra.py` |
| paper NUMBERS.md, tables, figures | `paper_numbers_md.py`, `paper_tables.py`, `paper_figures.py` with `--paper-dir`; they read only numbers.csv, numbers_meta.csv and analysis/out/final_real_per_run.csv |

Check on 8 Oct 2026: a second run of paper_stats.py from the commit gave byte-identical numbers.csv and
numbers_meta.csv; paper_step7_extra.py and paper_figures.py (PNG files) also reproduced byte for byte.

## Outputs (SHA-256)

| File | SHA-256 |
|---|---|
| numbers.csv | 908781bf3be71dd936900ddbf67243955fa2bf7f579bdeec71642319121452a5 |
| numbers_meta.csv | 9c3043f8a25ab6fa77fac40c23f316c8ee367ac53f6fc8866a4d7e8dec743924 |
| step7_stream_cpu.csv | d193c9e1694b77a623affd88fbc3f064443cbe0f399d939996845052c5aa657f |
| step7_ranges.csv | e2bf45e2237fca1d7ff36b486218c7fb2bd6f008810998e418135c1d801425e9 |
| PROVENANCE_inputs.sha256 | 22c9157e2745b237e16c74d8f148199e89f3f5e63b291bc2b1a9c995b9269606 |

## Inputs

All 486 input files, each with its SHA-256, are listed in `PROVENANCE_inputs.sha256`
(check: `sha256sum -c analysis/out/paper_v2.1/PROVENANCE_inputs.sha256`). The list was recorded with a Python
audit hook on the files the scripts open. By tree: data_v2 385 (simulated runs), data_v2_real 66 (live API,
28 Sep 2026), data 25 (thesis runs, April 2026), analysis/out 6, results_v2 3, simulated_endpoint 1.
Every input is unchanged against tag v2.0 (`git diff v2.0` is empty for these paths). The aggregates:

| File | SHA-256 |
|---|---|
| results_v2/per_run_v2.csv | bbef92cb7defb602ee1a289c3b9bbceb516208f062a04ffda630836116887d8e |
| results_v2/validation_real_v2.csv | dc5f529ec6cf19947b45c3230abf52a64ea67df5a437266422ab4d0307cfa5c4 |
| results_v2/validation_real_v2_throughput.csv | 6d676d35845d583aaed0568aecf4c1844704abf859a42f084f958c766eba2f27 |
| simulated_endpoint/calibration_v2.json | a5b54888dc4b21650bb46a11e4804510b39e8f7dd795272284eaeee3cc22340e |
| analysis/out/final_mw.csv | 938f1fc564e6e2e762a5e091651a3843961660cbbadbdf421355f84809659361 |
| analysis/out/final_mw_ratio.csv | 82ef70e458d4dac3f54311f58f363b2e9ebb90f74732ec0a30cdf1fb4243e964 |
| analysis/out/final_phase_c.csv | e361e3dcd91836143f06bbea8f929ca51ba2189137b12e5e12aa919bdd42d2ac |
| analysis/out/final_real_per_run.csv | cbb903480920932b4adda1a404fa4c569171fbbca3b532ea0f954909f6d77bde |
| analysis/out/final_steady_state.csv | e50812217b2d7a4fdcfa65ec0c93199cf29ed8163a9d43f729c453e5f18c3f8d |
| analysis/out/final_stream_cpu.csv | 24097e640f4ba73a02986ce1d6bb0c51ef9168469057faf134648abd81d4c1f3 |

## What changed against v2.0

The v2.0 outputs stay in `analysis/out/paper/` and in the v2.0 release; they are not modified.
Point values: none changed (1,895 numbers, same ids). Intervals: 1,286 rows changed. The column `interval`
(new, last) names the kind of each interval:

- `os93.75`: one group of 5 runs, statistic = median of the per-run values; interval = [min, max] of the 5,
  a distribution-free 93.75 % confidence interval for the median (Le Boudec 2010, Theorem 2.1).
- `boot95`: pooled statistics and statistics that combine groups (ratios, differences); 95 % percentile
  bootstrap that resamples whole runs within each group and recomputes the same statistic. Rows with 3 runs
  in a group are flagged "approximate: 3 runs per group" in numbers_meta.csv and NUMBERS.md.
- `range3`: one group of 3 live-API runs; interval = range of the 3 per-run values, not a confidence interval.
- `none`: constants and the thesis differences of Table 6 (first panel).
- Range rows (`N.*`) give the envelope of their members' intervals and name the members' kinds.

The v2.0 method (t-interval over runs for one group, df 4 or 2) is no longer used.
