import pytest

from ivlab import checks
from ivlab.instrument import BUILDS, CAPACITY, Instrument, InstrumentError

req = pytest.mark.req


@req("REQ-001")
def test_run_lifecycle(inst):
    inst.load_sample("S1")
    run = inst.start_run()
    assert inst.status()["state"] == "RUNNING" and inst.status()["run_id"] == run
    inst.stop_run()
    assert inst.state == "IDLE" and inst.samples == [] and inst.runs()[0]["status"] == "COMPLETED"


@req("REQ-002")
def test_start_without_samples_rejected(inst):
    with pytest.raises(InstrumentError, match="no samples"):
        inst.start_run()


@req("REQ-001")
def test_start_twice_rejected(inst):
    inst.load_sample("S1")
    inst.start_run()
    with pytest.raises(InstrumentError, match="already"):
        inst.start_run()


@req("REQ-001")
def test_stop_without_run_rejected(inst):
    with pytest.raises(InstrumentError):
        inst.stop_run()


@req("REQ-003")
def test_capacity_limit(inst):
    for i in range(CAPACITY):
        inst.load_sample(f"S{i}")
    with pytest.raises(InstrumentError, match="rack full"):
        inst.load_sample("S99")


@pytest.mark.parametrize("sample", ["", "S1"])
def test_invalid_or_duplicate_sample_rejected(inst, sample):
    inst.load_sample("S1")
    with pytest.raises(InstrumentError):
        inst.load_sample(sample)


def test_unload_sample(inst):
    inst.load_sample("S1")
    inst.unload_sample("S1")
    assert inst.samples == []
    with pytest.raises(InstrumentError):
        inst.unload_sample("S1")


def test_sample_handling_locked_during_run(inst):
    inst.load_sample("S1")
    inst.start_run()
    with pytest.raises(InstrumentError):
        inst.load_sample("S2")
    with pytest.raises(InstrumentError):
        inst.unload_sample("S1")


@req("REQ-005", "REQ-006", "REQ-007")
@pytest.mark.parametrize("fault,code", [("overtemp", "E101"), ("sensor_dropout", "E102"), ("door_open", "E103")])
def test_fault_during_run_aborts_with_error(inst, fault, code):
    inst.load_sample("S1")
    inst.start_run()
    inst.inject_fault(fault)
    inst.read_sensors()
    assert (inst.state, inst.error) == ("ERROR", code)
    assert inst.runs()[-1]["status"] == "ABORTED"


@req("REQ-006")
def test_door_open_blocks_start(inst):
    inst.load_sample("S1")
    inst.inject_fault("door_open")
    with pytest.raises(InstrumentError, match="door"):
        inst.start_run()


def test_prototype_has_no_door_interlock():
    proto = Instrument("prototype", seed=1)
    proto.load_sample("S1")
    proto.start_run()
    proto.inject_fault("door_open")
    proto.read_sensors()
    assert proto.state == "RUNNING"


@req("REQ-008")
def test_reset_requires_cleared_faults_then_recovers(inst):
    inst.inject_fault("overtemp")
    inst.read_sensors()
    with pytest.raises(InstrumentError, match="clear"):
        inst.reset()
    inst.clear_faults()
    inst.reset()
    assert inst.status()["state"] == "IDLE" and inst.error is None


def test_start_rejected_in_error_state(inst):
    inst.load_sample("S1")
    inst.inject_fault("sensor_dropout")
    inst.read_sensors()
    with pytest.raises(InstrumentError, match="E102"):
        inst.start_run()


@req("REQ-004")
def test_series_temperature_within_tolerance(inst):
    temps = [inst.read_sensors()["temperature_c"] for _ in range(200)]
    assert max(abs(t - 37.0) for t in temps) <= 0.5


@req("REQ-010")
def test_events_logged(inst):
    inst.load_sample("S1")
    inst.start_run()
    inst.stop_run()
    assert [e["kind"] for e in inst.events()] == ["sample_loaded", "run_started", "run_stopped"]


@req("REQ-009")
def test_runs_persist_in_sqlite_file(tmp_path):
    db = str(tmp_path / "inst.db")
    a = Instrument("series", db=db)
    a.load_sample("S1")
    a.start_run()
    a.stop_run()
    a.db.close()
    assert Instrument("series", db=db).runs()[0]["status"] == "COMPLETED"


@pytest.mark.parametrize("bad", [lambda: Instrument("beta"), lambda: Instrument().inject_fault("lightning")])
def test_unknown_build_or_fault_rejected(bad):
    with pytest.raises(ValueError):
        bad()


@pytest.mark.parametrize("build", list(BUILDS))
def test_seeded_simulation_is_deterministic(build):
    a, b = Instrument(build, seed=7), Instrument(build, seed=7)
    assert [a.read_sensors() for _ in range(5)] == [b.read_sensors() for _ in range(5)]


@req("REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005", "REQ-006", "REQ-007", "REQ-008", "REQ-009", "REQ-010")
@pytest.mark.parametrize("name", sorted(checks.CHECKS))
def test_protocol_check_passes_on_series(name):
    passed, observed = checks.CHECKS[name](Instrument("series", seed=3))
    assert passed, observed


@pytest.mark.parametrize("name", ["temp_stability", "door_interlock"])
def test_protocol_check_detects_prototype_defects(name):
    passed, _ = checks.CHECKS[name](Instrument("prototype", seed=3))
    assert not passed
