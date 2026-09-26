"""
Shared Locust instrumentation for the v2 rerun (loaded next to an unchanged test file):

  locust -f locust_tests/test_inference.py,locust_tests/request_log.py ...

1. Per-request log (all endpoints): one row per completed request, written to
   <csv_prefix>_requests.csv at exit, with start and end times, response time, name,
   type, success, exception, a per-user id, the HTTP status and, for the pipeline, the
   number of the four stage timings present in the response. Start = end - response time.
2. In-flight requests at stop: with zero wait time every user always has one
   request outstanding. At test stop each user's outstanding request (issued at its
   last completion, or at its first task start) is written to <csv_prefix>_inflight.csv
   with its age at stop; these are the right-censored observations.
3. Uniform spawn (C-C). Locust 2.43.4 spawns users in batches of max(1, floor(r))
   every floor(r)/r seconds (locust/dispatch.py:203-205), so r = c / S at c = 100
   still starts 34 users at once. With UNIFORM_SPAWN=1 (default) the k-th user's
   first task is delayed until t0 + k / r, where t0 is the first user's start, so
   first requests are spaced 1 / r apart. The spawn rate itself is unchanged.
4. <csv_prefix>_locust_meta.json with spawn rate, uniform spawn flag, first start,
   stop time, number of users started and completed rows, and (wall, monotonic) anchor
   pairs at init and at quit.

Clock: every time that is compared across processes or used for a window, an age or the
pacing schedule is time.monotonic() (CLOCK_MONOTONIC, shared by all processes in one boot):
start_mono, end_mono, issued_mono, age_at_stop_s, first_user_start_mono, stop_mono.
The *_ts columns are the wall clock (time.time()) and are labels only.

http_status: response.status_code when Locust passes the response (inference, pipeline);
otherwise the n of an "HTTP n" exception (stream non-200); otherwise empty.
stages_logged: pipeline only, how many of the four stage*_ms keys are in stage_timings.
"""

import csv
import json
import os
import re
import time

import gevent
from locust import events

UNIFORM_SPAWN = os.environ.get("UNIFORM_SPAWN", "1") == "1"

_rows = []
_users = {}  # user id -> {"first_start": t, "issued": t, "completed": n}
_state = {"k": 0, "t0": None, "t0_mono": None, "stop": None, "stop_mono": None, "spawn_rate": None,
          "anchor_init": None}
STAGE_KEYS = ("stage1_query_analysis_ms", "stage2_context_retrieval_ms", "stage3_augmented_inference_ms",
              "stage4_postprocessing_ms")
HTTP_RE = re.compile(r"HTTP (\d{3})")


def _anchor():
    return {"wall": time.time(), "mono": time.monotonic()}


def _uid():
    return id(gevent.getcurrent())


def _wrap_on_start(cls):
    original = cls.on_start

    def on_start(self):
        k = _state["k"]
        _state["k"] += 1
        now = time.monotonic()
        if _state["t0_mono"] is None:
            _state["t0_mono"] = now
            _state["t0"] = time.time()
        rate = _state["spawn_rate"]
        if UNIFORM_SPAWN and rate:
            target = _state["t0_mono"] + k / rate
            if target > now:
                gevent.sleep(target - now)
        t = time.monotonic()
        _users[_uid()] = {"index": k, "first_start": t, "issued": t, "issued_ts": time.time(), "completed": 0}
        original(self)

    cls.on_start = on_start


@events.init.add_listener
def _on_init(environment, **_kwargs):
    opts = getattr(environment, "parsed_options", None)
    _state["spawn_rate"] = float(opts.spawn_rate) if opts and opts.spawn_rate else None
    _state["anchor_init"] = _anchor()
    for cls in environment.user_classes:
        _wrap_on_start(cls)


def _http_status(response, exception):
    code = getattr(response, "status_code", None)
    if code is not None:
        return code
    m = HTTP_RE.search(str(exception)) if exception is not None else None
    return int(m.group(1)) if m else ""


def _stages_logged(name, response):
    if name != "/api/pipeline" or getattr(response, "status_code", None) != 200:
        return ""
    try:
        st = response.json().get("stage_timings") or {}
        return sum(1 for k in STAGE_KEYS if isinstance(st.get(k), (int, float)))
    except Exception:  # noqa: BLE001 - unparsable body: no stage logged
        return 0


@events.request.add_listener
def _on_request(request_type, name, response_time, response_length, exception=None, response=None, **_kwargs):
    end_mono = time.monotonic()
    end = time.time()
    rt_s = (response_time or 0) / 1000.0
    uid = _uid()
    user = _users.get(uid)
    _rows.append({
        "start_ts": round(end - rt_s, 6),
        "end_ts": round(end, 6),
        "start_mono": round(end_mono - rt_s, 6),
        "end_mono": round(end_mono, 6),
        "response_time_ms": round(response_time or 0, 3),
        "request_type": request_type,
        "name": name,
        "success": exception is None,
        "exception": "" if exception is None else repr(exception)[:200],
        "response_length": response_length,
        "user": user["index"] if user else "",
        "http_status": _http_status(response, exception),
        "stages_logged": _stages_logged(name, response),
    })
    if user:
        user["issued"] = end_mono
        user["issued_ts"] = end
        user["completed"] += 1


@events.test_stopping.add_listener
def _on_stopping(**_kwargs):
    if _state["stop_mono"] is None:
        _state["stop_mono"] = time.monotonic()
        _state["stop"] = time.time()


@events.quitting.add_listener
def _on_quitting(environment, **_kwargs):
    opts = getattr(environment, "parsed_options", None)
    prefix = opts.csv_prefix if opts and opts.csv_prefix else "run"
    if _state["stop_mono"] is None:
        _state["stop_mono"] = time.monotonic()
        _state["stop"] = time.time()
    stop = _state["stop_mono"]

    with open(f"{prefix}_requests.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["start_ts", "end_ts", "start_mono", "end_mono", "response_time_ms",
                                          "request_type", "name", "success", "exception", "response_length", "user",
                                          "http_status", "stages_logged"])
        w.writeheader()
        w.writerows(_rows)

    with open(f"{prefix}_inflight.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["user", "issued_ts", "issued_mono", "age_at_stop_s", "completed_before"])
        w.writeheader()
        for u in sorted(_users.values(), key=lambda x: x["index"]):
            if u["issued"] <= stop:
                w.writerow({"user": u["index"], "issued_ts": round(u["issued_ts"], 6),
                            "issued_mono": round(u["issued"], 6), "age_at_stop_s": round(stop - u["issued"], 6),
                            "completed_before": u["completed"]})

    with open(f"{prefix}_locust_meta.json", "w", encoding="utf-8") as f:
        json.dump({
            "spawn_rate": _state["spawn_rate"],
            "uniform_spawn": UNIFORM_SPAWN,
            "first_user_start_ts": _state["t0"],
            "first_user_start_mono": _state["t0_mono"],
            "stop_ts": _state["stop"],
            "stop_mono": stop,
            "users_started": len(_users),
            "completed_rows": len(_rows),
            "anchor_init": _state["anchor_init"],
            "anchor_quit": _anchor(),
        }, f, indent=2)
