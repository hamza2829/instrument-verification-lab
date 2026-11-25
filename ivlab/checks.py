"""Automated protocol checks. Each takes a fresh Instrument and returns (passed, observed)."""
from __future__ import annotations

from .instrument import CAPACITY, SETPOINT_C, Instrument, InstrumentError


def _loaded(inst: Instrument, n: int = 1) -> Instrument:
    for i in range(n):
        inst.load_sample(f"S{i + 1:03d}")
    return inst


def run_lifecycle(inst: Instrument):
    run = _loaded(inst).start_run()
    inst.stop_run()
    status = inst.runs()[-1]["status"]
    return status == "COMPLETED" and inst.state == "IDLE", f"run {run} {status}, state {inst.state}"


def start_requires_sample(inst: Instrument):
    try:
        inst.start_run()
        return False, "run started without samples"
    except InstrumentError as e:
        return True, f"rejected: {e}"


def sample_capacity(inst: Instrument):
    _loaded(inst, CAPACITY)
    try:
        inst.load_sample("EXTRA")
        return False, f"accepted sample {CAPACITY + 1}"
    except InstrumentError as e:
        return len(inst.samples) == CAPACITY, f"{len(inst.samples)} loaded, extra rejected: {e}"


def temp_stability(inst: Instrument, reads: int = 10, tolerance: float = 0.5):
    _loaded(inst).start_run()
    temps = [inst.read_sensors()["temperature_c"] for _ in range(reads)]
    worst = max(abs(t - SETPOINT_C) for t in temps)
    return worst <= tolerance, f"max deviation {worst:.2f} C over {reads} reads (tolerance {tolerance})"


def _fault_aborts(inst: Instrument, fault: str, code: str):
    _loaded(inst).start_run()
    inst.inject_fault(fault)
    inst.read_sensors()
    run_status = inst.runs()[-1]["status"]
    ok = inst.state == "ERROR" and inst.error == code and run_status == "ABORTED"
    return ok, f"state {inst.state}, error {inst.error}, run {run_status}"


def overtemp_alarm(inst: Instrument):
    return _fault_aborts(inst, "overtemp", "E101")


def sensor_dropout(inst: Instrument):
    return _fault_aborts(inst, "sensor_dropout", "E102")


def door_interlock(inst: Instrument):
    return _fault_aborts(inst, "door_open", "E103")


def error_recovery(inst: Instrument):
    _fault_aborts(inst, "overtemp", "E101")
    inst.clear_faults()
    inst.reset()
    inst.start_run()  # samples of the aborted run are still in the rack
    return inst.state == "RUNNING", f"state after reset and restart: {inst.state}"


def results_persistence(inst: Instrument):
    for _ in range(3):
        _loaded(inst).start_run()
        inst.stop_run()
    rows = inst.db.execute("SELECT COUNT(*) FROM runs WHERE status='COMPLETED'").fetchone()[0]
    return rows == 3, f"{rows} completed runs stored in SQLite"


def audit_log(inst: Instrument):
    _loaded(inst).start_run()
    inst.stop_run()
    kinds = [e["kind"] for e in inst.events()]
    needed = ["sample_loaded", "run_started", "run_stopped"]
    return all(k in kinds for k in needed), f"events: {', '.join(kinds)}"


CHECKS = {f.__name__: f for f in (run_lifecycle, start_requires_sample, sample_capacity, temp_stability, overtemp_alarm,
                                  sensor_dropout, door_interlock, error_recovery, results_persistence, audit_log)}
