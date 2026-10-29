# Checked JISA manuscript table snapshot

`tables/` contains the exact seven table source files used in the JISA manuscript
prepared on 26 October 2026 from the checked 23 October baseline. JISA layout,
parenthetical citation syntax and the qualitative Bottle description differ from
the earlier snapshot; experimental numerical values do not.

This is numerical-reproducibility material, not a complete or independently
compilable manuscript. The checker covers `t2_throughput.tex`, `t3_latency.tex`,
`t4_resources.tex`, `t5_validation.tex` and `t6_thesis_vs_v2.tex`, plus the final
file's steady-state TTFT-growth footnote. The framework-selection and setup table
files (`t0_frameworks.tex`, `t1_setup.tex`) are included for provenance but are
outside that numerical check. These filename numbers are not the rendered PDF's
table order. The checked total is 123 body rows and 854 numerical values.

The snapshot is CC BY 4.0; see `../LICENSE-DATA`. The manifest records exact
table, input-data and generator hashes. The main source, bibliography and PDF
are identified by hash only and are not included in this software/data artifact.
Their hashes identify this pre-release-citation manuscript copy; a later verified
DOI update will change its source and PDF hashes without changing these tables.

See `../ARTIFACT.md` for commands and validation limits. Hashes describe the
stored file bytes. If Windows changes LF endings to CRLF in a checkout, use Git
blob bytes or normalise only those line endings before checking the hashes.
