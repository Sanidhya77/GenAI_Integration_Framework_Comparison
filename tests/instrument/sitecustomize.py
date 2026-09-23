"""Test-only instrumentation (T2), active only when this directory is on PYTHONPATH and
CONSTRUCTION_LOG is set: logs every httpx.Client / httpx.AsyncClient / Anthropic /
AsyncAnthropic construction as one JSON line (pid, class, time)."""
import json
import os
import time

_LOG = os.environ.get("CONSTRUCTION_LOG")

if _LOG:
    import anthropic
    import httpx

    def _wrap(cls):
        original = cls.__init__

        def __init__(self, *args, **kwargs):
            with open(_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "cls": cls.__name__, "ts": time.time()}) + "\n")
            original(self, *args, **kwargs)

        cls.__init__ = __init__

    for _cls in (httpx.Client, httpx.AsyncClient, anthropic.Anthropic, anthropic.AsyncAnthropic):
        _wrap(_cls)
