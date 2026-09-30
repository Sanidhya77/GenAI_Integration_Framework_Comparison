# Benchmarking Python Web Frameworks under Generative AI Workloads

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23062471.svg)](https://doi.org/10.5281/zenodo.23062471)

Code and data for the paper **"Benchmarking Python Web Frameworks under Generative AI Workloads: A Comparison of Synchronous and Asynchronous Architectures"** by Sanidhya Thakur and Padmaraj Nidagundi (Riga Technical University).

Licences: code under the MIT License ([LICENSE](LICENSE)); data and analysis outputs under CC BY 4.0 ([LICENSE-DATA](LICENSE-DATA)).

## What this is

A controlled benchmark of four Python web frameworks used as the web layer in front of a hosted LLM API:

| Framework | Execution model | Server |
|---|---|---|
| Flask 3.1.3 | synchronous (WSGI) | Gunicorn 25.3.0 sync, 1 worker, and 17 workers (2 x 8 vCPUs + 1) |
| Django 6.0.3 | synchronous (WSGI) | Gunicorn 25.3.0 sync, 1 worker, and 17 workers |
| FastAPI 0.135.3 | asynchronous (ASGI) | Uvicorn 0.42.0, one process |
| Tornado 6.5.5 | asynchronous (event loop) | built-in HTTP server, one process |

Every framework exposes the same three endpoints, with the shared logic in `common/`, so the framework and its server are the only variables:

- `POST /api/inference`: blocking request and response.
- `POST /api/inference/stream`: token streaming over Server-Sent Events (SSE).
- `POST /api/pipeline`: RAG-style pipeline in 4 stages (query analysis; keyword retrieval plus a 50 ms simulated vector-store delay; augmented inference; formatting).

Load comes from a closed-loop Locust generator with zero think time at 1, 5, 10, 25, 50 and 100 concurrent users. Each run lasts 60 s, and each configuration is run 5 times with a server restart and 3 warm-up requests per run. RSS, USS and CPU of the server process tree are sampled every 250 ms. The v2 data set holds 564 runs: the main matrix (4 frameworks x 3 endpoints x 6 levels x 5 runs = 360), the 17-worker Gunicorn arm (180) and a real-API validation (24).

## Why a simulator

The study compares frameworks, not LLM providers. The upstream is therefore an HTTP/SSE-level simulator of the Anthropic Messages API (`simulated_endpoint/simulator.py`), calibrated on real measurements (`simulated_endpoint/calibration_v2.json`): 2.878 s for an inference call; a stream of 12 chunks, the first after 557.3 ms and the rest 202.1 ms apart; 2.7115 s for the pipeline's model call. The unmodified Anthropic SDK reaches it through `base_url`, so the framework code path is the one used against the real API. The simulator is deterministic, so every framework faces identical upstream behaviour. Live provider APIs differ between providers and change over time: between April and September 2026 the real inference service time rose by 26.3 % (95 % CI 16.3 to 33.5 %) and a streamed response went from 12 to about 92 chunks.

A validation against the live API is included in `data_v2_real/`: FastAPI inference (Phase A) and streaming (Phase B) at 1 and 25 users, and streaming at 1 user for all four frameworks (Phase C).

## Key results

Value [95 % CI] as reported in the paper; S = calibrated service time of an endpoint.

- One synchronous worker saturates at 1/S: Flask inference at c = 100 reaches 0.3464 req/s [0.3463, 0.3464] (1/S = 0.3475 req/s), while FastAPI reaches 34.6309 req/s [34.6258, 34.6362] (c/S = 34.75 req/s).
- Async / one-worker sync throughput, inference, c = 100: 100.00 x [99.99, 100.02] (thesis: 64). Async / 17-worker sync: 5.883 x [5.882, 5.884] (theory 100 / 17 = 5.882).
- Within a class (Flask vs Django, FastAPI vs Tornado) throughput differs by at most 0.08 %; Django's peak USS is 17.7 to 18.3 % [17.6, 18.4] above Flask's.
- Async / one-worker sync peak RSS, inference, c = 100: 1.044 x [1.042, 1.046] (thesis: 2.9). Pipeline Stage 2 (a 50 ms sleep) p50, FastAPI, c = 100: 51.39 ms [51.37, 51.43] (thesis: 643.9 ms).
- In a 60 s run the full-window mean understates the one-worker steady-state latency at c = 10 by 23.6 to 24.7 % [23.5, 24.8].
- Real API (FastAPI inference): median latency at c = 25 / c = 1 = 1.001 [0.900, 1.093]. Real streaming at c = 25 costs 46.5 % of one core [43.0, 48.8], against 20.8 % with the 12-chunk simulator.

## Repository layout

| Path | Content |
|---|---|
| `common/` | shared logic: `config.py` (model, prompts, simulator URL, dummy simulator key), `anthropic_client.py` (SDK client singletons), `pipeline_service.py` (4 stages with timing), `retrieval.py` |
| `flask_app/`, `django_app/` | WSGI apps; `gunicorn_config.py` (1 worker) and `gunicorn_config_mw.py` (17 workers) |
| `fastapi_app/`, `tornado_app/` | asynchronous apps (`main.py`) |
| `simulated_endpoint/` | `simulator.py` (Messages API simulator, JSON and SSE, port 9000) and `calibration_v2.json` |
| `locust_tests/` | Locust users per endpoint; `request_log.py` (per-request log, in-flight requests at stop, paced first requests) |
| `monitoring/` | `resource_monitor_v2.py` (v2: 250 ms, RSS, USS, CPU, process tree); `resource_monitor.py` (v1) |
| `document_store/` | knowledge base searched by the pipeline |
| `scripts/run_matrix.py` | v2 orchestrator: restart, warm-up, monitors, Locust, `meta.json` provenance, clock checks, resume |
| `scripts/hostclock.py` | Windows host clock reference for the per-run clock-rate check |
| `scripts/calibrate_from_data.py` | derives `calibration_v2.json` from the thesis real-API data (no API calls) |
| `scripts/aggregate_v2.py` | per-run metrics and per-configuration medians -> `results_v2/` |
| `scripts/validate_sim.py`, `scripts/validate_real_v2.py` | simulator vs thesis real data; real-API validation analysis |
| `scripts/run_real_validation.py`, `.sh` | real-API validation driver (Phases A, B, C) |
| `scripts/run_config.sh`, `aggregate_data.py`, `calibrate_simulator.py` | v1 (thesis) orchestrator, aggregation and calibration |
| `tests/` | pytest suite (simulator contract, server paths, retry detection, clock, aggregation) |
| `analysis/scripts/` | `final_*.py` (full v2 analysis), `paper_*.py` (paper numbers with 95 % CIs, LaTeX tables, figures), audit scripts of the v1 harness (`p1` to `p12`, `ast_compare`, `common_load`, `v2_t5_bursts`, `v2_real_mode_proof`) |
| `analysis/CODE_AUDIT.md` | audit of the v1 harness that motivated v2 |
| `analysis/out/` | analysis outputs: CSV and Markdown tables, figures, `paper/numbers.csv`, test evidence |
| `data_v2/` | 540 simulated v2 runs: `<framework>/<endpoint>/c<N>_run<R>_*` for flask, django, fastapi, tornado, flask_mw, django_mw |
| `data_v2_real/` | 24 real-API runs: `fastapi/{inference,stream}/` (Phases A, B), `phase_c/<framework>/stream/` |
| `results_v2/` | aggregates: `per_run_v2.csv`, `summary_v2.csv`, `summary_v2_long.csv`, `clock_rate_summary.csv`, validation CSVs (`_prev_20260927/` = superseded pre-final aggregate) |
| `data/`, `results/` | thesis (v1) raw data and summaries, see [Thesis version (v1)](#thesis-version-v1) |
| `environment.txt` | pinned Python packages (`pip freeze`) |

Per run, `data_v2/` holds Locust CSVs (`_stats`, `_stats_history`, `_failures`, `_exceptions`), the per-request log (`_requests`, `_inflight`, `_locust_meta.json`), endpoint metrics (`_stream_metrics` or `_pipeline_metrics`), the server and simulator monitors (`_resources`, `_sim_monitor`), the server and Locust logs, and `_meta.json` (git SHA, calibration and pip-freeze hashes, commands, PIDs, clock and idle-memory checks).

## Environment

- Host: laptop with an Intel Core i5-12500H, Windows with a WSL2 VM (kernel 6.6.87.2-microsoft-standard-WSL2), 8 vCPUs, 7,942 MiB RAM, clocksource `tsc`. Load generator, simulator, monitors and server share the host.
- Python 3.12.3. Flask 3.1.3, Django 6.0.3, FastAPI 0.135.3 (Starlette 1.0.0), Tornado 6.5.5; Gunicorn 25.3.0, Uvicorn 0.42.0 (asyncio and h11; uvloop and httptools not installed); Locust 2.43.4 (gevent 25.9.1); httpx 0.28.1; anthropic 0.88.0; psutil 7.2.2; pytest 9.0.2; matplotlib 3.10.8 and numpy 2.4.4 for the figures. Full list: `environment.txt`.
- Model: `claude-haiku-4-5-20251001`, max_tokens 256, temperature 0.0. The code was run and tested with anthropic 0.88.0 only; keep the pinned versions.
- All 564 runs record the same git SHA, calibration sha256 and pip-freeze sha256. The recorded SHA is ada7ab1, which is 14f5663 (tag `v2-freeze`) after the message-only history rewrite of 30 Sep 2026; see [HASH_MAP.md](HASH_MAP.md).

### Clock requirement

`systemd-timesyncd` must be stopped and disabled during runs. Inside WSL2 its corrections conflict with the Hyper-V host time sync: the guest wall clock was stepped forward by about 0.6 to 0.9 s every 33 s, and the slewing made `CLOCK_MONOTONIC` run about 2 % slow. `time.monotonic()` and `time.perf_counter()` both read `CLOCK_MONOTONIC`, so every latency, window and rate would be distorted.

```bash
sudo systemctl stop systemd-timesyncd
sudo systemctl disable systemd-timesyncd
systemctl is-active systemd-timesyncd chronyd ntp   # expect "inactive" three times
# after the campaign
sudo systemctl enable --now systemd-timesyncd
```

Also disable host sleep for the campaign: a suspended host pauses the VM (one main-matrix run was interrupted by a power cut and redone).

How the harness enforces and checks this (all results go to each run's `_meta.json`):

- **Preflight.** `run_matrix.py` and `run_real_validation.py` refuse to start, and abort before a run, if `systemd-timesyncd`, `chronyd` or `ntp` is active (override `ALLOW_TIMESYNC=1`, not used for the paper data). They record the service states, the kernel clocksource and the apt-daily timers.
- **Clock step.** Both monitors (server and simulator) record `time.time() - time.monotonic()` at every sample, and the orchestrator records (wall, monotonic) anchors at run start and end. If this offset varies by more than 20 ms within a run, the run gets `clock_step_detected: true` and `clock_step_ms`.
- **Clock rate** (`scripts/hostclock.py`). The Windows host clock is read through the modification time of a file created on `/mnt/c/Users/Public` (best of 3 reads) right before Locust starts, at the midpoint of the run and right after Locust stops. `clock_rate_ratio` = guest monotonic time / host time over the run, with `clock_rate_uncertainty` and the ratios of the two halves. Flags: `clock_rate_unstable` if the half ratios differ by more than 0.005, `clock_rate_off_nominal` if the ratio differs from 1 by more than 0.002. A failed read records null and never aborts a run.
- **Redo.** `scripts/aggregate_v2.py --list-clock-steps` lists runs with any of the three flags; `scripts/run_matrix.py --redo-clock-steps` deletes and repeats them.
- **Paper data.** No run carries a flag; `clock_rate_ratio` lies between 0.999757 and 1.000261 over the 564 runs and the largest clock step is 0.315 ms, so all values are reported uncorrected.

## How to reproduce

Run everything from the repository root on Linux or WSL2 (the clock-rate check needs `/mnt/c`; elsewhere it records null). Ports 8000 and 9000 must be free.

### 1 Setup (minutes)

```bash
git clone https://github.com/Sanidhya77/GenAI_Integration_Framework_Comparison.git
cd GenAI_Integration_Framework_Comparison
python3.12 -m venv venv
venv/bin/pip install $(grep '==' environment.txt)   # environment.txt ends with two info lines, hence the grep
venv/bin/pip install matplotlib==3.10.8 numpy==2.4.4
venv/bin/python -m pytest -q tests/                # 27 tests, about 9 min; starts the simulator and servers
```

### 2 Calibration (optional, seconds)

The committed `simulated_endpoint/calibration_v2.json` (sha256 `a5b54888dc4b21650bb46a11e4804510b39e8f7dd795272284eaeee3cc22340e`) was used for all runs. To re-derive it from the thesis real-API runs at c = 1 in `data/` (no API calls):

```bash
venv/bin/python scripts/calibrate_from_data.py
git diff simulated_endpoint/calibration_v2.json
git checkout simulated_endpoint/calibration_v2.json
```

All values come out identical. Without the untracked thesis file `simulated_endpoint/calibration.json`, 4 provenance lines differ; restore the committed file afterwards, because `run_matrix.py` refuses to start with modified tracked files.

### 3 Main matrix (360 runs, about 11 h)

```bash
REST_MODE=short venv/bin/python scripts/run_matrix.py --estimate-only
REST_MODE=short nohup venv/bin/python scripts/run_matrix.py > run_main.log 2>&1 &
```

`REST_MODE=short` (30 s rests, used for the paper) is estimated at 10.8 h; the default thesis rests (3c + 30 s, 3c + 60 s) at 21.0 h. The paper's run took 11.4 h of wall time (2026-09-26 18:52 to 2026-09-27 06:17 UTC, including a 68 min host suspension). Output: `data_v2/`. The script is resumable (complete runs are skipped) and refuses to start with modified tracked files, busy ports or active time sync.

### 4 Multi-worker arm (180 runs, about 5.5 h)

```bash
MULTIWORKER=1 REST_MODE=short nohup venv/bin/python scripts/run_matrix.py > run_mw.log 2>&1 &
```

Estimated at 5.4 h (short rests) or 10.5 h (thesis rests); the paper's run took 5.2 h. Output: `data_v2/flask_mw/`, `data_v2/django_mw/`.

### 5 Real-API validation (optional, costs money, about 50 min)

This phase calls the real Anthropic API with model `claude-haiku-4-5-20251001` and is billed to your account. It needs `ANTHROPIC_API_KEY` in `.env` (ignored by git). At c = 25 the account must sustain about 540 requests/min and 138,000 output tokens/min. Check that the model has not been retired before you spend anything.

```bash
echo 'ANTHROPIC_API_KEY=<your key>' > .env
venv/bin/python scripts/run_real_validation.py --plan-only   # requests and cost per phase, no API contact
export $(cat .env | xargs)
ALLOW_REAL_API=1 REST_MODE=short PHASE=A ./scripts/run_real_validation.sh   # FastAPI inference, c = 1 and 25
ALLOW_REAL_API=1 REST_MODE=short PHASE=B ./scripts/run_real_validation.sh   # FastAPI stream, c = 1 and 25
ALLOW_REAL_API=1 REST_MODE=short PHASE=C ./scripts/run_real_validation.sh   # stream, c = 1, all frameworks
```

Estimated cost at $1 / $5 per million input / output tokens: Phase A about $2.26 (1,722 requests), Phase B about $2.34 (1,779), Phase C about $0.40 (307). The script refuses if the estimate exceeds `BUDGET_USD` (default 5.00) and asks for a typed "yes". Any retry, HTTP 429 or 5xx marks the run invalid and stops the phase. The paper's three phases ran on 2026-09-28 in about 50 min. Output: `data_v2_real/`.

### 6 Analysis (read-only on the data)

```bash
venv/bin/python scripts/aggregate_v2.py                   # -> results_v2/ (540 runs, 108 configurations)
venv/bin/python scripts/aggregate_v2.py --list-clock-steps
venv/bin/python scripts/validate_real_v2.py --phase all   # -> results_v2/validation_real_v2*.csv
venv/bin/python scripts/validate_sim.py                   # -> results_v2/validation_sim_vs_real.csv
for s in real mw steady_state stream_cpu integrity separation tables figures; do
  venv/bin/python analysis/scripts/final_$s.py            # -> analysis/out/ (CSV, final_tables.md, tables/, figures/)
done
```

The scripts only read the committed data (run time not recorded). They rewrite `results_v2/` and `analysis/out/` in place, so `git status` and `git diff` show any difference from the published outputs.

### 7 Paper numbers, tables and figures

```bash
venv/bin/python analysis/scripts/paper_stats.py                           # -> analysis/out/paper/numbers.csv (95 % CIs)
venv/bin/python analysis/scripts/paper_tables.py     --paper-dir /tmp/paper_out   # -> tables/t1_setup.tex ... t6_thesis_vs_v2.tex
venv/bin/python analysis/scripts/paper_figures.py    --paper-dir /tmp/paper_out   # -> figures/F1 ... F6, FA (.pdf, .png)
venv/bin/python analysis/scripts/paper_numbers_md.py --paper-dir /tmp/paper_out   # -> NUMBERS.md
```

Always pass `--paper-dir`: the default is the authors' local paper folder. Confidence intervals are t-intervals over runs or percentile bootstraps over runs (10,000 resamples, fixed seeds). Not needed for reproduction: `final_thesis_text.py` searches the thesis PDF, which is not in this repository, and `paper_claims.py` writes the authors' claims map and a LaTeX skeleton. Some v1 audit scripts read `logs/`, which is not published.

## Thesis version (v1)

The bachelor thesis "Comparative Analysis of Python-Based Web Frameworks for Efficient Integration of Generative AI Services" (Riga Technical University, Institute of Applied Computer Systems) used the v1 harness, tagged `thesis-v1`. **The thesis results are superseded.** Harness artefacts in v1 changed several headline numbers, as documented in the paper; for example, at c = 100 the async / one-worker sync throughput ratio was 64 in the thesis and is 100.00 in v2, the peak RSS ratio 2.9 and now 1.044, and FastAPI pipeline Stage 2 p50 643.9 ms and now 51.39 ms. `analysis/CODE_AUDIT.md` lists the artefacts: a new HTTP client per request in the simulated path, synchronised bursts of users, no server restart between runs (memory carried over), sync latency censored by the 60 s window, the done signal counted as a token and no first-token delay in the simulated stream.

v1 design, kept for reference:

- Same frameworks, servers (single-worker Gunicorn only) and endpoints as v2.
- Hybrid upstream: the live Anthropic API at c = 1, 5 and 10, and a simpler local simulator at c = 25, 50 and 100.
- 4 frameworks x 3 endpoints x 6 levels x 5 runs = 360 runs, raw data in `data/<framework>/<endpoint>/`.
- 13 metrics in 4 dimensions: latency and connection stability (TTFT, TPOT, total response time, connection success rate); concurrency scalability (throughput, p95/p99 latency, error rate); resource use (peak RSS, memory growth, CPU); pipeline coordination (end-to-end pipeline latency, stage timing, pipeline completion rate).
- Summaries in `results/`: `summary_locust_stats.csv` (request and latency statistics), `summary_pipeline_custom.csv` (pipeline timing), `summary_resources.csv` (CPU and memory), `summary_stream_custom.csv` (TTFT, TPOT), plus 10 charts; produced by `scripts/aggregate_data.py`. The thesis runs were driven by `scripts/run_config.sh`, monitored by `monitoring/resource_monitor.py` and calibrated by `scripts/calibrate_simulator.py`.

Manual v1 workflow (`git checkout thesis-v1`; the live-API levels need `ANTHROPIC_API_KEY` in `.env`):

```bash
source venv/bin/activate
export $(cat .env | xargs)

# start one server
gunicorn -c flask_app/gunicorn_config.py flask_app.app:app                        # Flask
(cd django_app && gunicorn -c gunicorn_config.py config.wsgi:application)         # Django
uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8000 --workers 1               # FastAPI
python tornado_app/main.py                                                        # Tornado

curl http://localhost:8000/health
locust -f locust_tests/test_inference.py --headless -u 1 -r 1 -t 60s \
  --host http://localhost:8000 --csv data/flask/inference/run1
python monitoring/resource_monitor.py --pid <SERVER_PID> --output data/flask/inference/run1_resources.csv
```

## How to cite

Please cite the paper, and the software and data record if you use the code or the data.

- Paper: Sanidhya Thakur and Padmaraj Nidagundi. *Benchmarking Python Web Frameworks under Generative AI Workloads: A Comparison of Synchronous and Asynchronous Architectures.* arXiv:TODO, 2026.
- Software and data: Sanidhya Thakur and Padmaraj Nidagundi. *Benchmarking Python Web Frameworks under Generative AI Workloads: benchmark code and data*, version 2.0. Zenodo, 2026. DOI: [10.5281/zenodo.23062472](https://doi.org/10.5281/zenodo.23062472). The concept DOI [10.5281/zenodo.23062471](https://doi.org/10.5281/zenodo.23062471) covers all versions and resolves to the latest one (the badge above).

```bibtex
@misc{thakur2026benchmarking,
  author        = {Thakur, Sanidhya and Nidagundi, Padmaraj},
  title         = {Benchmarking Python Web Frameworks under Generative AI Workloads: A Comparison of Synchronous and Asynchronous Architectures},
  year          = {2026},
  eprint        = {TODO},
  archivePrefix = {arXiv}
}

@software{thakur2026benchmarkcode,
  author    = {Thakur, Sanidhya and Nidagundi, Padmaraj},
  title     = {Benchmarking Python Web Frameworks under Generative AI Workloads: benchmark code and data},
  version   = {2.0},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.23062472},
  url       = {https://github.com/Sanidhya77/GenAI_Integration_Framework_Comparison}
}
```

`CITATION.cff` holds the same metadata (GitHub shows it as "Cite this repository").

## Licence

- Code (everything except the folders below): MIT License, see [LICENSE](LICENSE).
- Data and outputs in `data_v2/`, `data_v2_real/`, `results_v2/`, `analysis/out/`, `data/` and `results/`: Creative Commons Attribution 4.0 International (CC BY 4.0), see [LICENSE-DATA](LICENSE-DATA).
