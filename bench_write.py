"""Write-path stress test — POST traffic reports (backend agent simulation)."""
import concurrent.futures
import json
import statistics
import time
import urllib.request

API_TOKEN = "dev-api-token"


def report(node_id):
    body = json.dumps({
        "node_id": node_id,
        "upload": 1024 * 1024,
        "download": 2 * 1024 * 1024,
        "users": [{"id": 1, "upload": 512 * 1024, "download": 1024 * 1024}],
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:5000/api/proxy_configs/{node_id}",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Token": API_TOKEN},
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"status {resp.status}")
    return (time.perf_counter() - start) * 1000


def main():
    n, conc = 500, 20
    print(f"[write-bench] {n} traffic reports x {conc} concurrent")
    lat, err = [], 0
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
        futs = [ex.submit(report, (i % 3) + 1) for i in range(n)]
        for f in concurrent.futures.as_completed(futs):
            try:
                lat.append(f.result())
            except Exception:
                err += 1
    elapsed = time.perf_counter() - start
    lat.sort()
    p50 = statistics.median(lat)
    p95 = lat[int(len(lat) * 0.95) - 1]
    p99 = lat[int(len(lat) * 0.99) - 1]
    print(f"[write-bench] done in {elapsed:.2f}s")
    print(f"[write-bench] throughput: {n / elapsed:.0f} writes/s")
    print(f"[write-bench] latency: p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms")
    print(f"[write-bench] errors: {err}/{n} ({err / n * 100:.1f}%)")


if __name__ == "__main__":
    main()
