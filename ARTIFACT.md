# Research artifact, v2.1

This repository contains the benchmark code, raw measurements, aggregate data,
analysis scripts and a snapshot of the table sources checked against the
JISA manuscript prepared on 26 October 2026 from the checked 23 October baseline by Sanidhya Thakur and Padmaraj Nidagundi:
*Benchmarking Python Web Frameworks under Generative AI Workloads: A Comparison
of Synchronous and Asynchronous Architectures*.

The manuscript is unpublished. This artifact is software and supporting data;
it is not a journal publication or an arXiv preprint. The complete manuscript
is not included in this release.

## Check the manuscript tables without rerunning experiments

The check needs Python and its standard library only. Python 3.12.3 was used
for the experiments; the release verification report records the interpreter
used for the archival check. No web server, API key, paid API call, package
installation or LaTeX installation is needed for this check.

From a fresh checkout or extracted release archive, run:

```sh
python analysis/scripts/paper_tables_check.py
```

Use `python3` instead of `python` if that is your interpreter's command.
The default input is `paper_snapshot/tables/`, resolved from the script's
location. The command also works when called by absolute path from another
working directory. For an external manuscript copy use:

```sh
python analysis/scripts/paper_tables_check.py --paper-dir /path/to/manuscript
```

Expected final line for the checked-in snapshot:

```text
total: 123 body rows, 854 numbers compared; 0 problems
```

The checker compares the numerical body cells in the table files `t2_throughput.tex` through `t6_thesis_vs_v2.tex` with tables
generated from `analysis/out/paper_v2.1/numbers.csv`. It also checks the
Table 6 steady-state TTFT-growth footnote. The latency table's panels are
matched against the generator's corresponding tables. Header labels, layout,
most captions, `t0_frameworks.tex` and `t1_setup.tex`, figures and manuscript prose are outside this
check. The script returns a nonzero exit status when a comparison fails.

This proves agreement with the archived aggregate numbers, not that every
statistical method, experiment or manuscript citation is independently
validated. It does not rerun the benchmark or regenerate the aggregates.

## Contents and provenance

| Path | Role |
|---|---|
| `paper_snapshot/tables/` | Exact table files from the checked 23 October manuscript |
| `paper_snapshot/manifest.json` | SHA-256 hashes of the source snapshot and data used by the check |
| `analysis/out/paper_v2.1/numbers.csv` | Aggregate numbers consumed by the table generator |
| `analysis/out/paper_v2.1/numbers_meta.csv` | Numerical provenance metadata |
| `analysis/scripts/paper_tables.py` | Generates comparison tables from the aggregate numbers |
| `analysis/scripts/paper_tables_check.py` | Compares the checked-in snapshot with those numbers |
| `data_v2/`, `data_v2_real/` | Corrected simulator and live-API measurements |
| `results_v2/` | Corrected aggregate results |
| `data/`, `results/` | Historical thesis data and outputs, superseded for the article's corrected results |
| `environment.txt` | Recorded experimental Python package versions |
| `HASH_MAP.md` | Mapping of recorded experiment commit IDs after a message-only history rewrite |

The preceding public main commit was
`455b1290f032c04f0e4d0e2db3bc68ab3842eca0`. This release adds packaging,
table snapshots, documentation and metadata; it does not replace raw runs or
change the numerical analysis/generation logic. The checker change is its
portable default input path and command help.

For full benchmark setup and optional experiment reproduction, see
[README.md](README.md). Those operations have different dependencies and
runtime requirements. They are not required to inspect the archived results.
Live-API experiments incur provider charges and are not part of the table check.

## Licences and citation

Source code and documentation remain MIT licensed. Measurement data, analysis
outputs and the table snapshot are CC BY 4.0; see [LICENSE](LICENSE) and
[LICENSE-DATA](LICENSE-DATA).

The existing all-versions archive DOI is
[10.5281/zenodo.23062471](https://doi.org/10.5281/zenodo.23062471).
The v2.0 version DOI is
[10.5281/zenodo.23062472](https://doi.org/10.5281/zenodo.23062472).
Use the version DOI displayed on the actual v2.1 Zenodo record when citing
this release. No new DOI is invented or reused from v2.0 in these files.
