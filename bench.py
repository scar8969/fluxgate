"""Load test for FluxGate — measures real throughput + latency.

Hammers the API with concurrent requests and reports:
  - requests/second
  - p50 / p95 / p99 latency (ms)
  - error rate

Usage:
    .venv/Scripts/python bench.py --url http://127.0.0.1:5000 --requests 500 --concurrency 20
"""
import argparse
import concurrent.futures
import statistics
import time
import urllib.request
import urllib.error


def hit(url: str) -> float:
    """One request, returns latency in ms. Raises on non-200."""
    start = time.perf_counter()
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"status {resp.status}")
    return (time.perf_counter() - start) * 1000


def main():
    ap = argparse.ArgumentParser(description="FluxGate load test")
    ap.add_argument("--url", default="http://127.0.0.1:5000/api/metrics")
    ap.add_argument("--requests", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=20)
    args = ap.parse_args()

    print(f"[bench] {args.requests} requests x {args.concurrency} concurrent -> {args.url}")
    latencies = []
    errors = 0
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = [ex.submit(hit, args.url) for _ in range(args.requests)]
        for f in concurrent.futures.as_completed(futures):
            try:
                latencies.append(f.result())
            except Exception:
                errors += 1
    elapsed = time.perf_counter() - start

    if latencies:
        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95) - 1]
        p99 = latencies[int(len(latencies) * 0.99) - 1]
        rps = args.requests / elapsed
        print(f"[bench] done in {elapsed:.2f}s")
        print(f"[bench] throughput: {rps:.0f} req/s")
        print(f"[bench] latency: p50={p50:.1f}ms  p95={p95:.1f}ms  p99={p99:.1f}ms")
        print(f"[bench] errors: {errors}/{args.requests} ({errors / args.requests * 100:.1f}%)")
    else:
        print(f"[bench] all {errors} requests failed")


if __name__ == "__main__":
    main()
