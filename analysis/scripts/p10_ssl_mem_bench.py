"""RSS cost of N simultaneously-alive httpx.AsyncClient objects (no network). Compare with
the observed async RSS jump in the first simulated run at each c."""
import asyncio, gc, psutil, httpx
p = psutil.Process()
async def main():
    for n in (25, 50, 100):
        gc.collect(); base = p.memory_info().rss
        cs = [httpx.AsyncClient() for _ in range(n)]
        held = p.memory_info().rss
        for c in cs: await c.aclose()
        del cs; gc.collect(); after = p.memory_info().rss
        print(f"n={n:3d} alive clients: +{(held-base)/2**20:6.1f} MB ({(held-base)/2**20/n:.2f} MB/client); after close+gc: +{(after-base)/2**20:6.1f} MB retained")
asyncio.run(main())
