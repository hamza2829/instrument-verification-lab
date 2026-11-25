"""Simulated lab analysis instrument: state machine, sensors, faults, SQLite log."""
from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

SETPOINT_C = 37.0
CAPACITY = 8
OVERTEMP_C = 42.0
ERRORS = {"E101": "Over-temperature", "E102": "Temperature sensor dropout", "E103": "Door opened during run"}
FAULTS = ("overtemp", "sensor_dropout", "door_open")


@dataclass(frozen=True)
class BuildProfile:
    name: str
    temp_sigma: float  # sensor noise (deg C)
    door_interlock: bool
    persists_results: bool = True


BUILDS = {
    "prototype": BuildProfile("prototype", temp_sigma=0.6, door_interlock=False),
    "pre-series": BuildProfile("pre-series", temp_sigma=0.25, door_interlock=True),
    "series": BuildProfile("series", temp_sigma=0.08, door_interlock=True),
}


class InstrumentError(Exception):
    """Rejected command (maps to HTTP 409)."""


class Instrument:
    def __init__(self, build: str = "series", seed: int = 0, db: str = ":memory:"):
        if build not in BUILDS:
            raise ValueError(f"unknown build {build!r}")
        self.profile = BUILDS[build]
        self.rng = random.Random(seed)
        self.db = sqlite3.connect(db, check_same_thread=False)
        self.db.executescript(
            """CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, started TEXT, stopped TEXT, status TEXT, samples TEXT);
               CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, detail TEXT);"""
        )
        self.state = "IDLE"
        self.error: str | None = None
        self.samples: list[str] = []
        self.faults: set[str] = set()
        self.run_id: int | None = None

    # --- helpers -------------------------------------------------------------
    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def log(self, kind: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO events(ts, kind, detail) VALUES (?,?,?)", (self._now(), kind, detail))
        self.db.commit()

    def _raise_error(self, code: str) -> None:
        if self.state == "RUNNING":
            self._finish_run("ABORTED")
        self.state, self.error = "ERROR", code
        self.log("error", f"{code} {ERRORS[code]}")

    def _finish_run(self, status: str) -> None:
        self.db.execute("UPDATE runs SET stopped=?, status=? WHERE id=?", (self._now(), status, self.run_id))
        self.db.commit()
        self.run_id = None

    # --- samples -------------------------------------------------------------
    def load_sample(self, sample_id: str) -> None:
        if self.state == "RUNNING":
            raise InstrumentError("cannot load samples during a run")
        if not sample_id or sample_id in self.samples:
            raise InstrumentError(f"invalid or duplicate sample {sample_id!r}")
        if len(self.samples) >= CAPACITY:
            raise InstrumentError(f"rack full ({CAPACITY} positions)")
        self.samples.append(sample_id)
        self.log("sample_loaded", sample_id)

    def unload_sample(self, sample_id: str) -> None:
        if self.state == "RUNNING":
            raise InstrumentError("cannot unload samples during a run")
        if sample_id not in self.samples:
            raise InstrumentError(f"sample {sample_id!r} not loaded")
        self.samples.remove(sample_id)
        self.log("sample_unloaded", sample_id)

    # --- runs ----------------------------------------------------------------
    def start_run(self) -> int:
        if self.state == "ERROR":
            raise InstrumentError(f"instrument in error {self.error}; reset first")
        if self.state == "RUNNING":
            raise InstrumentError("run already in progress")
        if not self.samples:
            raise InstrumentError("no samples loaded")
        if self.profile.door_interlock and "door_open" in self.faults:
            raise InstrumentError("door open")
        cur = self.db.execute(
            "INSERT INTO runs(started, status, samples) VALUES (?,?,?)", (self._now(), "RUNNING", ",".join(self.samples))
        )
        self.db.commit()
        self.run_id, self.state = cur.lastrowid, "RUNNING"
        self.log("run_started", str(self.run_id))
        return self.run_id  # type: ignore[return-value]

    def stop_run(self) -> int:
        if self.state != "RUNNING":
            raise InstrumentError("no run in progress")
        run_id = self.run_id
        self._finish_run("COMPLETED" if self.profile.persists_results else "LOST")
        self.state = "IDLE"
        self.samples = []
        self.log("run_stopped", str(run_id))
        return run_id  # type: ignore[return-value]

    def runs(self) -> list[dict]:
        rows = self.db.execute("SELECT id, started, stopped, status, samples FROM runs ORDER BY id").fetchall()
        return [dict(zip(("id", "started", "stopped", "status", "samples"), r)) for r in rows]

    def events(self) -> list[dict]:
        rows = self.db.execute("SELECT ts, kind, detail FROM events ORDER BY id").fetchall()
        return [dict(zip(("ts", "kind", "detail"), r)) for r in rows]

    # --- sensors & faults -----------------------------------------------------
    def read_sensors(self) -> dict:
        temp = None if "sensor_dropout" in self.faults else round(
            (OVERTEMP_C + 3 if "overtemp" in self.faults else SETPOINT_C) + self.rng.gauss(0, self.profile.temp_sigma), 3
        )
        door_open = "door_open" in self.faults
        if self.state != "ERROR":
            if temp is None:
                self._raise_error("E102")
            elif temp >= OVERTEMP_C:
                self._raise_error("E101")
            elif door_open and self.state == "RUNNING" and self.profile.door_interlock:
                self._raise_error("E103")
        return {"temperature_c": temp, "pressure_kpa": round(101.3 + self.rng.gauss(0, 0.05), 3), "door_open": door_open}

    def inject_fault(self, fault: str) -> None:
        if fault not in FAULTS:
            raise ValueError(f"unknown fault {fault!r}")
        self.faults.add(fault)
        self.log("fault_injected", fault)

    def clear_faults(self) -> None:
        self.faults.clear()
        self.log("faults_cleared")

    def reset(self) -> None:
        if self.faults:
            raise InstrumentError("clear active faults before reset")
        self.state, self.error = "IDLE", None
        self.log("reset")

    def status(self) -> dict:
        return {
            "build": self.profile.name, "state": self.state, "error": self.error,
            "error_text": ERRORS.get(self.error or ""), "samples": list(self.samples),
            "faults": sorted(self.faults), "run_id": self.run_id,
        }
