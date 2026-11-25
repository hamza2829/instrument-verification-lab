"""Repetitive checks: N start/stop cycles plus temperature statistics against a running API.
Usage: python scripts/repetitive_checks.py http://127.0.0.1:8000 --cycles 25 --out out/repetitive.json"""
import argparse
import json
import statistics
import sys
from pathlib import Path

import httpx


def run(base: str, cycles: int) -> dict:
    c = httpx.Client(base_url=base, timeout=10)
    failures, temps = [], []
    for i in range(cycles):
        ok = c.post("/api/samples", json={"sample_id": f"REP-{i}"}).status_code == 201
        ok &= c.post("/api/runs/start").status_code == 201
        temps += [c.get("/api/sensors").json()["temperature_c"] for _ in range(4)]
        ok &= c.post("/api/runs/stop").status_code == 200
        if not ok:
            failures.append(i)
    dev = max(abs(t - 37.0) for t in temps)
    return {"cycles": cycles, "failed_cycles": failures, "temp_mean": round(statistics.mean(temps), 3),
            "temp_stdev": round(statistics.stdev(temps), 3), "max_deviation": round(dev, 3),
            "passed": not failures and dev <= 0.5}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    p.add_argument("--cycles", type=int, default=25)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    summary = run(a.base, a.cycles)
    print(json.dumps(summary, indent=2))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(summary, indent=2))
    sys.exit(0 if summary["passed"] else 1)
