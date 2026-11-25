"""Shared fixtures + requirement traceability for pytest (@pytest.mark.req("REQ-001"))."""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from ivlab.api import create_app
from ivlab.instrument import Instrument

_records: list[dict] = []


def pytest_addoption(parser):
    parser.addoption("--req-report", default=None, help="write requirement-linked test outcomes to this JSON file")


def pytest_configure(config):
    config.addinivalue_line("markers", "req(*ids): requirement ids this test verifies")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    rep = (yield).get_result()
    reqs = [r for m in item.iter_markers("req") for r in m.args]
    if reqs and (rep.when == "call" or rep.outcome != "passed"):
        _records.append({"nodeid": item.nodeid, "reqs": reqs, "outcome": rep.outcome})


def pytest_sessionfinish(session):
    path = session.config.getoption("--req-report")
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(_records, indent=2), encoding="utf-8")


@pytest.fixture
def inst():
    return Instrument("series", seed=1)


@pytest.fixture(scope="session")
def live_server():
    app = create_app(Instrument("series", seed=1))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", app
    server.should_exit = True
    thread.join(5)


@pytest.fixture
def server(live_server):
    """Live server URL with a fresh series-build instrument for each test."""
    url, app = live_server
    app.state.inst = Instrument("series", seed=1)
    return url
