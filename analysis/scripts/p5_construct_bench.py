"""Micro-benchmark (no network I/O, no servers): cost of constructing httpx clients as done per request
in common/anthropic_client.py:165 (httpx.post -> Client), :175 (httpx.stream -> Client), :199/:210 (AsyncClient).
Also measures ssl.create_default_context(cafile=certifi.where()), which httpx calls in its transport __init__."""
import asyncio, ssl, statistics, time
import certifi, httpx
def bench(fn, n=60):
    fn()  # warm imports
    t = []
    for _ in range(n):
        a = time.perf_counter(); fn(); t.append((time.perf_counter() - a) * 1000)
    return statistics.median(t), min(t), max(t)
def sync_client():
    c = httpx.Client(); c.close()
def async_client():
    async def f():
        async with httpx.AsyncClient():
            pass
    asyncio.run(f())
async def async_ctor_only_loop(n=60):
    t = []
    for _ in range(n):
        a = time.perf_counter(); c = httpx.AsyncClient(); t.append((time.perf_counter() - a) * 1000); await c.aclose()
    return statistics.median(t), min(t), max(t)
print("ssl.create_default_context(certifi) ms (median,min,max):", bench(lambda: ssl.create_default_context(cafile=certifi.where())))
print("httpx.Client() + close ms:", bench(sync_client))
print("httpx.AsyncClient() ctor inside running loop ms:", asyncio.run(async_ctor_only_loop()))
print("httpx version", httpx.__version__, "certifi bundle", certifi.where())
