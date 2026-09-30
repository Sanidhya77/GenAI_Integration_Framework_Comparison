"""
Offline reference clock for WSL2: the Windows host clock, read through a file timestamp.

A new file is created on /mnt/c (O_CREAT | O_EXCL), 1 byte is written, the file is closed,
os.stat().st_mtime is read and the file is unlinked. Windows sets the timestamp, so it is
the host clock. time.monotonic() is read before and after; the midpoint is the guest time
of the read. Method validated against PowerShell (~/paper_context/hostclock_test.py):
slopes agree to 0.00003; latency median 14 ms, max 33 ms. No internet is needed.

sample() takes 3 reads and keeps the one with the lowest latency.
rate(start, mid, end) compares guest monotonic time with host time over a Locust run:
  clock_rate_ratio        = (mono_mid_end - mono_mid_start) / (host_end - host_start)
  clock_rate_uncertainty  = (latency_start / 2 + latency_end / 2 + 0.032) / (host_end - host_start)
                            (0.032 s allows a 16 ms timestamp granularity at each end)
  clock_rate_half_diff    = |ratio of the first half - ratio of the second half|
  clock_rate_unstable     = half_diff > 0.005
  clock_rate_off_nominal  = |ratio - 1| > 0.002
A ratio below 1 means the guest monotonic clock runs slow against the host.
Every failure returns None; callers record null and never abort a run.
"""

import os
import time

HOST_DIR = "/mnt/c/Users/Public"
READS_PER_SAMPLE = 3
GRANULARITY_ALLOWANCE_S = 0.032
UNSTABLE_HALF_DIFF = 0.005
OFF_NOMINAL = 0.002

_counter = 0


def read_once(directory=HOST_DIR):
    """One host-clock read: {mono_before, mono_after, mono_mid, host_ts, latency_s}."""
    global _counter
    _counter += 1
    path = os.path.join(directory, f"hostclock_{os.getpid()}_{time.monotonic_ns()}_{_counter}.tmp")
    m0 = time.monotonic()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, b"x")
        finally:
            os.close(fd)
        host = os.stat(path).st_mtime
        m1 = time.monotonic()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return {"mono_before": m0, "mono_after": m1, "mono_mid": (m0 + m1) / 2, "host_ts": host,
            "latency_s": m1 - m0}


def sample(reads=READS_PER_SAMPLE, directory=HOST_DIR):
    """Best of `reads` reads (lowest latency), or None on any failure."""
    try:
        got = [read_once(directory) for _ in range(reads)]
        return min(got, key=lambda r: r["latency_s"])
    except Exception:  # noqa: BLE001 - never abort a run for the reference clock
        return None


def _ratio(a, b):
    dh = b["host_ts"] - a["host_ts"]
    return (b["mono_mid"] - a["mono_mid"]) / dh if dh > 0 else None


def rate(start, mid, end):
    """Clock-rate fields for meta.json; every field None if a sample is missing."""
    out = {"clock_rate_ratio": None, "clock_rate_uncertainty": None, "clock_rate_ratio_first_half": None,
           "clock_rate_ratio_second_half": None, "clock_rate_half_diff": None, "clock_rate_unstable": None,
           "clock_rate_off_nominal": None}
    if not start or not end:
        return out
    dh = end["host_ts"] - start["host_ts"]
    ratio = _ratio(start, end)
    if ratio is None:
        return out
    out["clock_rate_ratio"] = ratio
    out["clock_rate_uncertainty"] = (start["latency_s"] / 2 + end["latency_s"] / 2 + GRANULARITY_ALLOWANCE_S) / dh
    out["clock_rate_off_nominal"] = abs(ratio - 1) > OFF_NOMINAL
    if mid:
        r1, r2 = _ratio(start, mid), _ratio(mid, end)
        out["clock_rate_ratio_first_half"], out["clock_rate_ratio_second_half"] = r1, r2
        if r1 is not None and r2 is not None:
            out["clock_rate_half_diff"] = abs(r1 - r2)
            out["clock_rate_unstable"] = out["clock_rate_half_diff"] > UNSTABLE_HALF_DIFF
    return out


if __name__ == "__main__":
    s = sample()
    print(s)
