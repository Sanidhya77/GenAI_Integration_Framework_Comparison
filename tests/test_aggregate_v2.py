"""aggregate_v2.py on synthetic run directories (no servers): monotonic columns required,
stream pairing verified, error rate, CSR, PCR, consistency ratio and --clock-correct."""
import csv
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import aggregate_v2 as ag  # noqa: E402

CAL = json.load(open(os.path.join(ROOT, "simulated_endpoint", "calibration_v2.json")))["values"]
T0, STOP = 1000.0, 1030.0
REQ_FIELDS = ["start_ts", "end_ts", "start_mono", "end_mono", "response_time_ms", "request_type", "name",
              "success", "exception", "response_length", "user", "http_status", "stages_logged"]


def write_csv(path, fields, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def make_run(root, fw, ep, c, s, reqs, extra_files, ratio=0.98):
    d = os.path.join(root, fw, ep)
    os.makedirs(d, exist_ok=True)
    prefix = os.path.join(d, f"c{c}_run1")
    meta = {"status": "complete", "framework": fw, "endpoint": ep, "concurrency": c, "run": 1, "service_time_s": s,
            "worker_pids": [1], "idle_rss_mb": 60.0, "idle_uss_mb": 45.0, "idle_drift": False,
            "clock_rate_ratio": ratio, "clock_step_detected": False, "clock_step_ms": 0.5,
            "clock_rate_unstable": False, "clock_rate_off_nominal": False, "monitor_cpu_pct": 1.2}
    json.dump(meta, open(prefix + "_meta.json", "w"))
    json.dump({"first_user_start_mono": T0, "stop_mono": STOP, "first_user_start_ts": 1.7e9,
               "stop_ts": 1.7e9 + 30}, open(prefix + "_locust_meta.json", "w"))
    write_csv(prefix + "_requests.csv", [k for k in REQ_FIELDS if k in reqs[0]], reqs)
    write_csv(prefix + "_inflight.csv", ["user", "issued_ts", "issued_mono", "age_at_stop_s", "completed_before"],
              [{"user": 0, "issued_ts": 0, "issued_mono": STOP - 1, "age_at_stop_s": 1.0, "completed_before": 5}])
    write_csv(prefix + "_stats.csv", ["Name", "Requests/s"], [{"Name": "Aggregated", "Requests/s": 0.7}])
    mon = ["timestamp", "mono", "elapsed_s", "wall_minus_mono_s", "rss_mb", "uss_mb", "cpu_percent", "n_procs"]
    rows = [{"timestamp": 0, "mono": T0 - 2 + i * 0.25, "elapsed_s": 0, "wall_minus_mono_s": 0, "rss_mb": 61,
             "uss_mb": 46, "cpu_percent": 10.0 if i % 2 else 30.0, "n_procs": 1} for i in range(136)]
    write_csv(prefix + "_resources.csv", mon, rows)
    write_csv(prefix + "_sim_monitor.csv", mon, rows)
    for name, (fields, frows) in extra_files.items():
        write_csv(f"{prefix}_{name}.csv", fields, frows)
    return prefix, meta


def req_row(end, rt_ms, ok=True, exc="", length=12, status="", stages="", rtype="SSE", name="/api/inference/stream"):
    return {"start_ts": 0, "end_ts": 0, "start_mono": end - rt_ms / 1000, "end_mono": end, "response_time_ms": rt_ms,
            "request_type": rtype, "name": name, "success": ok, "exception": exc, "response_length": length,
            "user": 0, "http_status": status, "stages_logged": stages}


def stream_run(tmp_path, mismatch=False, drop_mono=False):
    s = CAL["service_time_s"]["stream"]
    reqs, sm = [], []
    ends = [T0 + 2.8 * k for k in range(1, 11)]  # 1002.8 .. 1028.0, in the loaded window
    for i, e in enumerate(ends):
        tokens = 11 if i == 3 else 12
        done = i != 5
        reqs.append(req_row(e, 2800.123 + i, length=tokens))
        sm.append({"timestamp": 0, "ttft_ms": 560 + i, "tpot_ms": 202.0, "total_time_ms": 2800.123 + i,
                   "token_count": tokens, "success": done})
    reqs.append(req_row(T0 + 29.0, 5.0, ok=False, exc="Exception('HTTP 503')", length=0, status=503))
    sm.append({"timestamp": 0, "ttft_ms": None, "tpot_ms": None, "total_time_ms": 5.0, "token_count": 0,
               "success": False})
    reqs.append(req_row(STOP + 0.5, 2800.0))  # finished after stop: outside the loaded window
    sm.append({"timestamp": 0, "ttft_ms": 561, "tpot_ms": 202.0, "total_time_ms": 2800.0, "token_count": 12,
               "success": True})
    if mismatch:
        sm[2]["total_time_ms"] = 1.0
    if drop_mono:
        for r in reqs:
            r.pop("start_mono"), r.pop("end_mono")
    fields = ["timestamp", "ttft_ms", "tpot_ms", "total_time_ms", "token_count", "success"]
    return make_run(str(tmp_path / "data"), "fastapi", "stream", 2, s, reqs, {"stream_metrics": (fields, sm)})


def test_stream_metrics(tmp_path):
    prefix, meta = stream_run(tmp_path)
    m = ag.run_metrics(prefix, "fastapi", "stream", 2, meta["service_time_s"], CAL, meta)
    assert m["finished_loaded"] == 11 and m["error_rate_pct"] == pytest.approx(100 / 11)
    assert json.loads(m["failures_by_type"]) == {"HTTP 503": 1}
    # 11 streams in [t0, stop]: failed ones are #3 (11 chunks), #5 (no done) and the HTTP 503
    assert m["stream_csr_pct"] == pytest.approx(8 / 11 * 100)
    ends = [T0 + 2.8 * k for k in range(1, 11)]
    in_win = [(e, 2800.123 + i) for i, e in enumerate(ends) if e >= T0 + 2 * meta["service_time_s"]]
    x = (len(in_win) - 1) / (in_win[-1][0] - in_win[0][0])
    mean_s = sum(rt for _e, rt in in_win) / len(in_win) / 1000
    assert m["throughput_completion_rate"] == pytest.approx(x)
    assert m["closed_system_consistency"] == pytest.approx(mean_s * x / 2)
    assert m["ttft_p50_ms"] is not None and m["ttft_p99_ms"] is None  # n < 100
    assert m["sim_cpu_mean_pct"] == pytest.approx(20.0, abs=0.5) and m["sim_cpu_p95_pct"] == pytest.approx(30.0)
    assert m["rss_growth_mb"] == pytest.approx(1.0)
    assert "littles_ratio" not in m and "response_law_vs_measured_mean" not in m

    c = ag.clock_correct(m)
    assert c["latency_p50_ms"] == pytest.approx(m["latency_p50_ms"] / 0.98)
    assert c["tpot_p50_ms"] == pytest.approx(202.0 / 0.98)
    assert c["throughput_completion_rate"] == pytest.approx(x * 0.98)
    assert c["ceiling_rps"] == pytest.approx(m["ceiling_rps"] * 0.98)
    for k in ("share_of_ceiling_completion_rate", "closed_system_consistency", "cpu_mean_loaded_pct",
              "cpu_ms_per_request", "clock_step_ms", "idle_rss_mb"):
        assert c[k] == m[k]
    assert c["clock_correction"] == "applied"
    assert ag.clock_correct(dict(m, clock_rate_ratio=None))["clock_correction"] == "unavailable"


def test_stream_pairing_mismatch_fails_loudly(tmp_path):
    prefix, meta = stream_run(tmp_path, mismatch=True)
    with pytest.raises(SystemExit, match="does not match"):
        ag.run_metrics(prefix, "fastapi", "stream", 2, meta["service_time_s"], CAL, meta)


def test_missing_monotonic_columns_fail_loudly(tmp_path):
    prefix, meta = stream_run(tmp_path, drop_mono=True)
    with pytest.raises(SystemExit, match="monotonic"):
        ag.run_metrics(prefix, "fastapi", "stream", 2, meta["service_time_s"], CAL, meta)
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "aggregate_v2.py"), "--data",
                          str(tmp_path / "data"), "--out", str(tmp_path / "out")], capture_output=True, text=True)
    assert out.returncode != 0 and "monotonic" in out.stderr


def test_pipeline_completion_rate(tmp_path):
    s = CAL["service_time_s"]["pipeline"]
    kw = {"rtype": "POST", "name": "/api/pipeline"}
    reqs = [req_row(T0 + 3 + i, 2766.0, status=200, stages=4, length=1200, **kw) for i in range(6)]
    reqs.append(req_row(T0 + 10.5, 2766.0, status=200, stages=3, length=1200, **kw))
    reqs.append(req_row(T0 + 11.5, 3.0, ok=False, exc="CatchResponseError('HTTP 500')", status=500, stages="",
                        length=0, **kw))
    stage = {"timestamp": 0, "completed": True, "e2e_pipeline_ms": 2766.0, "stage1_ms": 0.0, "stage2_ms": 50.2,
             "stage3_ms": 2715.8, "stage4_ms": 0.001}
    fields = list(stage)
    prefix, meta = make_run(str(tmp_path / "data"), "tornado", "pipeline", 5, s, reqs,
                            {"pipeline_metrics": (fields, [stage] * 7)})
    m = ag.run_metrics(prefix, "tornado", "pipeline", 5, s, CAL, meta)
    assert m["pipeline_completion_pct"] == pytest.approx(6 / 8 * 100)
    assert m["error_rate_pct"] == pytest.approx(100 / 8)
    assert json.loads(m["failures_by_type"]) == {"HTTP 500": 1}
    assert m["stage2_p50_ms"] == pytest.approx(50.2) and m["e2e_server_p95_ms"] == pytest.approx(2766.0)
    assert m["e2e_client_p50_ms"] == pytest.approx(2766.0)


def test_cli_outputs_and_list_clock_steps(tmp_path):
    prefix, meta = stream_run(tmp_path)
    meta["clock_rate_unstable"] = True
    json.dump(meta, open(prefix + "_meta.json", "w"))
    agg = os.path.join(ROOT, "scripts", "aggregate_v2.py")
    out = subprocess.run([sys.executable, agg, "--data", str(tmp_path / "data"), "--out", str(tmp_path / "out"),
                          "--clock-correct"], capture_output=True, text=True, check=True)
    assert "12 content chunks AND done event seen" in out.stdout
    for name in ("per_run_v2.csv", "summary_v2.csv", "per_run_v2_clockcorrected.csv", "clock_rate_summary.csv",
                 "metric_rules.txt"):
        assert os.path.exists(tmp_path / "out" / name)
    wide = list(csv.DictReader(open(tmp_path / "out" / "summary_v2.csv")))[0]
    assert wide["clock_correction"] == "uncorrected" and wide["clock_flagged_runs"] == "1"
    lst = subprocess.run([sys.executable, agg, "--data", str(tmp_path / "data"), "--list-clock-steps"],
                         capture_output=True, text=True, check=True).stdout
    assert "clock_rate_unstable" in lst and "1 flagged run" in lst
