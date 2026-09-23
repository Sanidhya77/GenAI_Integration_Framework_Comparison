"""
Shared Locust instrumentation for the v2 rerun (loaded next to an unchanged test file):

  locust -f locust_tests/test_inference.py,locust_tests/request_log.py ...

1. Per-request log (all endpoints): one row per completed request, written to
   <csv_prefix>_requests.csv at exit, with start and end wall-clock times, response
   time, name, type, success, exception and a per-user id. Start = end - response time.
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
   stop time, number of users started and completed rows.
"""

import csv
import json
import os
import time

import gevent
from locust import events

UNIFORM_SPAWN = os.environ.get("UNIFORM_SPAWN", "1") == "1"

_rows = []
_users = {}  # user id -> {"first_start": t, "issued": t, "completed": n}
_state = {"k": 0, "t0": None, "stop": None, "spawn_rate": None}


def _uid():
    return id(gevent.getcurrent())


def _wrap_on_start(cls):
    original = cls.on_start

    def on_start(self):
        k = _state["k"]
        _state["k"] += 1
        now = time.time()
        if _state["t0"] is None:
            _state["t0"] = now
        rate = _state["spawn_rate"]
        if UNIFORM_SPAWN and rate:
            target = _state["t0"] + k / rate
            if target > now:
                gevent.sleep(target - now)
        t = time.time()
        _users[_uid()] = {"index": k, "first_start": t, "issued": t, "completed": 0}
        original(self)

    cls.on_start = on_start


@events.init.add_listener
def _on_init(environment, **_kwargs):
    opts = getattr(environment, "parsed_options", None)
    _state["spawn_rate"] = float(opts.spawn_rate) if opts and opts.spawn_rate else None
    for cls in environment.user_classes:
        _wrap_on_start(cls)


@events.request.add_listener
def _on_request(request_type, name, response_time, response_length, exception=None, **_kwargs):
    end = time.time()
    uid = _uid()
    user = _users.get(uid)
    _rows.append({
        "start_ts": round(end - (response_time or 0) / 1000.0, 6),
        "end_ts": round(end, 6),
        "response_time_ms": round(response_time or 0, 3),
        "request_type": request_type,
        "name": name,
        "success": exception is None,
        "exception": "" if exception is None else repr(exception)[:200],
        "response_length": response_length,
        "user": user["index"] if user else "",
    })
    if user:
        user["issued"] = end
        user["completed"] += 1


@events.test_stopping.add_listener
def _on_stopping(**_kwargs):
    if _state["stop"] is None:
        _state["stop"] = time.time()


@events.quitting.add_listener
def _on_quitting(environment, **_kwargs):
    opts = getattr(environment, "parsed_options", None)
    prefix = opts.csv_prefix if opts and opts.csv_prefix else "run"
    stop = _state["stop"] or time.time()

    with open(f"{prefix}_requests.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["start_ts", "end_ts", "response_time_ms", "request_type", "name",
                                          "success", "exception", "response_length", "user"])
        w.writeheader()
        w.writerows(_rows)

    with open(f"{prefix}_inflight.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["user", "issued_ts", "age_at_stop_s", "completed_before"])
        w.writeheader()
        for u in sorted(_users.values(), key=lambda x: x["index"]):
            if u["issued"] <= stop:
                w.writerow({"user": u["index"], "issued_ts": round(u["issued"], 6),
                            "age_at_stop_s": round(stop - u["issued"], 6), "completed_before": u["completed"]})

    with open(f"{prefix}_locust_meta.json", "w", encoding="utf-8") as f:
        json.dump({
            "spawn_rate": _state["spawn_rate"],
            "uniform_spawn": UNIFORM_SPAWN,
            "first_user_start_ts": _state["t0"],
            "stop_ts": stop,
            "users_started": len(_users),
            "completed_rows": len(_rows),
        }, f, indent=2)
