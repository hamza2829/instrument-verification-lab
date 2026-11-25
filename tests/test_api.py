import pytest
from fastapi.testclient import TestClient

from ivlab.api import create_app
from ivlab.instrument import Instrument

req = pytest.mark.req


@pytest.fixture
def client():
    return TestClient(create_app(Instrument("series", seed=1)))


def test_status_initial(client):
    assert client.get("/api/status").json() | {} == {
        "build": "series", "state": "IDLE", "error": None, "error_text": None, "samples": [], "faults": [], "run_id": None}


@req("REQ-001", "REQ-009")
def test_run_flow_over_api(client):
    assert client.post("/api/samples", json={"sample_id": "S1"}).status_code == 201
    run = client.post("/api/runs/start").json()["run_id"]
    assert client.get("/api/status").json()["state"] == "RUNNING"
    assert client.post("/api/runs/stop").json() == {"run_id": run}
    assert client.get("/api/runs").json()[0]["status"] == "COMPLETED"


@req("REQ-002")
def test_start_without_sample_is_409(client):
    r = client.post("/api/runs/start")
    assert r.status_code == 409 and "no samples" in r.json()["detail"]


def test_unload_sample(client):
    client.post("/api/samples", json={"sample_id": "S1"})
    assert client.delete("/api/samples/S1").json()["samples"] == []
    assert client.delete("/api/samples/S1").status_code == 409


def test_unknown_fault_is_422(client):
    assert client.post("/api/faults", json={"fault": "lightning"}).status_code == 422


def test_invalid_payload_is_422(client):
    assert client.post("/api/samples", json={}).status_code == 422


@req("REQ-004")
def test_sensor_reading_shape(client):
    s = client.get("/api/sensors").json()
    assert set(s) == {"temperature_c", "pressure_kpa", "door_open"} and abs(s["temperature_c"] - 37) < 0.5


@req("REQ-005", "REQ-008")
def test_fault_injection_error_and_recovery(client):
    client.post("/api/samples", json={"sample_id": "S1"})
    client.post("/api/runs/start")
    client.post("/api/faults", json={"fault": "overtemp"})
    client.get("/api/sensors")
    st = client.get("/api/status").json()
    assert (st["state"], st["error"]) == ("ERROR", "E101")
    assert client.post("/api/reset").status_code == 409
    client.delete("/api/faults")
    assert client.post("/api/reset").json()["state"] == "IDLE"


@req("REQ-010")
def test_events_endpoint(client):
    client.post("/api/samples", json={"sample_id": "S1"})
    assert client.get("/api/events").json()[-1]["kind"] == "sample_loaded"


@req("REQ-011")
def test_ui_page_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Instrument Console" in r.text and "sensor_dropout" in r.text
