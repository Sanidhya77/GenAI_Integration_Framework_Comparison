"""Clock guards (no servers): clock-step detection with mocked clocks, host-clock rate
arithmetic, idle-memory window, time-sync preflight and the --redo-clock-steps rule."""
import csv
import json
import os
import random
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "monitoring"))

import hostclock  # noqa: E402
import resource_monitor_v2 as mon  # noqa: E402
import run_matrix as rm  # noqa: E402


class FakeClocks:
    """Monotonic advances 0.25 s per sample; wall = monotonic + base + wall_shift(i).

    read_offset() reads monotonic, wall, monotonic: the first monotonic read of a sample
    advances 0.25 s, the second 10 µs (so no retry), the wall read advances the index."""

    def __init__(self, wall_shift):
        self.mono = 5000.0
        self.calls = 0
        self.i = 0
        self.wall_shift = wall_shift

    def monotonic(self):
        self.calls += 1
        self.mono += 0.25 if self.calls % 2 else 0.00001
        return self.mono

    def time(self):
        w = self.mono + 1.7e9 + self.wall_shift(self.i)
        self.i += 1
        return w


def offsets_with(monkeypatch, wall_shift, n=240):
    fake = FakeClocks(wall_shift)
    monkeypatch.setattr(mon, "time", types.SimpleNamespace(monotonic=fake.monotonic, time=fake.time))
    return [mon.read_offset()[1] for _ in range(n)]


def test_clock_step_600ms_detected(monkeypatch):
    offs = offsets_with(monkeypatch, lambda i: 0.6 if i >= 70 else 0.0)
    detected, step_ms = rm.detect_clock_step(offs)
    assert detected
    assert step_ms == pytest.approx(600, abs=1)


def test_clock_jitter_5ms_not_detected(monkeypatch):
    rnd = random.Random(1)
    offs = offsets_with(monkeypatch, lambda i: rnd.uniform(-0.005, 0.005))
    detected, step_ms = rm.detect_clock_step(offs)
    assert not detected
    assert step_ms <= 10.1
    alternating = offsets_with(monkeypatch, lambda i: 0.005 if i % 2 else -0.005)
    assert rm.detect_clock_step(alternating)[0] is False


def test_clock_step_threshold_and_edge_cases():
    assert rm.detect_clock_step([0.0, 0.025])[0] is True
    assert rm.detect_clock_step([0.0, 0.019])[0] is False
    assert rm.detect_clock_step([0.1]) == (False, 0.0)
    assert rm.detect_clock_step([None, 0.1, None]) == (False, 0.0)


def test_monitor_csv_offsets_feed_detector(tmp_path):
    path = tmp_path / "x_resources.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "mono", "elapsed_s", "wall_minus_mono_s", "rss_mb", "uss_mb", "cpu_percent",
                    "n_procs"])
        for i in range(10):
            w.writerow([0, 100 + i * 0.25, i * 0.25, 1.7e9 + (0.614 if i > 5 else 0.0), 60, 45, 1.0, 1])
    detected, step_ms = rm.detect_clock_step(rm.monitor_offsets(str(path)))
    assert detected and step_ms == pytest.approx(614, abs=0.01)


def mk(host, mono_mid, lat=0.01):
    return {"host_ts": host, "mono_mid": mono_mid, "mono_before": mono_mid - lat / 2,
            "mono_after": mono_mid + lat / 2, "latency_s": lat}


def test_hostclock_rate_math():
    r = hostclock.rate(mk(1000.0, 50.0), mk(1030.0, 50.0 + 30 * 0.98), mk(1060.0, 50.0 + 60 * 0.98))
    assert r["clock_rate_ratio"] == pytest.approx(0.98)
    assert r["clock_rate_uncertainty"] == pytest.approx((0.005 + 0.005 + 0.032) / 60)
    assert r["clock_rate_half_diff"] == pytest.approx(0.0, abs=1e-12)
    assert r["clock_rate_unstable"] is False
    assert r["clock_rate_off_nominal"] is True

    r = hostclock.rate(mk(0.0, 0.0), mk(30.0, 30.0), mk(60.0, 30.0 + 30 * 1.01))
    assert r["clock_rate_ratio_first_half"] == pytest.approx(1.0)
    assert r["clock_rate_ratio_second_half"] == pytest.approx(1.01)
    assert r["clock_rate_unstable"] is True
    assert r["clock_rate_off_nominal"] is True  # 1.005

    r = hostclock.rate(mk(0.0, 0.0), None, mk(60.0, 60.03))
    assert r["clock_rate_ratio"] == pytest.approx(1.0005)
    assert r["clock_rate_off_nominal"] is False and r["clock_rate_unstable"] is None
    assert all(v is None for v in hostclock.rate(None, None, mk(1, 1)).values())


def test_hostclock_read_and_failure(tmp_path):
    s = hostclock.sample(directory=str(tmp_path))
    assert s["mono_before"] <= s["mono_mid"] <= s["mono_after"] and s["latency_s"] >= 0
    assert os.listdir(tmp_path) == []  # always unlinked
    assert hostclock.sample(directory=str(tmp_path / "missing")) is None


def write_resources(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "mono", "elapsed_s", "wall_minus_mono_s", "rss_mb", "uss_mb", "cpu_percent",
                    "n_procs"])
        for mono, rss, uss in rows:
            w.writerow([0, mono, 0, 0, rss, uss, 0, 1])


def test_idle_memory_uses_2s_lead(tmp_path):
    p = tmp_path / "c5_run1_resources.csv"
    write_resources(p, [(9.5, 99, 99), (10.0, 60.0, 45.0), (10.25, 60.2, 45.1), (11.75, 60.4, 45.2),
                        (12.0, 80, 70), (13, 90, 80)])
    rss, uss, n = rm.idle_memory(str(p), 12.0)
    assert (rss, uss, n) == (60.2, 45.1, 3)


def test_idle_reference_lowest_complete_run(tmp_path):
    for run, status, rss in ((3, "complete", 61.0), (2, "complete", 60.0), (1, "started", 59.0)):
        with open(tmp_path / f"c5_run{run}_meta.json", "w") as f:
            json.dump({"run": run, "status": status, "idle_rss_mb": rss, "idle_uss_mb": rss - 15}, f)
    assert rm.idle_reference(str(tmp_path / "c5_run4"), 4) == (2, 60.0, 45.0)
    assert rm.idle_reference(str(tmp_path / "c5_run2"), 2) == (3, 61.0, 46.0)


def test_timesync_preflight_rule():
    base = {"timesync_state": {"systemd-timesyncd": "inactive", "chronyd": "inactive", "ntp": "inactive"},
            "apt_timers": {"apt-daily.timer": "active", "apt-daily-upgrade.timer": "inactive"},
            "allow_timesync": False}
    assert rm.timesync_problem(base) is None
    assert "apt-daily.timer" in rm.apt_warning(base)
    active = dict(base, timesync_state=dict(base["timesync_state"], **{"systemd-timesyncd": "active"}))
    assert "systemd-timesyncd" in rm.timesync_problem(active)
    assert rm.timesync_problem(dict(active, allow_timesync=True)) is None


def test_redo_clock_steps_marks_flagged_runs_incomplete(tmp_path):
    prefix = str(tmp_path / "c1_run1")
    for p in rm.expected_files(prefix, "inference", "sim"):
        open(p, "w").close()
    meta = {"status": "complete", "clock_step_detected": False, "clock_rate_unstable": False,
            "clock_rate_off_nominal": True}
    with open(prefix + "_meta.json", "w") as f:
        json.dump(meta, f)
    assert rm.run_complete(prefix, "inference", "sim") is True
    assert rm.run_complete(prefix, "inference", "sim", redo_clock_steps=True) is False
    os.remove(prefix + "_sim_monitor.csv")
    assert rm.run_complete(prefix, "inference", "real") is True  # no simulator monitor in real mode
    assert rm.run_complete(prefix, "inference", "sim") is False
