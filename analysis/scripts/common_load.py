"""Shared loaders for the audit. Read-only access to data/ and logs/."""
import csv
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data")
LOGS = os.path.join(ROOT, "logs")
FWS = ["flask", "django", "fastapi", "tornado"]
SYNC = ["flask", "django"]
ASYNC = ["fastapi", "tornado"]
EPS = ["inference", "stream", "pipeline"]
CS = [1, 5, 10, 25, 50, 100]
RUNS = [1, 2, 3, 4, 5]
SIM_DELAY_S = 2.878
SIM_CHUNKS = 12
SIM_CHUNK_INTERVAL_S = 0.2
RETRIEVAL_S = 0.05


def path(fw, ep, c, r, suffix):
    return os.path.join(DATA, fw, ep, f"c{c}_run{r}_{suffix}.csv")


def rows(p):
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def stats_rows(fw, ep, c, r):
    rs = rows(path(fw, ep, c, r, "stats"))
    named = [x for x in rs if x["Name"] != "Aggregated"]
    agg = [x for x in rs if x["Name"] == "Aggregated"]
    return (named[0] if named else None), (agg[0] if agg else None)


def history(fw, ep, c, r):
    return rows(path(fw, ep, c, r, "stats_history"))


def stream_metrics(fw, c, r):
    out = []
    for x in rows(path(fw, "stream", c, r, "stream_metrics")):
        out.append({
            "timestamp": float(x["timestamp"]),
            "ttft_ms": float(x["ttft_ms"]) if x["ttft_ms"] not in ("", "None") else None,
            "tpot_ms": float(x["tpot_ms"]) if x["tpot_ms"] not in ("", "None") else None,
            "total_time_ms": float(x["total_time_ms"]),
            "token_count": int(x["token_count"]),
            "success": x["success"] == "True",
        })
    return out


def pipeline_metrics(fw, c, r):
    out = []
    for x in rows(path(fw, "pipeline", c, r, "pipeline_metrics")):
        def f(k):
            v = x.get(k)
            return float(v) if v not in (None, "", "None") else None
        out.append({
            "timestamp": float(x["timestamp"]),
            "completed": x["completed"] == "True",
            "e2e": f("e2e_pipeline_ms"), "s1": f("stage1_ms"), "s2": f("stage2_ms"),
            "s3": f("stage3_ms"), "s4": f("stage4_ms"),
        })
    return out


def resources(fw, ep, c, r):
    return [{k: float(v) for k, v in x.items()} for x in rows(path(fw, ep, c, r, "resources"))]


def jsonl(fw):
    p = os.path.join(LOGS, fw, "pipeline_timing.jsonl")
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def pct(v, p):
    """Same indexing rule as scripts/aggregate_data.py safe_percentile."""
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    return v[min(int(len(v) * p / 100), len(v) - 1)]


def is_sim(c):
    return c >= 25
