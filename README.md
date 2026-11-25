# instrument-verification-lab

[![Verification](https://github.com/hamza2829/instrument-verification-lab/actions/workflows/verification.yml/badge.svg)](https://github.com/hamza2829/instrument-verification-lab/actions/workflows/verification.yml)

A software verification workflow for a **simulated** lab analysis instrument. It covers requirements, test protocols for three hardware builds, a protocol runner, defect reports with traceability, automated tests (pytest, API and Playwright UI), result analysis and a release gate. Everything runs in GitHub Actions: no Docker, no API keys, no accounts, no manual steps.

## Architecture

```
requirements/requirements.yaml   REQ-001..012 (id, priority, text)
protocols/<build>.md             manual test protocol per build: step, req, action, expected, evidence, auto-check
recorded/<build>.yaml            recorded tester answers + evidence references for manual steps
        │
        ▼
ivlab/instrument.py   simulator: state machine, rack (8 positions), sensors with seeded noise,
                      error states E101/E102/E103, fault injection, SQLite run + event log;
                      build profiles: prototype, pre-series, series
ivlab/api.py          FastAPI control API (/api/...) + operator web console (/)
ivlab/checks.py       automated protocol checks run against a fresh simulator per step
ivlab/verify.py       protocol parser, runner, defect writer, analysis, Markdown/HTML report, gate
ivlab/__main__.py     CLI: run-build | analyze [--gate]
tests/                pytest: simulator, API, verification tooling, Playwright UI, scripts
scripts/              API integration flow and repetitive start/stop + sensor checks
```

Traceability: **requirement → protocol step / pytest test (`@pytest.mark.req`) → defect**. Each defect report (`out/defects/DEF-<BUILD>-<STEP>.md` and `defects.json`) names its requirement, step, expected and observed result, evidence, severity, and whether the failure is intermittent.

## What the three builds show

| Build | Simulated behaviour | Expected outcome |
|---|---|---|
| prototype | noisy temperature sensor, no door interlock, unfinished console and rack labels | several defects |
| pre-series | less sensor noise, interlock fitted | temperature check **flaky** across repeats, one label defect |
| series | release candidate | all steps pass |

Each build is run 5 times with different seeds. A step with mixed results is reported as flaky. A check that fails in 2 or more builds is reported as a recurring failure.

## Run it

```bash
pip install -r requirements.txt && python -m playwright install chromium
for b in prototype pre-series series; do python -m ivlab run-build --build $b --repeats 5; done
python -m pytest --req-report out/pytest-reqs.json
python -m ivlab analyze --gate        # out/report.md, out/report.html, out/defects/
```

CI (`.github/workflows/verification.yml`, ubuntu-latest) does the above, adds the integration and repetitive scripts against a live uvicorn server, writes the report to the job summary and uploads `verification-report`. **The gate fails the job when a requirement has no passing test**: there must be a passing protocol step in the series build or a passing requirement-linked pytest test.

## Real CI output

<!-- CI-OUTPUT -->
