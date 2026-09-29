"""
Claims-to-evidence map and LaTeX skeleton for the paper (read-only; no statistics computed here).

Every claim the paper will make is listed under its section and paragraph with the numbers.csv ids
(value and 95 % CI filled in from analysis/out/paper/numbers.csv), the tables and figures, and a status:
SUPPORTED, WEAK (with what is missing), INFERRED (reasoning, not measured), CITATION NEEDED or PLACEHOLDER.

Outputs: <paper dir>/CLAIMS_EVIDENCE.md (always rewritten)
         <paper dir>/main.tex and references.bib (only written if absent, or with --force; main.tex is meant to be
         edited by hand afterwards). main.tex holds one \\TODO line per planned paragraph.

Usage: venv/bin/python analysis/scripts/paper_claims.py [--paper-dir DIR] [--force]
"""

import argparse
import csv
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IN = os.path.join(ROOT, "analysis", "out", "paper")

S_, W_, I_, C_, P_ = "SUPPORTED", "WEAK", "INFERRED", "CITATION NEEDED", "PLACEHOLDER"

# (section number, title, label, [(paragraph id, paragraph plan, [(claim id, text, [ids], tables/figures, status, note)])])
OUTLINE = [
    ("A", "Abstract", None, [
        ("PA.1", "Problem, method and headline results in 150 to 200 words", [
            ("CA.1", "For LLM-API backends capacity is set by the execution model: at c = 100 async servers complete "
                     "about c times the requests of a single sync worker and c/17 times those of 17 sync workers.",
             ["RA1.inf.c100", "RA17.inf.c100"], "T2, F1", S_, ""),
            ("CA.2", "Within a class, frameworks differ only in memory and CPU, not in throughput or latency.",
             ["N.SC.X.fastapi_tornado", "N.SC.USSP.django_flask"], "T4", W_,
             "Flask vs Django CPU is not resolved (see C5.17); write 'differ in memory (and, for the async pair, CPU)'."),
            ("CA.3", "Common benchmarking pitfalls distorted the earlier results: 64x instead of 100x, Stage 2 644 ms "
                     "instead of 51 ms, async memory about 3x instead of 1.04 to 1.21x.",
             ["P.d.ratio", "ST2.fastapi.c100", "N.MRSS"], "T6, F5", S_, ""),
            ("CA.4", "A validation against the real API confirms the simulator's medians after rescaling the service "
                     "time, but not its tails.", ["VA.sim4b.lat.p50", "VB.sim4b.lat.p50", "VA.sim4b.lat.p95"], "T5, F4",
             W_, "median agreement has a CI of about +/- 11 % with 3 runs per level; say 'within about 10 %'."),
        ]),
    ]),
    ("1", "Introduction", "sec:intro", [
        ("P1.1", "Motivation: GenAI endpoints spend seconds waiting on an upstream LLM API; server choice decides "
                 "capacity", [
            ("C1.1", "An LLM API call takes seconds (S = 2.76 to 2.88 s simulated, 3.26 to 3.54 s real today) while the "
                     "server spends milliseconds of CPU per request.",
             ["M.S.inf", "M.S.pip", "VA.lat.p50.c1", "VB.lat.p50.c1", "CPUMS.inf.fastapi.c100", "CPUMS.str.fastapi.c100"],
             "T1, T4", S_, ""),
            ("C1.2", "Python services choose between WSGI sync workers and ASGI/async event loops; existing framework "
                     "benchmarks use CPU- or database-bound workloads.", [], "", C_,
             "needs the literature review (Section 3)."),
        ]),
        ("P1.2", "Approach: controlled comparison with a calibrated simulator; real API only for validation", [
            ("C1.3", "Four frameworks in six server configurations face identical upstream behaviour: 540 simulated runs "
                     "plus 24 real-API validation runs.", ["M.runs_sim", "M.runs_real"], "T1", S_, ""),
            ("C1.4", "Live APIs are not a stable reference: between April and September 2026 the same model became "
                     "slower and changed from 12 to about 92 stream chunks per response.",
             ["P.d.S", "VA.drift.lat", "VB.drift.chunks", "VB.chunks.p50.c1"], "T5, T6", W_,
             "'about 25 % slower' is the point value; the 95 % CI is 16 to 34 % (3 runs, two output modes). Write "
             "'16 to 34 % slower'. 'APIs differ between providers' is not measured here (one provider): cite."),
        ]),
        ("P1.3", "Findings and contributions", [
            ("C1.5", "Async throughput grows with concurrency (c/S); sync throughput is capped by the worker count "
                     "(1/S, 17/S).", ["N.SHA", "N.SH1", "N.SH17", "N.RA1.c100", "N.RA17.c100"], "T2, F1", S_,
             "simulated upstream; real API measured only at c = 25."),
            ("C1.6", "Within a class frameworks differ only in CPU and memory.",
             ["N.SC.X.django_flask", "N.SC.X.fastapi_tornado", "N.SC.USSP.django_flask", "N.SC.CPU.fastapi_tornado",
              "N.SC.CPU.django_flask"], "T4, F3, F6", W_,
             "true for memory in all pairs and CPU for FastAPI vs Tornado; Flask vs Django CPU is unresolved."),
            ("C1.7", "Benchmarking pitfalls distorted the thesis results (64x instead of 100x; Stage 2 644 instead of "
                     "51 ms; async memory 2.9x instead of 1.04 to 1.21x).",
             ["P.th.ratio", "RA1.inf.c100", "P.th.st2.fastapi", "ST2.fastapi.c100", "P.th.mem.inf", "N.MRSS"], "T6, F5", S_,
             "before/after numbers are measured; attributing each change to one artefact is INFERRED (C7.1)."),
            ("C1.8", "Contribution: a corrected, open harness and dataset.", ["M.runs_sim"], "", W_,
             "release of per-run CSVs and scripts is an open supervisor decision (RESULTS_FINAL 11.10)."),
        ]),
    ]),
    ("2", "Background", "sec:background", [
        ("P2.1", "WSGI vs ASGI execution models", [
            ("C2.1", "A WSGI sync worker serves one request at a time; an ASGI/asyncio event loop interleaves requests "
                     "that await I/O.", [], "", C_, "PEP 3333, ASGI specification, asyncio documentation."),
        ]),
        ("P2.2", "Closed-system model and the response-time law", [
            ("C2.2", "With N = c users and zero think time, X <= min(c, w)/S and the mean response time is R = N/X.",
             ["N.SSR1", "N.SSR17", "N.RTH"], "F2", S_, "theory needs a citation (for example Jain 1991, Lazowska et al. "
                                                       "1984); the data confirm it within 0.4 %."),
        ]),
        ("P2.3", "Censoring in a finite measurement window", [
            ("C2.3", "Requests that queue longer than the window never complete, so the measured percentiles of a "
                     "saturated sync server describe the window, not the queue.",
             ["N.TTFT1.c100", "N.TTFTD1.c100", "N.LR1.c100"], "T3", S_, ""),
        ]),
    ]),
    ("3", "Related work", "sec:related", [
        ("P3.1", "Python web framework benchmarks", [("C3.1", "Placeholder: framework benchmarks (for example "
                                                     "TechEmpower) and their workloads.", [], "", P_,
                                                     "literature review done separately.")]),
        ("P3.2", "LLM serving and API latency studies", [("C3.2", "Placeholder.", [], "", P_, "")]),
        ("P3.3", "Load-testing methodology (closed vs open loop, coordinated omission, warm-up, clocks)",
         [("C3.3", "Placeholder.", [], "", P_, "")]),
    ]),
    ("4", "Methodology", "sec:method", [
        ("P4.1", "Frameworks, servers and host", [
            ("C4.1", "Flask and Django on Gunicorn sync (1 or 17 workers), FastAPI on Uvicorn (asyncio, h11), Tornado; "
                     "one process each for async; versions and host in Table T1.", [], "T1", S_,
             "source: ~/paper_context/environment_snapshot.txt; one pip-freeze hash in all runs (RESULTS_FINAL 2.1)."),
        ]),
        ("P4.2", "Endpoints", [
            ("C4.2", "inference (one Messages call), stream (server-sent events, one event per upstream chunk), pipeline "
                     "(parse, retrieval with a 50 ms sleep, Messages call, format).", ["M.retrieval"], "T1", S_, ""),
        ]),
        ("P4.3", "Calibrated simulator and why it is used", [
            ("C4.3", "A deterministic Messages API simulator calibrated on the April real c = 1 data gives every "
                     "framework identical upstream behaviour.",
             ["M.S.inf", "M.S.str", "M.S.pip", "M.first_chunk", "M.chunk_gap", "M.chunks"], "T1", S_, ""),
            ("C4.4", "The live API is not a stable reference: service time and stream granularity changed between "
                     "April and September, and the API returns two output modes whose run medians differ by 12 to 14 %.",
             ["P.d.S", "VB.drift.chunks", "VB.drift.ttft", "VA.spread.c25", "VB.spread.c25"], "T5, T6", S_,
             "provider differences are not measured (one provider): cite if claimed."),
        ]),
        ("P4.4", "Harness controls", [
            ("C4.5", "One SDK client per process (no client per request).", [], "", S_,
             "test T2, 0 constructions per request (analysis/out/tests_ada7ab1.xml; PAPER_CONTEXT 9 F1, 10)."),
            ("C4.6", "Paced arrivals: the c first requests are spread over one S (no synchronised bursts).", [], "", S_,
             "PAPER_CONTEXT 5.3 and test T5 (0 empty seconds at c = 100)."),
            ("C4.7", "Server restarted for every run; idle memory recorded after warm-up.", ["M.idle_drift"], "", S_,
             "the 75 idle-drift flags are 17-worker runs with an 18-process sum (RESULTS_FINAL 2.5)."),
            ("C4.8", "Monotonic clock for all windows, host clock-rate and step guards; one run suspended by the host "
                     "was redone.", ["M.clock_min", "M.clock_max", "M.clock_step"], "T1", S_, "RESULTS_FINAL 2.3, 2.4."),
            ("C4.9", "5 runs per cell, 60 s each, 3 warm-ups, 250 ms resource sampling; 0 % errors.",
             ["M.runs_sim", "M.err", "M.err_real"], "T1", S_, ""),
        ]),
        ("P4.5", "Estimators and statistics", [
            ("C4.10", "Throughput is the completion rate in the steady window; 17 phase-locked workers need the cycle "
                      "estimator, because the completion rate reads up to 4 % high.", ["N.SH17", "N.SHR17", "N.SHF1"],
             "T2", S_, ""),
            ("C4.11", "Sync latency is the steady-state mean (requests started after t0 + ceil(c/w) S); where no such "
                      "request completes in 60 s, R = N/X is reported and the percentiles are marked censored.",
             ["N.SSR1", "N.LR1.c25"], "T3", S_, "rule text: RESULTS_FINAL 6.2."),
            ("C4.12", "Values are medians of 5 runs (real API: pooled over 3 runs) with 95 % CIs: t-interval over runs, "
                      "percentile bootstrap over runs for ratios (10,000 resamples).", [], "", S_,
             "analysis/scripts/paper_stats.py; NUMBERS.md."),
        ]),
    ]),
    ("5", "Results", "sec:results", [
        ("P5.1", "Capacity: one sync worker at 1/S, async at c/S, ratios at c = 100", [
            ("C5.1", "One sync worker (Flask, Django) saturates at 1/S at every c on all three endpoints.",
             ["N.X1.inf", "N.SH1"], "T2, F1, FA", S_, ""),
            ("C5.2", "Async servers (FastAPI, Tornado) follow c/S up to c = 100.",
             ["N.SHA", "N.XA100.inf", "N.XA100.str", "N.XA100.pip"], "T2, F1, FA", S_, "simulated upstream."),
            ("C5.3", "At c = 100 async completes c times as many requests as one sync worker.", ["N.RA1.c100"], "T2", S_, ""),
            ("C5.4", "The 0.3 to 0.5 % shortfall from the ceiling is the per-request overhead on top of S.",
             ["N.LA50.inf", "M.S.inf"], "T3", W_,
             "INFERRED from p50 2,887 to 2,890 ms vs S = 2,878 ms; no server-side timing breakdown measured."),
        ]),
        ("P5.2", "Latency: async flat at S; sync steady state equals R = N/X; censoring", [
            ("C5.6", "Async latency and TTFT stay at their c = 1 values up to c = 100.",
             ["N.LA50.inf", "N.TTFTA.c100", "N.TTFT.c1", "N.TPOT"], "T3, F2", S_, ""),
            ("C5.7", "The sync steady-state mean equals R = N/X; the full-window mean understates it by up to 24.7 % "
                     "(one worker) and 14.1 % (17 workers).",
             ["N.SSR1", "N.SSR17", "N.SSU1.c5", "N.SSU1.c10", "N.SSU17.c100"], "T3, F2", S_, ""),
            ("C5.8", "One sync worker at c >= 25: no steady-state request completes in 60 s; R = N/X is 69 to 289 s.",
             ["N.LR1.c25", "N.LR1.c100"], "T3, F2", S_, ""),
            ("C5.9", "Sync TTFT is queueing: 28.2 s measured (window-censored) vs 276.5 s steady state at c = 100; "
                     "17 workers 14.4 s.", ["N.TTFT1.c100", "N.TTFTD1.c100", "P.ttft.growth", "N.TTFT17.c100"], "T6", S_, ""),
            ("C5.10", "With phase-locked workers a request waits a whole number of rounds (17-worker p50 = 5.99 S at "
                      "c = 100).", ["L50.inf.flask17w.c100", "M.S.inf"], "T3", W_,
             "mechanism INFERRED; no per-request round analysis in numbers.csv."),
        ]),
        ("P5.3", "Resources: memory and CPU", [
            ("C5.11", "Memory: single-process servers idle at 43 to 50 MiB USS; async grows by 5 to 16 MiB up to "
                      "c = 100, one sync worker by less than 0.3 MiB; async / sync peak RSS is 1.04 to 1.21.",
             ["N.USSI1", "N.USSGA.infpip", "N.USSGA.str", "N.USSG1", "N.MRSS", "MUSS.str.c100"], "T4, F3", S_, ""),
            ("C5.12", "CPU: one sync worker uses 0.13 to 0.50 % of one core; async 17 to 59 % at c = 100; per request "
                      "all configurations spend 4 to 17 ms.", ["N.CPU1", "CPU.inf.tornado.c100", "CPU.str.fastapi.c100"],
             "T4, F6", S_, ""),
            ("C5.13", "A simulated stream (12 chunks) costs 2.7 to 2.9 times the CPU of an inference request.",
             ["CPUSI.fastapi.c100", "CPUSI.tornado.c100"], "T4, F6", S_, "depends on the chunk count (C8.3)."),
        ]),
        ("P5.4", "Same-class equivalence", [
            ("C5.14", "Within a class throughput and latency differ by at most 0.08 %; with the fixed run order this "
                      "supports no ranking.", ["N.SC.X.django_flask", "N.SC.X.fastapi_tornado", "N.SC.L50.django_flask",
                                                "N.SC.L50.fastapi_tornado"], "T2, T3", S_, "Threat C9.4."),
            ("C5.15", "Memory differences are robust: Django +17.7 to +18.3 % over Flask; FastAPI idle +10.3 to "
                      "+10.7 % over Tornado; Django 17w +18.8 to +20.2 % over Flask 17w.",
             ["N.SC.USSP.django_flask", "N.SC.USSI.fastapi_tornado", "N.SC.USSP.fastapi_tornado",
              "N.SC.USSP.django17w_flask17w"], "T4, F3", S_, "CI excludes 0 in every cell."),
            ("C5.16", "FastAPI uses more CPU than Tornado: +14.5 % at c = 100 and up to +178 % at c = 1 (inference).",
             ["SC.CPU.fastapi_tornado.inf.c100", "SC.CPU.fastapi_tornado.inf.c1", "N.SC.CPU.fastapi_tornado"], "T4, F6",
             S_, "resolved in 16 of 18 cells (not pipeline c = 10, 100); the c = 1 value is imprecise, quote c = 100."),
            ("C5.17", "Flask and Django differ in CPU.", ["N.SC.CPU.django_flask", "N.SC.CPUMS.django_flask"], "T4", W_,
             "NOT SUPPORTED: the CI includes 0 in 15 of 18 cells. State 'no resolved CPU difference'."),
            ("C5.18", "FastAPI's higher CPU at low c comes from Uvicorn's 0.1 s timer tick and access log.", [], "", W_,
             "INFERRED; no profiling was done."),
        ]),
        ("P5.5", "Multi-worker sync (17 Gunicorn workers)", [
            ("C5.19", "17 workers match one async process up to c = 10 (measured) and c = 17 (model).",
             ["N.RA17.le10", "N.SH17le10"], "T2, F1", W_, "no measurement between c = 10 and 25; c = 17 rests on the model."),
            ("C5.20", "Beyond 17 users throughput is capped at 17/S and latency grows as c S / 17.",
             ["N.SH17", "N.RTH", "N.R171.c100"], "T2, T3, F1, F2", S_, ""),
            ("C5.21", "The 17-worker deployment holds 10.8 to 16.8 times the async peak USS at similar CPU per request.",
             ["N.M17A", "CPUMS.inf.flask17w.c100", "CPUMS.inf.fastapi.c100"], "T4, F3", S_, ""),
            ("C5.22", "With a deterministic upstream the workers are phase-locked, which biases the completion rate by "
                      "up to 4 %.", ["N.SHR17", "N.SH17"], "T2", S_,
             "whether real upstream jitter breaks the phase lock is INFERRED (not measured)."),
        ]),
    ]),
    ("6", "Validation against the real API", "sec:validation", [
        ("P6.1", "Design: same harness; Phases A, B (FastAPI, c = 1, 25), C (four frameworks, c = 1, interleaved)", [
            ("C6.1", "24 real runs on 28 Sep 2026, 3 per level, 0 failures, 0 retries.", ["M.runs_real", "M.err_real"],
             "T5", S_, "retry scan: RESULTS_FINAL 2.2."),
        ]),
        ("P6.2", "Service-time drift", [
            ("C6.2", "The real inference service time today is 26 % above April.",
             ["VA.lat.p50.c1", "VA.thesis.lat.p50", "P.d.S", "VA.drift.lat"], "T5, T6", W_,
             "95 % CI 16 to 34 % with 3 runs; write the range. More runs per level (RESULTS_FINAL 11.7) would narrow it."),
        ]),
        ("P6.3", "Load independence and throughput at c = 25", [
            ("C6.3", "The real API shows no load effect at c = 25 (latency, TTFT and TPOT ratios c = 25 / c = 1 near 1).",
             ["VA.load.lat.p50", "VB.load.lat.p50", "VB.load.ttft.p50", "VB.load.tpot.p50"], "T5", W_,
             "CI of the latency ratios admits about +/- 10 to 12 %; only FastAPI, 3 runs per level. Within-mode ratios "
             "(0.969 to 1.009) help; 5 runs per level or a Tornado arm would strengthen it."),
            ("C6.4", "Real throughput at c = 25 follows 25 / S_today.", ["VA.share.c25", "VB.share.c25"], "T5", W_,
             "CI 0.89 to 1.09 because S_today itself is uncertain."),
        ]),
        ("P6.4", "Simulator fidelity", [
            ("C6.5", "After rescaling S, the simulator matches the real median latency and throughput share at c = 25.",
             ["VA.sim4b.lat.p50", "VB.sim4b.lat.p50", "VA.simshare.c25", "VB.simshare.c25"], "T5, F4", S_,
             "at the median, within about 11 % (CI driven by the real side)."),
            ("C6.6", "It does not reproduce tails, TTFT, TPOT or chunk counts.",
             ["VA.sim4b.lat.p95", "VB.sim4b.ttft.p50", "VB.drift.tpot", "VB.drift.chunks"], "T5, F4", S_, ""),
        ]),
        ("P6.5", "Streaming granularity changed", [
            ("C6.7", "The API now streams about 92 chunks 27 ms apart instead of 12 chunks 203 ms apart.",
             ["VB.chunks.p50.c1", "VB.thesis.chunks.p50", "VB.tpot.p50.c1", "VB.thesis.tpot.p50", "VB.drift.chunks"], "T5",
             S_, ""),
        ]),
        ("P6.6", "Phase C: per-framework TTFT and sync streaming", [
            ("C6.8", "The April per-framework TTFT spread (187 ms) was API drift between measurement blocks: "
                     "interleaved, the spread is 22 ms.",
             ["VC.spread.ttft.april", "VC.spread.ttft.today", "VC.perm.today", "VC.perm.april", "P.d.spread"], "T5, T6",
             W_, "the shrinkage is SUPPORTED; 'no framework effect' is not: effects up to about 55 ms are not excluded "
                 "(3 runs per framework)."),
            ("C6.9", "Sync servers forward about 100 chunks per stream with the same TPOT as async and about 30 % less "
                     "CPU per stream.", ["VC.flask.tpot.today", "VC.tornado.tpot.today", "VC.ratio.cpums"], "T5", S_,
             "3 runs per framework; ratio CI 0.64 to 0.81."),
        ]),
        ("P6.7", "Two output modes", [
            ("C6.10", "The API returned two output modes whose per-run medians differ by 12 to 14 %.",
             ["VA.spread.c1", "VA.spread.c25", "VB.spread.c1", "VB.spread.c25"], "", S_,
             "the cause (for example different replicas) is INFERRED."),
        ]),
    ]),
    ("7", "Measurement pitfalls", "sec:pitfalls", [
        ("P7.1", "Per-request API client and synchronised bursts", [
            ("C7.1", "Creating an API client per request and starting all users at once understated async throughput "
                     "and overstated async latency, TTFT and the Stage 2 sleep.",
             ["P.d.ratio", "P.d.fastapiX", "P.d.asynclat", "P.d.ttft.fastapi", "P.d.ttft.tornado", "P.d.st2.fastapi",
              "P.d.st2.tornado"], "T6, F5", W_,
             "before/after differences are measured; the split between the two artefacts is INFERRED (no ablation "
             "that fixes one artefact at a time)."),
        ]),
        ("P7.2", "Memory carried over between runs and live clients", [
            ("C7.2", "Without a restart per run, memory accumulated and async memory looked 2.9 to 4.5 times sync.",
             ["P.d.mem.inf", "P.d.mem.str", "P.d.fastapiRSS"], "T6, F5", W_, "attribution INFERRED, as C7.1."),
        ]),
        ("P7.3", "Window censoring", [
            ("C7.3", "The thesis sync TTFT (28 s) matches v2 only because both are cut by the 60 s window; the steady "
                     "state is 9.8 times longer, and full-window means understate by up to 24.7 %.",
             ["P.d.ttft.flask", "P.d.ttft.django", "P.ttft.growth", "N.SSU1.c10"], "T3, T6", S_, ""),
        ]),
        ("P7.4", "Estimator bias", [
            ("C7.4", "Fixed-window throughput reads 1 to 3 % high for one sync worker, the completion rate up to 4 % "
                     "high for phase-locked workers, and the async / sync ratio at c = 100 falls to 98.4 with the "
                     "fixed window.", ["N.SHF1", "N.SHR17", "RA1F.inf.c100"], "T2", S_, ""),
        ]),
        ("P7.5", "Measurement order confounded with the framework", [
            ("C7.5", "Measuring each framework in its own time block turned API drift into an apparent framework "
                     "difference.", ["P.d.spread", "VC.spread.ttft.april"], "T6", S_, "see C6.8 for the limits."),
        ]),
        ("P7.6", "Composite score dropped", [
            ("C7.6", "The thesis composite score is not reported: its within-class inputs differ by at most 0.08 %, "
                     "which min-max normalisation stretches to the full 0 to 1 range.", ["N.SC.X.fastapi_tornado"], "",
             I_, "not recomputed (RESULTS_FINAL 8)."),
        ]),
    ]),
    ("8", "Discussion", "sec:discussion", [
        ("P8.1", "Practical guidance", [
            ("C8.1", "For LLM-API backends provision concurrency, not CPU: one async process served c = 100 at 17 to "
                     "59 % of one core (12 chunks), while a sync deployment needs about c workers at 40 to 50 MiB each.",
             ["CPU.inf.tornado.c100", "CPU.str.fastapi.c100", "N.M17A", "N.USSI1"], "T4", S_,
             "simulated upstream with 12 chunks; see C8.3."),
            ("C8.2", "Within a class, choose on memory, CPU and ecosystem, not throughput.",
             ["N.SC.X.fastapi_tornado", "N.SC.USSP.django_flask"], "T4", S_, ""),
        ]),
        ("P8.2", "Streaming cost depends on the provider's chunk count", [
            ("C8.3", "The real stream (about 92 chunks) cost 2.7 times the CPU per request of the simulated stream "
                     "(12 chunks) at c = 25.",
             ["D.real.cpu.c25", "D.real.cpums.c25", "CPU.str.fastapi.c25", "CPUMS.str.fastapi.c25", "D.ratio.cpums.c25"],
             "T5", S_, "FastAPI only; report streaming CPU as a function of chunk count."),
            ("C8.4", "With about 92 chunks one async process would exceed one core at c = 100.",
             ["D.m1.fastapi.c100", "D.m2.fastapi.c100", "D.m2.tornado.c100", "D.m1.check.c25"], "", W_,
             "projection only (INFERRED): Method 1 overpredicts the c = 25 measurement 2.3x; the CIs cover input spread, "
             "not model error; at c = 50 the methods disagree (91 vs 201 % for FastAPI). Needs the 92-chunk simulator "
             "arm or real runs at c = 50 and 100."),
        ]),
        ("P8.3", "Recommendations for benchmarking GenAI backends", [
            ("C8.5", "Reuse clients, pace arrivals, restart per run, use monotonic clocks, report steady state or "
                     "R = N/X, and use a period-aligned estimator for phase-locked workers.", [], "T6", S_,
             "follows from Section 7."),
        ]),
    ]),
    ("9", "Threats to validity", "sec:threats", [
        ("P9.1", "Deterministic simulator", [
            ("C9.1", "Simulated p95 / p50 is at most 1.003; real is 1.12 to 1.22 at c = 25.",
             ["N.TAILsim", "VA.tail.c25", "VB.tail.c25"], "F4", S_, ""),
        ]),
        ("P9.2", "Real-API scope", [
            ("C9.2", "Real load only for FastAPI at c = 25, 3 runs per level; no real runs at c = 50, 100.",
             ["M.runs_real", "VA.maxrunp95"], "T5", S_, ""),
        ]),
        ("P9.3", "Single host, WSL2, clocks", [
            ("C9.3", "Generator, simulator and server share 8 vCPUs of one laptop under WSL2; clock rate within "
                     "1 +/- 0.00025.", ["M.clock_min", "M.clock_max", "M.clock_step"], "T1", S_, ""),
        ]),
        ("P9.4", "Fixed run order", [
            ("C9.4", "Frameworks ran in fixed blocks (only Phase C interleaved), so host drift is confounded with the "
                     "framework for differences below 0.1 %.", ["N.SC.X.fastapi_tornado"], "", S_, "PAPER_CONTEXT 15."),
        ]),
        ("P9.5", "Measurement resolution", [
            ("C9.5", "CPU samples are quantised in 4 % steps; the 17-worker monitor used 5 to 6 % of one core; USS "
                     "is summed over 18 processes.", ["M.cpu_step", "M.mon17", "M.idle_drift"], "T4", S_, ""),
        ]),
        ("P9.6", "Window length and statistics", [
            ("C9.6", "The 60 s window censors one sync worker at c >= 25; 5 runs per cell (3 real) give wide CIs for "
                     "the real-API values.", ["N.LR1.c25", "VA.lat.p50.c1"], "T3, T5", S_, ""),
        ]),
    ]),
    ("10", "Conclusion", "sec:conclusion", [
        ("P10.1", "Summary of the capacity, resource and pitfall results", [
            ("C10.1", "Restates C1.5 to C1.7 with their numbers.", ["N.RA1.c100", "N.RA17.c100", "N.MRSS"], "", S_,
             "use the Abstract wording."),
        ]),
        ("P10.2", "Future work", [
            ("C10.2", "92-chunk simulator arm; real runs at c = 50, 100 and with Tornado; a second provider.", [], "", I_,
             "open decisions RESULTS_FINAL 11."),
        ]),
    ]),
]

FIGS = [("F1_throughput", "fig:throughput", "5.1"), ("F2_latency", "fig:latency", "5.2"),
        ("F3_peak_uss", "fig:uss", "5.3"), ("F6_cpu_per_request", "fig:cpu", "5.3"),
        ("F4_validation", "fig:validation", "6"), ("F5_pitfalls", "fig:pitfalls", "7")]
TABS = {"4": ["t1_setup"], "5.1": ["t2_throughput"], "5.2": ["t3_latency"], "5.3": ["t4_resources"],
        "6": ["t5_validation"], "7": ["t6_thesis_vs_v2"]}


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def tex(s):
    s = s.replace("\\", r"\textbackslash{}")
    for a, b in (("&", r"\&"), ("%", r"\%"), ("#", r"\#"), ("_", r"\_"), ("$", r"\$"), ("~", r"\~{}"),
                 ("^", r"\^{}"), (">=", r"$\ge$"), ("<=", r"$\le$"), ("+/-", r"$\pm$")):
        s = s.replace(a, b)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper-dir", default=os.path.expanduser("~/paper_context/paper"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    nums = {r["id"]: r for r in read(os.path.join(IN, "numbers.csv"))}
    meta = {r["id"]: r for r in read(os.path.join(IN, "numbers_meta.csv"))}

    def val(i):
        r, nd = nums[i], int(meta[i]["decimals"])
        u = {"fraction": "", "ratio": "", "x": "x", "p": "(p)"}.get(r["unit"], r["unit"])
        try:
            v = f"{float(r['value']):,.{nd}f}"
        except ValueError:
            v = r["value"]
        ci = f" [{float(r['ci_low']):,.{nd}f}, {float(r['ci_high']):,.{nd}f}]" if r["ci_low"] else ""
        return f"{i}: {v}{(' ' + u) if u else ''}{ci}"

    missing = [i for _, _, _, ps in OUTLINE for _, _, cs in ps for c in cs for i in c[2] if i not in nums]
    assert not missing, missing

    # ---------------- CLAIMS_EVIDENCE.md
    L = ["# CLAIMS_EVIDENCE: every planned claim, its evidence and its status\n",
         "Generated by `venv/bin/python analysis/scripts/paper_claims.py` from analysis/out/paper/numbers.csv "
         "(values: RESULTS_FINAL estimators; [..] = 95 % CI, see NUMBERS.md for methods). Status: SUPPORTED = the "
         "numbers carry the claim as worded; WEAK = the claim needs rewording or more data (what is missing is "
         "stated); INFERRED = reasoning, not measured; CITATION NEEDED; PLACEHOLDER = related work, done "
         "separately. Tables T1 to T6 and figures F1 to F6, FA are in tables/ and figures/.\n"]
    weak = [(c[0], c[1], c[5]) for _, _, _, ps in OUTLINE for _, _, cs in ps for c in cs if c[4] == W_]
    L.append(f"## WEAK claims ({len(weak)})\n")
    L.append("| claim | statement | what is missing or how to reword |")
    L.append("|---|---|---|")
    for cid, t, note in weak:
        L.append(f"| {cid} | {t} | {note} |")
    L.append("")
    for sec, title, _lab, ps in OUTLINE:
        L.append(f"## {sec} {title}\n")
        for pid, plan, cs in ps:
            L.append(f"**{pid}** {plan}\n")
            L.append("| claim | statement | evidence (numbers.csv id: value [95 % CI]) | tables, figures | status | note |")
            L.append("|---|---|---|---|---|---|")
            for cid, t, ids, tf, st, note in cs:
                ev = "; ".join(val(i) for i in ids) if ids else "none (see note)"
                L.append(f"| {cid} | {t} | {ev} | {tf} | {st} | {note} |")
            L.append("")
    text = "\n".join(L) + "\n"
    assert "\u2014" not in text and "\u2013" not in text
    os.makedirs(a.paper_dir, exist_ok=True)
    with open(os.path.join(a.paper_dir, "CLAIMS_EVIDENCE.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"Saved CLAIMS_EVIDENCE.md: {sum(len(cs) for _, _, _, ps in OUTLINE for _, _, cs in ps)} claims, "
          f"{len(weak)} WEAK")

    # ---------------- main.tex skeleton
    main_tex = os.path.join(a.paper_dir, "main.tex")
    if os.path.exists(main_tex) and not a.force:
        print("main.tex exists; not overwritten (use --force)")
        return
    caps = {}
    cm = open(os.path.join(a.paper_dir, "figures", "captions.md"), encoding="utf-8").read()
    for m in re.finditer(r"^## (\S+)\n\n(.+?)\n", cm, re.M):
        caps[m.group(1)] = m.group(2)

    def fig(name, label, star=False):
        env = "figure*" if star else "figure"
        width = r"\textwidth" if star else r"\columnwidth"
        return [rf"\begin{{{env}}}", r"  \centering", rf"  \includegraphics[width={width}]{{figures/{name}}}",
                rf"  \caption{{{tex(caps[name])}}}", rf"  \label{{{label}}}", rf"\end{{{env}}}", ""]

    T = [r"\documentclass[sigconf,review=false]{acmart}",
         r"% Skeleton generated by analysis/scripts/paper_claims.py; edit by hand. For arXiv, switch to [manuscript].",
         r"% Numbers: NUMBERS.md; claims and their status: CLAIMS_EVIDENCE.md. Tables and figures are generated",
         r"% (analysis/scripts/paper_tables.py, paper_figures.py); do not edit them by hand.",
         r"\setcopyright{none}",
         r"\settopmatter{printacmref=false}",
         r"\renewcommand\footnotetextcopyrightpermission[1]{}",
         r"\newcommand{\TODO}[1]{\textcolor{red}{\textbf{TODO:} #1}}",
         "",
         r"\begin{document}",
         "",
         r"\title{Benchmarking Python Web Frameworks under Generative AI Workloads: A Comparison of Synchronous and "
         r"Asynchronous Architectures}",
         "",
         r"\author{Sanidhya Thakur}",
         r"\affiliation{%",
         r"  \institution{Riga Technical University}",
         r"  \city{Riga}",
         r"  \country{Latvia}}",
         r"% \email{} (not given)",
         "",
         r"\author{Padmaraj Nidagundi}",
         r"\affiliation{%",
         r"  \institution{Riga Technical University}",
         r"  \city{Riga}",
         r"  \country{Latvia}}",
         r"% \email{} (not given)",
         "",
         r"\begin{abstract}"]
    for pid, plan, cs in OUTLINE[0][3]:
        T.append(rf"\TODO{{{pid}: {tex(plan)} ({', '.join(c[0] for c in cs)}).}}")
    T += [r"\end{abstract}", "", r"\keywords{TODO}", "", r"\maketitle", ""]
    placed = set()
    for sec, title, lab, ps in OUTLINE[1:]:
        T.append(rf"\section{{{title}}}")
        T.append(rf"\label{{{lab}}}")
        T.append("")
        for pid, plan, cs in ps:
            sub = pid[1:]
            if sec == "5":
                subtitle = {"5.1": "Capacity", "5.2": "Latency", "5.3": "Resources", "5.4": "Same-class equivalence",
                            "5.5": "Multi-worker sync servers"}[sub]
                T.append(rf"\subsection{{{subtitle}}}")
                T.append(rf"\label{{sec:{subtitle.split()[0].lower().replace('-', '')}}}")
                T.append("")
            refs = ", ".join(c[0] for c in cs)
            T.append(rf"\TODO{{{pid}: {tex(plan)}. Claims {refs}; see CLAIMS\_EVIDENCE.md.}}")
            T.append("")
            key = sub if sec == "5" else sec
            for t in TABS.get(key, []):
                if t not in placed:
                    T.append(rf"\input{{tables/{t}}}")
                    T.append("")
                    placed.add(t)
            for name, label, where in FIGS:
                if where == key and name not in placed:
                    T += fig(name, label)
                    placed.add(name)
    T += [r"\begin{acks}", r"\TODO{Acknowledgements.}", r"\end{acks}", "",
          r"\bibliographystyle{ACM-Reference-Format}", r"\bibliography{references}", "",
          r"\appendix", r"\section{Additional results}", r"\label{sec:appendix}", "",
          r"\input{tables/t3b_latency_stream_pipeline}", ""]
    T += fig("FA_stream_pipeline", "fig:appendix", star=True)
    T += [r"\end{document}", ""]
    text = "\n".join(T)
    assert "\u2014" not in text and "\u2013" not in text
    with open(main_tex, "w", encoding="utf-8") as fh:
        fh.write(text)
    bib = os.path.join(a.paper_dir, "references.bib")
    if not os.path.exists(bib) or a.force:
        open(bib, "w").close()
    print(f"Saved {main_tex} and references.bib")


if __name__ == "__main__":
    main()
