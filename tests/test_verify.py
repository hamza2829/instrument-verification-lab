import json

import pytest

from ivlab import verify
from ivlab.__main__ import main

BUILDS = ["prototype", "pre-series", "series"]


@pytest.fixture(scope="module")
def reqs():
    return verify.load_requirements()


@pytest.fixture(scope="module")
def runs():
    return [verify.run_build(b, repeats=5) for b in BUILDS]


def test_requirements_have_unique_ids_and_fields(reqs):
    assert len(reqs) == 12
    assert all({"id", "title", "text", "priority"} <= set(r) for r in reqs.values())


@pytest.mark.parametrize("build", BUILDS)
def test_protocol_steps_trace_to_known_requirements(build, reqs):
    p = verify.load_protocol(build)
    assert p["build"] == build and len(p["steps"]) == 13
    assert {s["req"] for s in p["steps"]} == set(reqs)  # every requirement has a protocol step


def test_parse_protocol_table():
    p = verify.parse_protocol("# T\nBuild: series\n| Step | Req | Action | Expected | Evidence | Auto |\n|---|---|---|---|---|---|\n"
                              "| A01 | REQ-001 | do | ok | log | run_lifecycle |\n| M01 | REQ-011 | look | ok | photo | - |\n")
    assert [(s["step"], s["auto"]) for s in p["steps"]] == [("A01", "run_lifecycle"), ("M01", None)]


def test_series_build_passes_every_step(runs):
    assert all(r["result"] == "pass" for r in runs[2]["results"])


def test_build_runs_are_reproducible():
    assert verify.run_build("pre-series", 2) == verify.run_build("pre-series", 2)


def test_recorded_answers_are_used_for_manual_steps(runs):
    m03 = next(r for r in runs[0]["results"] if r["step"] == "M03")
    assert m03["result"] == "fail" and m03["evidence"].endswith("M03-rack.jpg")


def test_defects_written_with_traceability(runs, reqs, tmp_path):
    defects = verify.write_defects(runs, reqs, tmp_path)
    ids = {d["id"] for d in defects}
    assert {"DEF-PROTOTYPE-A04", "DEF-PROTOTYPE-A06", "DEF-PRESERIES-M03"} <= ids
    assert not any(d["build"] == "series" for d in defects)
    md = (tmp_path / "DEF-PROTOTYPE-A06.md").read_text(encoding="utf-8")
    assert "REQ-006 -> prototype/A06 -> DEF-PROTOTYPE-A06" in md
    assert json.loads((tmp_path / "defects.json").read_text())[0]["severity"] in {"major", "minor", "trivial"}


def test_analysis_finds_flaky_recurring_and_pass_rates(runs, reqs, tmp_path):
    a = verify.analyze(runs, reqs, [], verify.write_defects(runs, reqs, tmp_path))
    assert a["per_build"]["series"]["passed"] == a["per_build"]["series"]["executed"]
    assert a["per_build"]["prototype"]["passed"] < a["per_build"]["pre-series"]["passed"]
    assert {("pre-series", "A04")} == {(f["build"], f["step"]) for f in a["flaky"]}
    assert {"temp_stability", "Inspect rack position labels"} <= {r["check"] for r in a["recurring"]}
    assert a["gaps"] == []


def test_gate_flags_requirement_without_passing_test(runs, reqs):
    series = {**runs[2], "results": [r for r in runs[2]["results"] if r["req"] != "REQ-012"]}
    assert verify.analyze([runs[0], series], reqs, [], [])["gaps"] == ["REQ-012"]
    passing = [{"nodeid": "t", "reqs": ["REQ-012"], "outcome": "passed"}]
    assert verify.analyze([runs[0], series], reqs, passing, [])["gaps"] == []


def test_reports_render(runs, reqs):
    a = verify.analyze(runs, reqs, [{"nodeid": "t", "reqs": ["REQ-001"], "outcome": "passed"}], [])
    assert "Release gate" in verify.to_markdown(a) and "| REQ-001 |" in verify.to_markdown(a)
    assert verify.to_html(a).startswith("<!doctype html>") and 'class="flaky"' in verify.to_html(a)


def test_cli_end_to_end_with_gate(tmp_path, capsys):
    for b in BUILDS:
        assert main(["run-build", "--build", b, "--repeats", "2", "--out", str(tmp_path / "results")]) == 0
    assert main(["analyze", "--results", str(tmp_path / "results"), "--out", str(tmp_path), "--gate"]) == 0
    assert "GATE PASSED" in capsys.readouterr().out
    assert (tmp_path / "report.html").exists() and (tmp_path / "defects" / "defects.json").exists()


def test_cli_gate_fails_without_series_results(tmp_path):
    main(["run-build", "--build", "prototype", "--repeats", "1", "--out", str(tmp_path / "results")])
    assert main(["analyze", "--results", str(tmp_path / "results"), "--out", str(tmp_path), "--gate"]) == 1
