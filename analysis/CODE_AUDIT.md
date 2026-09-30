# Code, simulator and results audit

Scope: repository at HEAD 0fac7af, raw data in `data/`, server logs in `logs/`, local-only files, and installed packages in `venv/` (the environment that ran the experiment). Analysis only; no tracked file was modified, and no server, simulator, Locust run or API call was started.

Analysis scripts: `analysis/scripts/` (p1 to p12, plus `common_load.py`). Intermediate tables: `analysis/out/`. Two micro-benchmarks (p5, p10) construct httpx clients in-process with no network I/O. One (p11) writes only to the session scratch directory. Everything else only reads existing CSV/JSONL.

Status tags: CONFIRMED = shown directly by code or data. INFERRED = consistent with the evidence but not proven. UNVERIFIABLE = needs a new run or missing information.

Notation: c = concurrency, S = service time of the upstream (real API or simulator), X = per-request blocking cost of constructing an httpx client.

---

## 1. Executive summary

1. The async results at c >= 25 are dominated by a harness artefact (CONFIRMED). Every simulated call constructs a new httpx client, which costs about 15 to 20 ms of blocking SSL setup. The constant-delay simulator and simultaneous spawn lock requests into bursts of exactly c, so every request waits for the whole burst. Effects: latency +14 to 19 ms x c; throughput 85 / 74 / 63 % "of ideal"; Stage 2 at 190 / 373 / 644 ms; async TTFT 0.56 to 2.0 s.
2. Sync latency at c >= 25 is right-censored (CONFIRMED). Each run completes exactly 20 requests (24 for stream) and drops the c requests still in flight. The recorded 29 s medians and 56 to 59 s p95/p99 are set by the 60 s window. Steady-state latency would be c x S = 72 / 144 / 288 s.
3. Memory figures are carry-over high-water marks (CONFIRMED). One server process served many runs and configurations, idle RSS is about equal to peak, and Metric #9 (growth) is 0 in most cells. FastAPI's 332.2 MB is cumulative across all earlier simulated runs.
4. The simulated stream is wrong in two ways (CONFIRMED). The completion sentinel does not match, so token_count is always 13 and TPOT is 8 % low. The simulator has no first-token latency, so its stream lasts 2.4 s against 2.70 to 2.91 s on the real API, and sync stream throughput jumps 19 % at the c = 10 / 25 boundary.
5. Requests/s is measured from test start to the last completion, so the throughput ceiling is c / S for each endpoint (CONFIRMED). Little's law holds for async, so every async "loss" equals the latency inflation in item 1. Stream shares computed against 2.878 s exceed 100 %.
6. Server-side E2E pipeline latency (Metric #11) excludes queueing (CONFIRMED). Sync 2.95 s vs async 4.3 s at c = 100 is not a valid comparison: client-side, the sync requests took about 30 s, and that figure is itself censored.
7. Provenance (CONFIRMED): runtime code at HEAD is AST-identical to dc06cb4, which was committed after the runs. `streaming_chunks` in calibration.json was added by hand, and the file was last written after Flask's simulated inference runs. Flask c25 inference resource files come from a session 30 h after its Locust stats.
8. Several thesis method claims do not match the code (CONFIRMED): warm-up by "CV < 2 %" (the code sends 3 curls per configuration, and one loop hits a 404 URL), "120 log files", the directory names, and "typical response size" (the simulated body is 33 % smaller).
9. The headline numbers reproduce from raw data: throughput ratios, Stage 2 medians, memory ratios and sync TTFT. The exception is async TTFT at c = 100, which is 1.79 / 2.00 s rather than "about 1 s".
10. What survives: the sync single-worker ceiling (about 0.34 req/s = 1/S), the async >> sync throughput ordering at every c >= 5, and the real-API results at c <= 10. Almost every magnitude at c >= 25 needs a rerun.

---

## 2. Findings table

| ID | Finding | Status | Evidence | Affected metrics | Frameworks, c | Direction and rough size | Severity |
|---|---|---|---|---|---|---|---|
| F1 | Simulated path builds a new httpx client per request. `httpx.post`/`httpx.stream` module functions build a `Client` each call; async uses `async with httpx.AsyncClient()`. Construction loads the certifi CA bundle into a new SSLContext (httpx/_config.py:40) even for plain http. On an event loop this blocks for X ms. | CONFIRMED | common/anthropic_client.py:165, 175, 199, 210; httpx/_api.py:282 (post), 124 (stream). Local bench p5: Client 19.8 ms, AsyncClient 19.4 ms, ssl ctx 20.6 ms (median). CPU per completed request (p2), inference and pipeline: simulated 16.3 to 21.7 ms for all 4 frameworks vs real 2.5 to 3.6 ms (sync) and 2.9 to 7.0 ms (async). Stream: simulated 18.5 to 24.6 vs real 8.8 to 16.8 ms. | All latency metrics, throughput, TTFT, Stage 2/3, CPU, memory | FastAPI, Tornado at 25/50/100 (large); Flask, Django at 25/50/100 (small) | Async latency +c x X (X = 14 to 19 ms): +0.38 to 1.70 s. Throughput -15 / -26 / -37 %. Sync: +15 to 17 ms on a 2.9 s service time (-0.5 % throughput). | Invalidates reported result (async c >= 25) |
| F2 | Persistent synchronised bursts. `-r` = `-u`, `wait_time = between(0, 0)` and a zero-jitter simulator delay keep all c users in phase for the whole run. With F1, every request in a burst waits for all c constructions, and the whole burst completes together. | CONFIRMED | Server log clusters (p3): FastAPI c50 starts in clusters of 50 within 43 ms, ends in clusters of 50. stats_history (p12): FastAPI inference c25 completes exactly 25 every 3 to 4 s, with 0 in 39 of 55 s. Real API c10: 2 of 55 s empty (no bursts). Within a burst, sorted Stage 2 rises 12.1 to 14.6 ms per position, and Stage2+Stage3 IQR is 18 to 46 ms (p4). | Same as F1 | Async at 25/50/100 | Turns an X-per-request cost into c x X per request | Invalidates reported result (with F1) |
| F3 | Stage 2 "retrieval" inflation is event-loop resume lag. After `asyncio.sleep(0.05)` each coroutine waits for the constructions of the coroutines resumed before it. | CONFIRMED | common/retrieval.py:94; common/pipeline_service.py:151-160. Sorted Stage 2 slope 13.5 to 14.1 ms/position (FastAPI), 12.1 to 14.6 (Tornado); (median - 50)/(c/2) = 11.2 / 12.9 / 11.9 ms (FastAPI). | Metric #12 Stage 2, #11 | Async at 25/50/100 | Stage 2 +140 / +323 / +594 ms (FastAPI); +179 / +346 / +419 ms (Tornado) | Invalidates reported result (interpretation of Stage 2) |
| F4 | Sync latency is right-censored by the 60 s window with stop_timeout = 0. Only the first 20 requests of the initial queue are served; about c in-flight requests are killed and never recorded. | CONFIRMED | locust/argument_parser.py:866-872 (default "0"); locust/runners.py:278-283 (force=True kill). Completions per run (p1/p9): exactly 20 at every sync c >= 25 for inference and pipeline (one Flask and one Django pipeline run at c = 50 had 19), 24 for stream. Max response 57.9 to 59.0 s = 20 x S. | #1 TTFT, #3, #6 p95/p99, #4 CSR, #7 errors, #13 PCR | Flask, Django at 25/50/100 (c = 10 borderline, see H2) | Median recorded 29 to 30 s vs steady-state c x S = 72 / 144 / 288 s (2.5x / 4.8x / 9.6x under). p95/p99 capped at about 58 s. | Invalidates reported result |
| F5 | Sync 0 % errors, 100 % CSR and 100 % PCR at c >= 50 exist only because of F4. In steady state, the queue wait (c x S = 144 to 288 s) exceeds the 120 s client timeout. | INFERRED | locust_tests/test_inference.py:40, test_stream.py:67, test_pipeline.py:58 (timeout=120). requests' read timeout would fire before the first byte. | #4, #7, #13 | Flask, Django at 50/100 | Error rate would be high, not 0 % | Invalidates reported result (sync reliability claims) |
| F6 | Completion sentinel mismatch. The simulator sends `data: {"done": true, "total_tokens": 12}`; the framework-side readers look for `[DONE]`, so the done event is forwarded as a 13th "token". | CONFIRMED | simulated_endpoint/simulator.py:139 vs common/anthropic_client.py:188, 224. token_count = 13 in 100 % of the 30,043 simulated streams; real c <= 10: 10 to 14, mode 12 (p6). | #2 TPOT, token counts, stream payload | All 4 at 25/50/100 | TPOT 183.8 to 185.3 ms vs 198 to 205 ms real (-8 %). The 13th token arrives about 0 ms after the 12th, so span/12 = 2200/12. | Biases magnitude |
| F7 | The simulated stream has no first-token latency and is shorter. The first chunk arrives after one 200 ms interval; the real TTFT is 0.46 to 0.65 s. Simulated total 2.4 s vs real 2.70 to 2.91 s. | CONFIRMED | simulator.py:112-136; real c=1 data (p6): TTFT median 459 to 646 ms, total 2700 to 2912 ms, first-to-last chunk span 2172 to 2209 ms (the simulator's span is 2200, which matches). | #1, #3 (stream), #5 (stream) | All 4 across the 10/25 boundary | Sync stream throughput 0.34 to 0.35 at c <= 10, then 0.40 to 0.41 at c >= 25 (+19 %). Async TTFT at c = 25 looks continuous (559 to 581 ms vs about 510 ms) only because F1 adds about 360 ms. | Biases magnitude |
| F8 | Memory is carried over between runs and configurations. The server process was reused across 5 runs, 3 endpoints and 3 concurrency levels. Allocator high-water marks persist, so each run's "idle" sample is already near its peak. | CONFIRMED | p7 timeline. FastAPI after the SIMULATE=1 restart: idle 60 MB, then inference c100 peak 233, stream c100 idle 289 to 332, pipeline c25 idle 330. Summary `memory_growth_median_mb` is 0.0 in most rows (results/summary_resources.csv). Aggregation takes the first sample as idle (scripts/aggregate_data.py:252). | #8 peak RSS, #9 growth | All, mostly async at 25/50/100 | Peak depends on run order. Pipeline c25 (310 / 353 MB) is higher than pipeline c100 (234 / 180 MB). | Invalidates reported result (memory comparisons at c >= 25) |
| F9 | Part of the async memory at c >= 25 is live httpx clients: about 0.4 to 0.9 MB each, not returned to the OS after close. | INFERRED | p10: 100 live AsyncClients +38.9 MB, still retained after close and gc. The first simulated FastAPI inference run grows +34 / +59 / +95 MB at c = 25 / 50 / 100 (p7). | #8, #9 | Async at 25/50/100 | Possibly about 40 % of the async/sync gap at c = 100 | Biases magnitude |
| F10 | Throughput "share of ideal" uses the wrong ceiling for stream and pipeline, and for the real-API level c = 10. | CONFIRMED | locust/stats.py:472-476 (N / (last_request_timestamp - start_time)); start_time reset in LocalRunner._start (runners.py:481). Measured denominators 56.9 to 60.7 s (p1). Stream shares vs 2.878 s reach 102 to 104 % at c = 25 (p9). | #5 | All | See H6 table. Stream FastAPI 85 / 74 / 59 %; pipeline 86 / 79 / 64 % | Biases magnitude |
| F11 | Metric #11 (E2E pipeline) is measured server-side and excludes queueing, so it cannot be compared across execution models. | CONFIRMED | common/pipeline_service.py:97-122 (perf_counter inside the handler). Summary: Flask c100 E2E 2947 ms vs Locust response 30 s; FastAPI c100 E2E 4345 ms vs Locust 4.4 s. | #11 | Sync vs async at c >= 5 | Sync understated by 10x or more at c >= 10 | Invalidates reported result (any sync vs async E2E comparison) |
| F12 | Calibration provenance. `calibrate_simulator.py` never writes `streaming_chunks`; the key sits between `total_output_tokens` and `input_tokens` (hand edit). `tokens_per_second` counts `text_stream` deltas (chunks per second), not tokens. The file's mtime is after Flask's simulated inference runs. | CONFIRMED | scripts/calibrate_simulator.py:99, 104, 127-136; simulated_endpoint/calibration.json; mtime 2026-04-03 17:49:35 vs Flask inference c25 to c100 at 16:15 to 17:27, Flask stream c25 at 17:54. | Stream timing | All at c >= 25 | Values 5.0 chunks/s and 12 chunks do match the real c <= 10 data (TPOT about 200 ms, mode 12), so the numeric bias is small | Cosmetic (wording), provenance risk |
| F13 | Simulated payload differs from the real one. Text is 686 chars / 96 words vs about 1,030 chars. Inference body 785 to 793 B vs 1,177 to 1,191 B. Stream text is only the first 12 words (84 chars). Usage is fixed at 33/256 tokens, including for the longer pipeline prompt. Framework-side stream JSON is double-wrapped. | CONFIRMED | simulator.py:64-75, 91-98, 121-136; stats "Average Content Size" (c1/c10 vs c25, all frameworks); flask_app/app.py:60-63 wraps the simulator's raw JSON string. | Framework-side cost, content size | All at c >= 25 | Slightly lower serialisation and I/O cost in sim mode; small next to F1 | Cosmetic to minor |
| F14 | Flask inference c25 resource files come from a different session than its Locust stats. | CONFIRMED | mtimes: `c25_run*_resources.csv` 04-04 21:52 to 22:04; `c25_run*_stats*.csv` 04-03 16:15 to 16:26. dc06cb4 message: "fix Flask c25 resources". | #8, #9, #10 | Flask inference c25 | Unknown; the pairing of load and resources is not guaranteed | Biases magnitude (one cell) |
| F15 | Aggregation is inconsistent and low-precision. Locust metrics are medians of per-run values, taken from 2-significant-figure buckets. Stream and pipeline custom metrics are pooled across runs. With 20 requests per run, p95 and p99 are the top one or two observations. | CONFIRMED | scripts/aggregate_data.py:127-175 vs 330-341 and 431-438; locust/stats.py:122-137. Example: FastAPI vs Tornado inference c100 Locust median 4500 vs 4600, but exact mean 4.53 vs 4.46 s (order reverses). | #3, #6, #1, #2, #11, #12 | All | Up to about ±2.5 % per value; framework rankings within 100 ms are not resolvable | Biases magnitude |
| F16 | Metric #10 CPU averages include non-load samples (idle row, 2 s pre-start, tail) and are single-PID, sampled at 1 s. Async max CPU reaches 100 to 106 % during bursts (saturated core) while the mean is 23 to 55 %. | CONFIRMED | resource_monitor.py:54, 93-94; aggregate_data.py:246-261; run_config.sh:107-113 | #10 | All | Means understate burst saturation | Biases magnitude |
| F17 | The simulator has no latency jitter. Simulated p95 is about equal to the median (for example FastAPI stream c25: 2900 vs 2800), while the real API at c = 1 has p95 3.3 to 5.3 s. Tail-latency behaviour across the boundary is not comparable, and zero jitter is what sustains F2. | CONFIRMED | simulator.py:86-89; p1 table | #6 | All across 10/25 | Simulated tails far too tight | Biases magnitude |
| F18 | Warm-up does not match the thesis claim: 3 curl requests per configuration (not per run), with no CV check. For stream, the first loop posts to `/api/stream` (404). | CONFIRMED | scripts/run_config.sh:28, 77-82, 85-92 | First-run values | All | Small | Cosmetic (claim is false) |
| F19 | Asymmetries between servers. Gunicorn's sync worker forces `Connection: close`; the async servers keep connections alive. Gunicorn and Uvicorn write a stdout access-log line per request; Tornado writes none. The stream test uses module-level `requests.post` (new session and TCP connection per request) for all frameworks. | CONFIRMED | gunicorn/workers/sync.py:177-180; flask_app/gunicorn_config.py:26, django_app/gunicorn_config.py:33; uvicorn/config.py:198 (access_log=True); tornado/web.py:2421-2435 (INFO to an unconfigured logger); test_stream.py:63 | #3, #10 | All | Sub-millisecond per request; negligible next to F1 | Cosmetic |
| F20 | Django docs are inconsistent with its settings. The docstring says middleware was "removed" and a comment says "retained (session, security)"; the actual list is Security + Common only, with no session or CSRF middleware, so `@csrf_exempt` is a no-op. | CONFIRMED | django_app/config/settings.py:3, 22, 28-31; django_app/api/views.py:30, 50, 84 | Django cost | Django, all c | Negligible | Cosmetic (documentation) |
| F21 | The two runtime code changes (simulator chunk count; Gunicorn timeout 120 to 600) were committed after all runs finished. The data show that the chunk change was active for every simulated stream run; the timeout change is irrelevant, since requests take 3 s or less. | CONFIRMED (code) / INFERRED (effect) | dc06cb4 (2026-04-04 22:12) vs last run 21:19 (Tornado pipeline) and 22:04 (Flask c25 resources); p6: 13 tokens (the older code would emit 256 + 1) | None | None | None | Cosmetic (provenance) |

---

## 3. Detail by phase

### Phase 0: provenance

- History (CONFIRMED, `git log`): 96eba83 on 2026-04-02 23:56 (all code); dc06cb4 on 2026-04-04 22:12 (aggregate script, run_config.sh, and the two runtime edits in F21); b2fae72 on 2026-04-13 (data plus comment-only rewrites); 0fac7af on 2026-05-23 (chart labels). Runs happened 04-03 13:00 to 04-04 21:19, with Flask c25 inference resources re-recorded 04-04 21:52 to 22:04.
- Were code files changed after the data were committed? No. Data entered git in b2fae72. `analysis/scripts/ast_compare.py` shows every runtime `.py` at HEAD is AST-identical to dc06cb4; only `scripts/aggregate_data.py` differs (charts). The b2fae72 edits to code were comments and docstrings only.
- Is the working tree the code that produced the data? Very likely yes (INFERRED). `git diff HEAD` on tracked code is empty. The last runtime edits were committed at 22:12 on the final run day, so they may have been made at any time before. The data prove the simulator edit was live for all simulated stream runs (F21).
- calibration.json exists (not tracked, `.gitignore`). Contents: `median_response_time_s` 2.878, `tokens_per_second` 5.0, `total_output_tokens` 256, `streaming_chunks` 12, `input_tokens` 33, model claude-haiku-4-5-20251001, raw_response_times [2.917, 2.878, 2.758, 2.821, 3.003], raw_tps_values [5.0, 5.1, 4.8, 5.1, 4.8], raw_output_tokens [256 x 5]. The 2.878 delay and 5.0 rate match the thesis. The script's rate is chunks per second, and 12 is not produced by the script (F12). The inference raw times come from 5 sequential calls through one fresh client, so the first includes the TLS handshake.
- logs/: 4 files, one `pipeline_timing.jsonl` per framework (1,574 / 1,557 / 15,164 / 15,653 lines). They contain warm-up requests and requests completed after Locust stopped (for example FastAPI c100 run 1: 1,301 server records vs 1,201 Locust rows). They are not used by aggregation.
- FUTURE_IMPROVEMENTS.md exists (generic notes, no data). Experiment_Guide.md is absent; it was committed as an empty file and then deleted (31d4c37).
- Environments: `venv/` matches environment.txt exactly, plus plotting packages installed 04-04 21:26 (after the runs). Runtime packages were installed 04-02 12:48. `.venv/` holds only plotting libraries. uvloop and httptools are not installed, so Uvicorn 0.42.0 `loop="auto"` falls back to asyncio (uvicorn/loops/auto.py) and `http="auto"` to h11 (uvicorn/protocols/http/auto.py:7-13). Tornado also runs on the stock asyncio loop with its own pure-Python HTTP/1 parser. Loop parity between the two async servers holds. `--workers 1` is single-process (uvicorn/main.py:593-604).

### Phase 1: execution trace (one table)

The Locust client for inference and pipeline is `self.client` (HttpSession, one requests.Session per user, keep-alive attempted). For stream it is `requests.post` (test_stream.py:63, a new Session and TCP connection per request).

| Framework / endpoint | Server model | Handler to common/ | Upstream client, real mode | Upstream client, SIMULATE=1 | Pool limits in effect | Blocking ops on event loop | Response framing | Per-request logging |
|---|---|---|---|---|---|---|---|---|
| Flask inference | Gunicorn sync, 1 worker, 1 thread; `Connection: close` forced | `api_inference` to `inference_sync` | `Anthropic()` singleton per worker, created lazily on the first request (anthropic_client.py:36-41) | `httpx.post` builds a Client plus SSLContext per request; new TCP connection to :9000 (anthropic_client.py:165) | Real: SDK 1000 / 100 keep-alive (anthropic/_constants.py:11), 1 in use. Sim: throwaway client, httpx default 100 / 20, 1 in use | n/a (sync) | `jsonify` | Gunicorn access log to stdout |
| Flask stream | same | generator over `stream_sync` holds the worker for the whole stream | singleton; `messages.stream` | `httpx.stream` builds a Client per request (175); forwards raw `data:` payloads, including `{"done":...}` | same | n/a | SSE `{"token","index"}`, then done; the simulator's JSON is double-wrapped | Gunicorn |
| Flask pipeline | same | `run_pipeline_sync`: `_search` (file read per call, retrieval.py:62), `time.sleep(0.05)`, `inference_sync`, `_log_stage_timing` (makedirs + open/append per request, pipeline_service.py:42-52, 0.018 ms median by p11) | singleton | per-request Client | same | n/a | JSON with stage_timings | Gunicorn plus JSONL |
| Django inference / stream / pipeline | Gunicorn sync, same config; middleware Security + Common | views call the same common functions; `JsonResponse` / `StreamingHttpResponse` | same as Flask | same as Flask | same | n/a | same | Gunicorn plus JSONL (pipeline) |
| FastAPI inference | Uvicorn, 1 process, asyncio + h11, keep-alive | `await inference_async` | `AsyncAnthropic()` singleton, created lazily on the first request; construction blocks the loop once | `async with httpx.AsyncClient()` per request (199): X ms blocking on the loop; new TCP connection | Real: 1000 / 100. Sim: throwaway, 100 / 20 | Sim: client construction (about 15 to 20 ms). Real: one-time construction | `JSONResponse` | Uvicorn access log to stdout (default on) |
| FastAPI stream | same | `StreamingResponse` over `stream_async` | singleton | per-request AsyncClient (210); raw events forwarded | same | same | SSE, double-wrapped in sim | Uvicorn |
| FastAPI pipeline | same | `run_pipeline_async`: `_search` sync file read (about 0.027 ms, already ruled out), `asyncio.sleep`, `inference_async`, sync `_log_stage_timing` on the loop (0.018 ms) | singleton | per-request AsyncClient, constructed after the sleep resumes (F3) | same | construction; file read; JSONL append; `json.dumps` | JSON | Uvicorn plus JSONL |
| Tornado inference / stream / pipeline | Tornado HTTPServer, asyncio loop, own parser, keep-alive | handlers `await` the same common async functions; stream uses `write` + `flush` per chunk (tornado_app/main.py:74-78) | same as FastAPI | same as FastAPI | same | same as FastAPI | same | none emitted (tornado.access has no handler; INFO is dropped) plus JSONL for pipeline |

Consequence: in real mode every framework reuses one upstream client, which is fine. In simulated mode every framework constructs one client per request. The sync server pays X once per request inside a serial queue; the async server pays X on the shared loop, where it serialises across the burst (F1, F2).

Connection pools: in real mode at c <= 10 no limit binds. In simulated mode each throwaway client has its own pool, so no limit binds either. If a shared httpx client is introduced for the rerun, the httpx defaults (100 connections, 20 keep-alive, 5 s pool timeout, httpx/_config.py:246-247) would bind at exactly c = 100 and force connection churn. See change C1.

### Phase 2: simulator and calibration

See section 4 for the timing model. Parameter origins:

| Parameter read by simulator | Value used | Source | Written by calibrate_simulator.py? |
|---|---|---|---|
| `median_response_time_s` (simulator.py:86) | 2.878 | calibration.json | Yes (median of 5 non-stream calls, client-side wall time) |
| `tokens_per_second` (simulator.py:112) | 5.0 | calibration.json | Yes, but it is (text deltas - 1) / (last - first delta) (calibrate_simulator.py:99-104): chunks per second, not tokens |
| `streaming_chunks` (simulator.py:113) | 12 | calibration.json (hand-added); hard-coded fallback 12 | No |
| `total_output_tokens`, `input_tokens`, `model` | 256, 33, haiku | calibration.json | Yes; only echoed in the `usage` field |
| Defaults (simulator.py:34-40) | 2.5 s, 50 tps, 256 | used only if the file is missing | n/a |

SSE contract (CONFIRMED): the simulator ends with `data: {"done": true, "total_tokens": 12}` (simulator.py:139). `_simulated_stream_sync` and `_simulated_stream_async` terminate only on `data == "[DONE]"` (anthropic_client.py:188, 224), so they yield every event string, including the done object, as a "token". Each framework wraps that string again as `{"token": "<escaped simulator JSON>", "index": n}` and appends its own done event with `total_tokens` 13. The Locust parser counts 13 tokens and sets success on the framework's done event (test_stream.py:91-99).

Is the simulator a bottleneck at c = 100? Probably not (INFERRED). Simulated chunk pacing at c = 100 gives a first-to-last span of 2211 to 2224 ms against a nominal 2200 ms (p6), under 1 % slower. Flask c25 minimum latency is 2918 ms against a 2878 ms delay. The host has 8 logical CPUs, and every process involved is single-threaded. The simulator's own CPU was not monitored (UNVERIFIABLE directly).

### Phase 3: measurement and aggregation

| # | Metric | Code | Source | Includes queueing? |
|---|---|---|---|---|
| 1 | TTFT | test_stream.py:99: perf_counter from before `requests.post` to the first non-done event | custom client | Yes (sync backlog, async loop stalls) |
| 2 | TPOT | test_stream.py:107-111: (last - first event) / (n - 1) | custom client | No, but includes the sentinel artefact (F6) |
| 3 | Total response time | Locust HttpSession timing (inference, pipeline); manual `events.request.fire` (stream, test_stream.py:114) | Locust | Yes, for completed requests only (F4) |
| 4 | CSR | framework done event seen, per run then median (aggregate_data.py:350) | custom client | Killed in-flight requests are never counted |
| 5 | Throughput | Locust Requests/s = N / (last completion - test start) (stats.py:472-476) | Locust | n/a |
| 6 | p95/p99 | Locust percentiles of 2-s.f. buckets, per run, then median | Locust | Yes |
| 7 | Error rate | failures / requests per run, median | Locust | Killed requests are not failures |
| 8 | Peak RSS | max `rss_mb` of one PID including the pre-load sample (aggregate_data.py:257) | psutil | n/a (carry-over, F8) |
| 9 | Memory growth | peak - first sample | psutil | n/a |
| 10 | CPU | mean of 1 s `cpu_percent` including non-load samples (aggregate_data.py:261) | psutil | n/a |
| 11 | E2E pipeline | server perf_counter across stages 1 to 4 (pipeline_service.py:97-122), carried in the payload | server via payload | No (F11) |
| 12 | Stage timing | same payload, pooled medians (aggregate_data.py:431-438) | server via payload | Stage 2/3 include event-loop lag (F3) |
| 13 | PCR | HTTP 200 and non-empty answer (test_pipeline.py:55-75) | custom client | Killed requests are never counted |

Locust 2.43.4 semantics (CONFIRMED from installed source):
- `-t 60s` spawns `stop_and_optionally_quit` after 60 s (locust/main.py:513-514, 570-572).
- `--stop-timeout` defaults to "0" (argument_parser.py:866-872), so users are killed with `force=True` (runners.py:278-283) and in-flight requests are neither logged nor counted as failures.
- Requests/s for both CSV rows uses the global `stats.start_time` and `stats.last_request_timestamp` (stats.py:237-242, 472-476). start_time is reset by `clear_all()` at `_start` (runners.py:481). The window therefore runs from test start to the last completion, not a fixed 60 s. Measured denominators: 56.9 to 60.7 s.
- Response times are bucketed to about 2 significant figures before percentiles and medians (stats.py:122-137).

Arrival pattern (H7.3, CONFIRMED): `-r` = `-u` spawns all users in one tick. The measured spread between the first and the c-th send in async stream runs is 16 to 72 ms (p8). The bursts persist in stats_history and in the server JSONL (F2).

Resource monitor PID (INFERRED): run_config.sh takes a user-supplied PID described as "the framework server worker process" (run_config.sh:17). psutil reads only that PID, with no children (resource_monitor.py:33, 93-94). Flask and Django CPU per request (2.5 to 3.6 ms real, 16 to 20 ms simulated) and idle RSS of 57 to 66 MB (anthropic imported) show the monitored process served the requests, so it was the Gunicorn worker. With `preload_app = False` the master never imports the app and would show about 0 CPU. Uvicorn with 1 worker and Tornado are single processes.

---

## 4. Hypotheses

### H1: per-request client construction (CONFIRMED)

Overhead above the simulated service time S (inference 2.878, stream 2.4, pipeline 2.928 s). Uses exact medians from Locust means or the custom CSVs, not the 2-s.f. buckets (p9, p4):

| Framework | Endpoint | c | median latency s | overhead ms | overhead / c ms | Stage 2 excess ms | Stage 2 excess / c ms | within-burst Stage 2 slope ms/pos |
|---|---|---|---|---|---|---|---|---|
| FastAPI | inference | 25 / 50 / 100 | 3.363 / 3.828 / 4.529 | 485 / 950 / 1651 | 19.4 / 19.0 / 16.5 | | | |
| FastAPI | stream | 25 / 50 / 100 | 2.802 / 3.212 / 3.997 | 402 / 812 / 1597 | 16.1 / 16.2 / 16.0 | | | |
| FastAPI | pipeline | 25 / 50 / 100 | 3.307 / 3.663 / 4.345 | 379 / 735 / 1417 | 15.2 / 14.7 / 14.2 | 140 / 323 / 594 | 5.6 / 6.5 / 5.9 | 14.1 / 13.9 / 13.5 |
| Tornado | inference | 25 / 50 / 100 | 3.286 / 3.755 / 4.463 | 408 / 877 / 1585 | 16.3 / 17.5 / 15.9 | | | |
| Tornado | stream | 25 / 50 / 100 | 2.775 / 3.107 / 4.098 | 375 / 707 / 1698 | 15.0 / 14.1 / 17.0 | | | |
| Tornado | pipeline | 25 / 50 / 100 | 3.321 / 3.682 / 4.078 | 393 / 754 / 1150 | 15.7 / 15.1 / 11.5 | 179 / 346 / 419 | 7.2 / 6.9 / 4.2 | 14.6 / 14.0 / 12.1 |

Overhead / c is roughly constant at 14 to 19 ms, which is the signature of burst serialisation. Stage 2 excess / c is about X/2 because the median request sits in the middle of the burst. The implied per-construction cost is X of about 12 to 19 ms. Three independent estimates agree: the latency slope (14 to 19 ms), the Stage 2 slope (12 to 14.6 ms), and the CPU per request in simulated minus real mode for inference and pipeline (about 14 to 18 ms, p2). This matches the sandbox figure of about 20 ms. On this machine today, the construction micro-benchmark gives 19.4 to 19.8 ms (p5).

Attempted refutation:
- CPU saturation alone would give latency of about c x (total CPU per request) only when c x X_total > S. At c = 50 that is 50 x 21 ms = 1.05 s < 2.878 s, yet latency is still +0.9 s. Only synchronised bursts explain c = 25 and 50.
- A Locust-side artefact is excluded because Stage 2 is timed server-side and shows the per-position slope.
- The simulator is excluded by F2/F7 pacing accuracy.
- Tornado c100 pipeline is the weakest fit (11.5 ms/c): its bursts partly dispersed (34 start clusters, median size 29, p3). It does not contradict the mechanism.

Mechanism: all c requests arrive together. Each coroutine runs to its first await, and in simulated mode the construction happens just before that first await. The loop therefore runs c constructions back to back before any upstream connection is written. All c simulator calls then start and return together, so all c responses leave together, and the users re-send together.

What the sync path loses: X once per request, on top of a 2.9 s serial service time. CPU per request rises from about 3 ms to about 18 ms (p2), throughput falls by about 0.5 %, and queueing latency grows by k x X (under 0.35 s at k = 20). Parity is broken in scale, not in kind: sync pays X, async pays about c x X.

### H2: sync censoring (CONFIRMED)

Completions per run and recorded latency (p9, 2-s.f. Locust values), against the uncensored steady-state expectation c x S:

| Framework | Endpoint | c = 25 | c = 50 | c = 100 | recorded median / p95 / p99 / max (ms) | c x S steady state (s) |
|---|---|---|---|---|---|---|
| Flask | inference | 20 x5 | 20 x5 | 20 x5 | 29000 / 58000 / 58000 / 57955 to 57991 | 72 / 144 / 288 |
| Flask | stream | 24 x5 | 24 x5 | 24 x5 | 29000 / 56000 / 58000 / 58153 to 58172 | 60 / 120 / 240 |
| Flask | pipeline | 20 x5 | 19, 20 x4 | 20 x5 | 29000 to 30000 / 59000 / 59000 / 58971 to 58990 | 73 / 146 / 293 |
| Django | inference | 20 x5 | 20 x5 | 20 x5 | 29000 / 58000 / 58000 / 57989 to 58015 | 72 / 144 / 288 |
| Django | stream | 24 x5 | 24 x5 | 24 x5 | 29000 / 56000 / 58000 / 58193 to 58228 | 60 / 120 / 240 |
| Django | pipeline | 20 x5 | 20 x4, 19 | 20 x5 | 29000 to 30000 / 59000 / 59000 / 58970 to 58995 | 73 / 146 / 293 |

At c = 1 / 5 / 10 the counts are 14 to 21 per run. At c = 5 the recorded median (14 s) equals c x S (14.5 s), so it is not censored. At c = 10 the recorded 28 to 29 s equals c x S (29 s): the first round is still ramping, but the median is essentially uncensored. Requests dropped at stop per run: about c (1 in service plus c - 1 queued).

Under FIFO accept order, the served requests have latency k x S for k = 1..20, so the median is about 10.5 x S, which is about 30 s whatever c is. This is exactly what was recorded. The thesis's flat 29 s from c = 25 to 100 comes from the window, not from framework behaviour.

Thesis latency claims affected: sync response time medians at c = 25 / 50 / 100 (about 29 to 30 s); sync p95/p99 (56 to 59 s); sync TTFT at c >= 25 (about 28 s, the "28 s vs about 1 s" headline); any statement that sync latency "plateaus" or "stabilises" beyond c = 25; the sync/async latency ratios at c >= 25 (understated by about 2.4x / 4.8x / 9.6x); sync error rate, CSR and PCR of 0 % / 100 / 100 % at c >= 25 (F5); and the sync E2E pipeline comparison (F11).

### H3: sentinel forwarded as a token (CONFIRMED)

token_count distribution (p6): at c <= 10 all frameworks show 10 to 14 (mode 12, for example FastAPI c10 {10: 31, 11: 168, 12: 711, 13: 73}). At c >= 25 it is {13: n} for all four frameworks at all three levels (Flask 120/120/120, Django 120/120/120, FastAPI 2658/4669/7495, Tornado 2675/4697/7129).

| Framework | TPOT median ms, c = 1 / 5 / 10 (real) | TPOT median ms, c = 25 / 50 / 100 (sim) | Unbiased simulated value |
|---|---|---|---|
| Flask | 201.6 / 199.1 / 200.7 | 183.8 / 183.9 / 183.9 | 200 (2200 / 11) |
| Django | 204.6 / 202.1 / 204.0 | 183.9 / 183.9 / 183.9 | 200 |
| FastAPI | 203.4 / 204.0 / 203.3 | 184.3 / 184.5 / 185.2 | 200 |
| Tornado | 200.0 / 198.7 / 197.8 | 184.3 / 184.7 / 185.3 | 200 |

The downward shift of 8 % is entirely the sentinel. Without it the simulated TPOT would equal the real one. This is consistent with the 5.0 chunks/s calibration.

### H4: stream shorter and no first-token latency (CONFIRMED)

| Framework | Real c = 1 TTFT / total (ms) | Sim model TTFT / total (ms) | Observed sim c = 25 TTFT / total (ms) | Stream throughput c = 10 / 25 |
|---|---|---|---|---|
| Flask | 593 / 2829 | 200 / 2400 | 28196 / 30405 (queued) | 0.345 / 0.404 |
| Django | 646 / 2912 | 200 / 2400 | 28109 / 30317 (queued) | 0.339 / 0.412 |
| FastAPI | 515 / 2765 | 200 / 2400 | 581 / 2802 | 3.278 / 8.875 |
| Tornado | 459 / 2700 | 200 / 2400 | 559 / 2775 | 3.383 / 8.998 |

The simulator reproduces the real chunk cadence (span 2200 ms vs real 2172 to 2209 ms) but not the first-token latency (200 ms vs 459 to 646 ms, framework path included). The simulated stream is therefore 300 to 500 ms (11 to 17 %) shorter. Sync stream capacity jumps from 1/2.83 to 1/2.45 req/s at the boundary (+19 %), a pure simulator effect. Async TTFT at c = 25 looks continuous with c = 10 only because the missing 300 ms of first-token latency is offset by about 360 ms of F1 overhead. At c = 50 / 100 the TTFT (981 / 1787 FastAPI, 923 / 2003 Tornado) is almost entirely F1. TTFT, total time and stream throughput are not comparable across c = 10 / 25.

### H5: memory and client objects (partly INFERRED)

What the data can show: RSS of one PID at 1 s resolution, and that RSS ratchets up across runs and configurations within one server lifetime (F8). What the data cannot show: which allocations make up the RSS, whether memory would be released between runs, and how RSS splits between concurrent clients, sockets and buffers. Nothing else was recorded.

Supporting estimate: 100 live AsyncClients cost 38.9 MB here, all retained after close (p10). The first simulated FastAPI inference runs grew +34 / +59 / +95 MB at c = 25 / 50 / 100. Clients plausibly account for a large share, perhaps 40 %, at c = 100.

Measurement that would separate the causes: a 2 x 2 design (per-request vs singleton client) x (c = 25 / 100) on a server restarted per run, recording:
- RSS, USS and PSS at 100 ms resolution;
- the number of open sockets (`psutil.Process.net_connections`) and live `ssl.SSLContext` objects (gc scan);
- `tracemalloc` snapshots for the Python heap;
- optionally `MALLOC_ARENA_MAX` and `malloc_trim` checks, to separate allocator retention from live objects.

### H6: throughput ceiling (CONFIRMED)

Derivation for a closed loop with c users, constant service time S and zero think time. `-r` = `-u` gives a spawn spread of 0.02 to 0.07 s. The test is killed at t0 + 60 s. Requests/s = N / (t_last - t_start), where t_start is the `clear_all` time just before spawning.

Each user completes k = floor((60 - d) / S) requests, where d is the spawn offset, and the last completion is at d + kS. So Requests/s = ck / (kS + d) = (c / S) x kS / (kS + d), which is 0.98 to 1.0 x c/S. Integer rounding of rounds does not lower the ceiling, because the window ends at the last completion. The ceiling is c / S_endpoint for async and 1 / S_endpoint for a single sync worker.

The correct service times are: inference 2.878 s; stream 2.4 s; pipeline 2.928 s; plus a few ms of irreducible framework cost. For the real-API levels (c <= 10), use the measured real service time (c = 1 median for the same framework and endpoint: 2.70 to 3.05 s), not the simulator's 2.878.

Little's law check: c / mean latency equals Requests/s within 0 to 5 % for every async cell at c >= 25 (within 7 % at c <= 10). The async shortfall is therefore entirely latency inflation (F1, F2), not a separate throughput limit.

| Async | Endpoint | Thesis-style share rps / (c / 2.878), c = 10 / 25 / 50 / 100 | Corrected share rps / (c / S_ep), c = 10 / 25 / 50 / 100 |
|---|---|---|---|
| FastAPI | inference | 96.4 / 84.9 / 73.5 / 62.6 % | 94.8 (S = 2.83 real) / 84.9 / 73.5 / 62.6 % |
| FastAPI | stream | 94.3 / 102.2 / 89.0 / 71.2 % | 90.6 / 85.2 / 74.2 / 59.4 % |
| FastAPI | pipeline | 96.3 / 84.9 / 77.1 / 63.0 % | 90.6 / 86.3 / 78.5 / 64.1 % |
| Tornado | inference | 97.2 / 84.8 / 73.8 / 61.6 % | 103.0 (S = 3.05 real) / 84.8 / 73.8 / 61.6 % |
| Tornado | stream | 97.3 / 103.6 / 90.9 / 68.6 % | 91.3 / 86.4 / 75.8 / 57.2 % |
| Tornado | pipeline | 98.6 / 86.5 / 77.7 / 68.7 % | 94.6 / 88.0 / 79.0 / 69.8 % |

Sync against 1 / S_ep: 96 to 99 % at c >= 25 for every endpoint. Stream is 97 to 99 % against 1/2.4, whereas against 1/2.878 it would be 116 to 119 %.

For inference the thesis ceiling happens to be right numerically (97 / 85 / 74 / 63 % reproduces as 96.4 / 84.9 / 73.5 / 62.6 %). The deficit, though, is the F1 artefact and not a framework property. With a singleton client and jittered arrivals, the expected share is about 98 % (INFERRED; UNVERIFIABLE without a rerun).

### H7: other asymmetries

- Access logging (CONFIRMED): Gunicorn (flask_app/gunicorn_config.py:26, django_app/gunicorn_config.py:33) and Uvicorn (default `access_log=True`, uvicorn/config.py:198) write one line per request to stdout. Where stdout went is unknown. Tornado emits nothing, because `tornado.access` has no handler and 2xx is logged at INFO (tornado/web.py:2421-2435). The cost is microseconds per request, unless stdout was a slow WSL terminal (UNVERIFIABLE).
- Django (CONFIRMED): Security + Common middleware only; no CSRF middleware, so `@csrf_exempt` does nothing. Negligible cost.
- Keep-alive (CONFIRMED): the Gunicorn sync worker always closes (sync.py:177-180), so `keepalive = 5` is ignored. Uvicorn and Tornado keep connections alive for inference and pipeline. A localhost TCP setup costs about 0.1 ms, which is negligible.
- Stream client (CONFIRMED): module-level `requests.post` opens a new connection per request for all frameworks. This is equal across frameworks but differs from the other endpoints. The response is not explicitly closed, but it is fully consumed.
- Loop and HTTP implementation (CONFIRMED): both async servers use asyncio with pure-Python parsers. Parity is acceptable, and the result is not "Uvicorn with uvloop/httptools".
- Locust CPU headroom at c = 100: UNVERIFIABLE. Locust's own "CPU usage above 90 %" warning goes to stdout and was not saved. Locust handles at most about 25 req/s here, which is modest for requests + gevent. Client-side values (TTFT, total) include Locust's sequential processing of 100 near-simultaneous responses (INFERRED small).
- Co-location (INFERRED benign): 8 logical CPUs, and the server, simulator, Locust and monitor are each single-threaded. Simulator pacing error is under 1 %. Burst CPU saturation of the server's own core (max 100 to 106 %) is the binding resource.

---

## 5. Simulator, end to end

`/simulate/inference` (simulator.py:85-101): receive the POST, `await asyncio.sleep(2.878)` (constant, no jitter), then write a JSON body with the fixed 686-char text, `usage` {33, 256} and the model name. Tornado sets Content-Length. It is a single-process Tornado server on :9000.

`/simulate/stream` (simulator.py:111-140): headers are set but not flushed. Then, 12 times: `await asyncio.sleep(0.2)`, write `data: {"token": "<word> ", "index": i}` and flush. Finally, the done event is written immediately.

Timing of one simulated stream request through an async framework at concurrency c (ms, after the request reaches the framework, when requests arrive in a synchronised burst):

```
framework handler k (k = 1..c in burst order)
  0 .......... k*X   wait for earlier constructions on the loop   (X ~ 14-19 ms)  <- artefact F1/F2
  ...(c*X)..         all c AsyncClients built; all c connects/POSTs to :9000 flushed together
simulator (per request, from receipt)
  +0                 headers buffered
  +200               chunk 1 flushed (with headers)            <- TTFT_sim = 200 (real ~460-650 incl. framework)
  +400 ... +2400     chunks 2..12, 200 ms apart                <- matches real cadence
  +2400              {"done": true, ...} flushed immediately   <- forwarded as token 13 (F6)
  +2400              response finished (chunked terminator)
framework
  forwards 13 "tokens" as {"token": "<escaped sim JSON>", "index": n}, then its own done (total_tokens 13)
Locust client
  TTFT  ~ c*X + 200          (c=25: 581, c=50: 981, c=100: 1787 FastAPI)
  total ~ c*X + 2400         (c=25: 2802, c=50: 3212, c=100: 3997 FastAPI)
  TPOT  = 2200 / 12 = 183.3  (vs 200 unbiased)
```

Real stream at c = 1 for comparison: TTFT about 0.46 to 0.65 s, then about 11 more chunks at about 200 ms each, total 2.70 to 2.91 s, 10 to 14 chunks, about 1,000 chars of text.

---

## 6. Headline number reproduction (Phase 5)

Recomputed from raw data with the thesis's aggregation (medians of per-run Locust values; pooled medians for custom CSVs):

| Claim | Thesis | Recomputed | Verdict |
|---|---|---|---|
| Inference throughput c = 10, FastAPI vs Flask / Django | 3.35 vs 0.34 (about 10:1) | 3.349 vs 0.345 / 0.341 (9.7:1 / 9.8:1) | MATCH |
| c = 50 | 12.78 vs 0.34 (38:1) | 12.777 vs 0.335 / 0.342 (38.1:1 / 37.4:1) | MATCH |
| c = 100 | 21.74 vs 0.34 (64:1) | 21.739 vs 0.334 / 0.344 (65.1:1 / 63.2:1) | MATCH |
| TTFT c = 100, sync | about 28 s | Flask 28163, Django 28113 ms | MATCH (censored value, F4) |
| TTFT c = 100, async | about 1 s | FastAPI 1787, Tornado 2003 ms (c = 50: 981 / 923) | MISMATCH ("about 1 s" matches c = 50, not c = 100) |
| Stage 2 median FastAPI c = 10 / 25 / 50 / 100 | 51 / 190 / 373 / 644 ms | 50.6 / 189.7 / 373.3 / 643.9 ms | MATCH |
| FastAPI peak RSS | 332.2 MB | 332.2 MB (stream c = 100, median of per-run peak) | MATCH (cumulative high-water mark, F8) |
| Memory async / sync, inference c = 100 | about 3x | FastAPI 210.9, Tornado 207.2 vs Flask 72.5, Django 74.5 MB: 2.78x to 2.91x | MATCH |
| Memory async / sync, stream c = 100 | about 4.5x | 332.2 / 340.6 vs 73.3 / 83.0 MB: 4.54x / 4.65x vs Flask; 4.00x / 4.10x vs Django | MATCH vs Flask; 4.0x to 4.1x vs Django |
| Share of ideal, FastAPI inference c = 10 / 25 / 50 / 100 | 97 / 85 / 74 / 63 % | 96.4 / 84.9 / 73.5 / 62.6 % | MATCH, within rounding (c = 10 rounds to 96) |

The numbers reproduce. The problems are in what they measure, not in the arithmetic.

---

## 7. What survives

These hold regardless of every finding:
- A single sync Gunicorn worker (1 thread) serves about 1/S requests per second: 0.33 to 0.35 req/s at every c, and 0.40 to 0.41 for the shorter simulated stream. Capacity is fixed and latency grows linearly with the queue. This is a property of the configuration, not of Flask vs Django.
- The ordering async >> sync in throughput at every c >= 5, by roughly a factor of c (minus F1 losses). With F1 fixed, the async advantage at c >= 25 would be larger, not smaller.
- All real-API results at c = 1 / 5 / 10: async throughput about c/S, async latency about S, sync latency about c x S, TTFT about 0.5 s async, TPOT about 200 ms, 100 % CSR/PCR. F1 does not touch the real path, which uses singleton clients.
- Flask vs Django and FastAPI vs Tornado are indistinguishable at c <= 10, within Locust's 2-s.f. resolution and run-to-run noise. Any ranking within a pair at c >= 25 is dominated by F1/F2 and by rounding (F15).
- Stage 1 and Stage 4 are sub-millisecond for all frameworks.
- The sync-over-async memory advantage exists in direction. At c <= 10, async RSS stays at 60 to 72 MB vs sync 57 to 66 MB, so the large ratios appear only in the simulated, carry-over regime (F8, F9).

These do not survive as reported: async latency, TTFT, Stage 2 and throughput "share" at c >= 25; all sync latency percentiles, TTFT and reliability at c >= 25; memory and growth comparisons at c >= 25; TPOT and stream throughput continuity across c = 10 / 25; any sync vs async comparison of Metric #11.

---

## 8. Changes required before the rerun (priority order; described, not applied)

C1. Client lifetime parity (fixes F1 and F9).
- Create one upstream client per process at startup (Flask/Django: module level or Gunicorn `post_worker_init`; FastAPI: lifespan; Tornado: before `IOLoop.start`), for both the real and the simulated path.
- Sync uses `httpx.Client`; async uses `httpx.AsyncClient`. Or route simulated calls through the Anthropic SDK itself with `base_url` pointed at a simulator speaking the Messages API, so the code path is identical in both modes.
- Never construct a client inside a request. Warm each client with one request before measurement.
- Set explicit pool limits above the maximum concurrency on every client: for example `httpx.Limits(max_connections=256, max_keepalive_connections=128)` and a pool timeout of at least the request timeout. With the httpx defaults (100 / 20, 5 s pool timeout) a shared client would queue or churn at c = 100.
- Set the Anthropic client's `max_connections` and `max_keepalive_connections` explicitly (defaults are 1000 / 100) and record them.

C2. Break artificial synchronisation (fixes F2).
- Spawn with `-r` well below `-u` (for example 5 to 10 users/s) and exclude the ramp from measurement.
- Add jitter to the simulator, sampled from the empirical real-API distribution (per-call latency, TTFT, chunk count and inter-chunk times).
- Optionally add a small random start offset per user. Report whether bursts remain, using per-second completions from stats_history.

C3. Stream completion sentinel (fixes F6, F13).
- Make the simulator emit exactly what the client parser expects (`data: [DONE]`, or parse JSON and stop on `done`).
- Have `_simulated_stream_*` parse each event and forward only the token text, never the envelope, so both modes deliver plain text chunks to the framework.
- Add a unit test asserting identical token counts and framing in both modes.

C4. Stream calibration (fixes F7, F12, F13).
- Extend `calibrate_simulator.py` to record and write, automatically and without hand edits, per call: TTFT, chunk count, every inter-chunk gap, total duration, text length and usage tokens.
- Use at least 30 calls spread over time, and store the raw arrays.
- Rename `tokens_per_second` to `chunks_per_second`.
- Have the simulator model TTFT plus inter-chunk gaps plus chunk count, and replay real response text so the payload size matches.
- Commit calibration.json with the data, record its hash in each run's metadata, and recalibrate on the day of the runs.

C5. The 60 s window and sync latency (fixes F4, F5). Options:
- (a) Long runs sized for steady state: the duration must cover several full queue cycles, i.e. at least (warm-up of c x S) + m x c x S. At c = 100 that is about 5 min per cycle, so 20 to 30 min per run. Raise the client timeout above c x S, or record timeouts as errors. Trade-off: this measures the real overload behaviour, but at high cost and time (sync c = 100 x 3 endpoints x 5 runs is about 6 h).
- (b) Measure only after the queue is full: reset stats at t = c x S (a custom `events` hook or `--reset-stats` after a ramp). Trade-off: the steady-state distribution comes from a shorter window, and the run still needs to be about c x S + 60 s.
- (c) Keep 60 s but treat in-flight requests as right-censored. Set `--stop-timeout` long enough to drain, or log dispatch times and report Kaplan-Meier medians and the censoring fraction. Keep throughput on a fixed window. Trade-off: cheap and honest, but it reports a transient, not a steady state.
- (d) Declare sync c >= 25 saturated by design and report the analytic c x S with measured S, plus a separate sync configuration with more workers or threads. Trade-off: no measured tail percentiles for the overloaded case.
- (e) Use an open-loop arrival rate below and above sync capacity, which avoids closed-loop censoring. Trade-off: this changes the experimental design and the thesis metric definitions.
- Recommendation: (c) for all cells plus (a) or (b) for the sync c >= 25 cells, and report the censoring fraction everywhere.

C6. Memory methodology (fixes F8, F9, F14).
- Restart the server before every run, or at least every configuration, and record a post-warm-up baseline.
- Sample at 100 to 250 ms. Record RSS plus USS/PSS; for Gunicorn record master and worker via the process tree; also record socket counts.
- Report per-run growth. Record the monitored PID and command line in each run's metadata.
- Never splice resource files from a different session.

C7. Throughput definition (fixes F10).
- Compute throughput on a fixed measurement window: completions with start and end inside [t_ramp_end, t_stop], divided by the window length.
- Report the ceiling as c / S_ep with measured S for each endpoint and mode, and show a Little's-law consistency check.

C8. Metric definitions.
- For Metric #11, add a client-side E2E pipeline latency, or a server receive timestamp that includes queueing, and use it for cross-model comparison (F11).
- Stage 2 should time only `_search` plus the sleep, measured as sleep-requested vs sleep-actual, and report loop lag separately (F3).
- CPU should report per-request CPU seconds and a loaded-window mean (F16).

C9. Aggregation and precision (fixes F15).
- Write a per-request CSV for every endpoint (a `request` event hook) and compute all percentiles from raw values, not Locust buckets.
- Use one aggregation rule for every metric (for example, median of per-run medians, with the run-to-run spread).
- Do not report p99 when a run has fewer than about 100 samples.

C10. Server parity (fixes F19, F20).
- Disable access logs on all servers (Gunicorn `accesslog=None`, Uvicorn `--no-access-log`), or enable equivalent logging on Tornado.
- Document that the sync worker closes connections. Use `self.client` with `stream=True` for the stream test, or one `requests.Session` per user.
- Fix the Django settings docstring and comment to match the middleware actually used.

C11. Warm-up and provenance (fixes F18, F21).
- Fix the warm-up URL for stream and warm up before each run.
- Implement the CV criterion if the thesis keeps claiming it; otherwise drop the claim.
- Commit code before running and record the git SHA, `pip freeze`, the calibration hash, server launch commands (including SIMULATE and logging flags), PIDs, and host state per run.

---

## 9. Thesis claims vs code (Phase 6)

| Claim | Code / data | Verdict |
|---|---|---|
| Warm-up "calibrated until the CV of response time drops below 2 %" | run_config.sh:28, 77-92: 3 fixed curl requests per configuration, no CV computation. For stream, the first loop posts to `/api/stream`, which does not exist, then 3 posts to `/api/inference/stream`. final_defence/discriminator_results.md already concludes the CV claim must be dropped. | Differs |
| 12 chunks and 5.0 chunks/s "both calibrated from real API streaming measurements" | 5.0 is produced by the calibration script as text deltas per second. 12 is not produced by any code (hand-added key; hard-coded fallback 12). Both agree with real c <= 10 data (TPOT about 200 ms, mode 12 chunks). First-token latency was not calibrated. | Partly true; wording inaccurate |
| "120 stage-level pipeline timing log files" | The 120 files are client-side `*_pipeline_metrics.csv` files (stage values copied from the response payload). The server-side logs are 4 JSONL files, one per framework, gitignored, not used by aggregation, and they include warm-up and post-stop requests. | Differs |
| Repository layout /flask, /django, /fastapi, /tornado, /load_tests | Actual: `flask_app/`, `django_app/`, `fastapi_app/`, `tornado_app/`, `locust_tests/`, plus `common/`, `simulated_endpoint/`, `monitoring/`, `scripts/` | Differs |
| Simulated response "matching the typical real response size" | 686 chars / 96 words vs about 1,030 chars real; body 785 to 793 B vs 1,177 to 1,191 B (-33 %); the stream carries only 12 words (84 chars); the `usage.output_tokens` = 256 label does not match the text | Differs |

---

## 10. Open questions only you can answer

1. Exact server launch commands for each phase. Was Uvicorn started with default access logging? Where did Gunicorn and Uvicorn stdout go (terminal, file, /dev/null)? Was SIMULATE=1 exported only at the c >= 25 restarts?
2. Which PID did you pass to run_config.sh for Flask and Django: the Gunicorn worker or the master? The data suggest the worker.
3. When were servers restarted? The RSS timeline shows restarts at the real to simulated switch and possibly within configurations (for example Tornado pipeline c50 before run 5, FastAPI pipeline c100 before run 3). Were any runs repeated or discarded?
4. What did calibration.json contain before 2026-04-03 17:49, and which simulator code served Flask inference c25 to c100 (16:15 to 17:27)? The data are consistent with a 2.878 s delay; the file history is not recoverable.
5. Where does `streaming_chunks: 12` come from: the console output of a calibration run, or the c <= 10 data? When was `calibrate_simulator.py` run?
6. Why were the Flask inference c25 resource files re-recorded on 04-04 21:52 to 22:04? Was Locust load running at the time, and what happened to that session's Locust output?
7. Which statistic or concurrency level does the thesis's "about 1 s" async TTFT refer to? And which text interprets Stage 2 inflation, sync latency plateaus and the E2E pipeline comparison? I did not have the thesis text; claims were checked against the values given in the brief.
8. Host conditions: .wslconfig CPU and memory limits, other workloads during the runs, power mode. Were Locust console logs (CPU warnings) kept anywhere?
9. For the paper, do you want sync configured as in the thesis (1 worker, 1 thread) for continuity, or also a realistic sync configuration (several workers or gthread) as an additional arm? This decides how to apply C5.
