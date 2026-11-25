"""Integration script: drives a running instrument API end to end. Usage: python scripts/api_integration.py http://127.0.0.1:8000"""
import sys

import httpx


def run(base: str) -> list[tuple[str, bool]]:
    c = httpx.Client(base_url=base, timeout=10)
    out = []
    check = lambda name, cond: out.append((name, bool(cond)))  # noqa: E731
    for s in ("INT-1", "INT-2"):
        check(f"load {s}", c.post("/api/samples", json={"sample_id": s}).status_code == 201)
    run_id = c.post("/api/runs/start").json().get("run_id")
    check("run started", c.get("/api/status").json()["state"] == "RUNNING")
    temps = [c.get("/api/sensors").json()["temperature_c"] for _ in range(5)]
    check("temperature in 37.0 +/- 0.5", all(abs(t - 37) <= 0.5 for t in temps))
    check("run stopped", c.post("/api/runs/stop").json()["run_id"] == run_id)
    check("run persisted", any(r["id"] == run_id and r["status"] == "COMPLETED" for r in c.get("/api/runs").json()))
    c.post("/api/samples", json={"sample_id": "INT-3"})
    c.post("/api/runs/start")
    c.post("/api/faults", json={"fault": "door_open"})
    c.get("/api/sensors")
    check("door fault raises E103", c.get("/api/status").json()["error"] == "E103")
    c.delete("/api/faults")
    check("reset recovers", c.post("/api/reset").json()["state"] == "IDLE")
    c.delete("/api/samples/INT-3")
    return out


if __name__ == "__main__":
    results = run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    sys.exit(0 if all(ok for _, ok in results) else 1)
