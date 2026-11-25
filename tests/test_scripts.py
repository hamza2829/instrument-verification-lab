import importlib.util
from pathlib import Path

import pytest


def _load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent.parent / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.req("REQ-001", "REQ-006", "REQ-008", "REQ-009")
def test_api_integration_script(server):
    results = _load("api_integration").run(server)
    assert all(ok for _, ok in results), results


@pytest.mark.req("REQ-001", "REQ-004")
def test_repetitive_checks_script(server):
    summary = _load("repetitive_checks").run(server, cycles=10)
    assert summary["passed"] and summary["failed_cycles"] == []
