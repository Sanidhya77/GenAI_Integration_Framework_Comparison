"""
Resource monitor for the v2 rerun (the thesis monitor, resource_monitor.py, is kept unchanged).

Samples every --interval seconds (default 0.25):
  rss_mb   resident set size
  uss_mb   unique set size (memory freed if the process exited)
  cpu_percent  CPU since the previous sample (100 = one core)
With --tree the values are summed over the PID and all its descendants
(Gunicorn master + workers in the multi-worker arm).

Clock: the schedule, elapsed_s and the mono column use time.monotonic() (CLOCK_MONOTONIC,
shared by all processes in one boot), so a wall-clock step cannot shift samples or windows.
timestamp is the wall clock, a label only. wall_minus_mono_s = time.time() - time.monotonic()
at each sample; a change of more than 20 ms within a run is a clock step (run_matrix.py).
psutil's cpu_percent() already measures its interval with time.monotonic().

Stops on SIGINT/SIGTERM or when the process exits.

Usage:
  python monitoring/resource_monitor_v2.py --pid <PID> --output <CSV> [--interval 0.25] [--tree]

Output CSV columns:
  timestamp, mono, elapsed_s, wall_minus_mono_s, rss_mb, uss_mb, cpu_percent, n_procs
"""

import argparse
import csv
import os
import signal
import time

import psutil

MB = 1024 * 1024
OFFSET_READ_MAX_S = 0.001


def read_offset(retries=3):
    """(mono, wall - mono), reading the wall clock between two monotonic reads.

    A pair is retried when the two monotonic reads are more than 1 ms apart (preemption),
    so the offset error stays far below the 20 ms step threshold."""
    best = None
    for _ in range(retries):
        m0 = time.monotonic()
        w = time.time()
        m1 = time.monotonic()
        mid = (m0 + m1) / 2
        if best is None or m1 - m0 < best[2]:
            best = (mid, w - mid, m1 - m0)
        if m1 - m0 <= OFFSET_READ_MAX_S:
            break
    return best[0], best[1]


def procs(root, tree):
    if not tree:
        return [root]
    try:
        return [root] + root.children(recursive=True)
    except psutil.NoSuchProcess:
        return [root]


def sample(root, tree, cache):
    rss = uss = cpu = 0.0
    alive = 0
    for p in procs(root, tree):
        # reuse Process objects so cpu_percent() measures since the previous sample
        p = cache.setdefault(p.pid, p)
        try:
            with p.oneshot():
                mem = p.memory_full_info()
                c = p.cpu_percent()
            rss += mem.rss
            uss += mem.uss
            cpu += c
            alive += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rss / MB, uss / MB, cpu, alive


def monitor(pid, output_path, interval, tree):
    root = psutil.Process(pid)
    cache = {}
    for p in procs(root, tree):
        cache.setdefault(p.pid, p).cpu_percent()  # prime the CPU counters

    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    start = time.monotonic()
    next_t = start
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "mono", "elapsed_s", "wall_minus_mono_s", "rss_mb", "uss_mb", "cpu_percent",
                    "n_procs"])
        rss, uss, _, n = sample(root, tree, cache)
        mono, off = read_offset()
        w.writerow([round(mono + off, 3), round(mono, 6), 0.0, round(off, 6), round(rss, 2), round(uss, 2), 0.0, n])
        while running:
            next_t += interval
            time.sleep(max(0.0, next_t - time.monotonic()))
            if not root.is_running():
                break
            rss, uss, cpu, n = sample(root, tree, cache)
            mono, off = read_offset()
            w.writerow([round(mono + off, 3), round(mono, 6), round(mono - start, 3), round(off, 6), round(rss, 2),
                        round(uss, 2), round(cpu, 1), n])
            f.flush()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Sample RSS, USS and CPU of a process (or process tree)")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--interval", type=float, default=0.25)
    ap.add_argument("--tree", action="store_true", help="sum over the process and all descendants")
    a = ap.parse_args()
    monitor(a.pid, a.output, a.interval, a.tree)
