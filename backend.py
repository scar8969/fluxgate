"""Sample backend node agent — the missing piece the original never shipped.

A real proxy backend polls the panel for its config, simulates user traffic
with a diurnal pattern, and reports usage back (which doubles as a heartbeat).
Run one per node:

    .venv/Scripts/python backend.py --node 1 --users 5

This makes the whole system end-to-end: panel <-> backend agent <-> traffic.
"""
import argparse
import random
import time
import urllib.request
import json
from datetime import datetime

PANEL = "http://127.0.0.1:5000"
API_TOKEN = "dev-api-token"


def diurnal(hour: int) -> float:
    """Traffic multiplier peaking at 21:00, trough at 05:00."""
    import math
    return 0.25 + 0.75 * (0.5 - 0.5 * math.cos(2 * math.pi * (hour - 21) / 24))


def api(path, data=None):
    req = urllib.request.Request(
        f"{PANEL}{path}",
        data=json.dumps(data).encode() if data else None,
        headers={"X-API-Token": API_TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser(description="FluxGate sample backend agent")
    ap.add_argument("--node", type=int, default=1, help="node id to serve")
    ap.add_argument("--users", type=int, default=5, help="simulated users on this node")
    ap.add_argument("--interval", type=int, default=30, help="report interval seconds")
    ap.add_argument("--once", action="store_true", help="run a single report and exit")
    args = ap.parse_args()

    print(f"[backend] serving node {args.node} -> {PANEL}")
    while True:
        try:
            # 1. pull config
            cfg = api(f"/api/proxy_configs/{args.node}")
            # 2. generate traffic report for simulated users
            now = datetime.utcnow()
            mult = diurnal(now.hour)
            data = []
            for uid in range(2, 2 + args.users):  # demo users start at id 2
                up = int(random.uniform(0.5, 3) * 1024 * 1024 * mult)
                down = int(random.uniform(1, 8) * 1024 * 1024 * mult)
                data.append({"user_id": uid, "upload": up, "download": down})
            # 3. report (also heartbeat)
            api(f"/api/proxy_configs/{args.node}", {"data": data})
            total = sum(i["upload"] + i["download"] for i in data)
            print(f"[backend] {now:%H:%M:%S} node={cfg['name']} reported "
                  f"{total / 1024 / 1024:.1f} MB ({len(data)} users)")
        except Exception as e:
            print(f"[backend] error: {e}")
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
