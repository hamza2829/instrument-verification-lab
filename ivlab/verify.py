"""Requirements, protocols, protocol runner, defect reports, analysis, reports and the coverage gate."""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

from .checks import CHECKS
from .instrument import Instrument

ROOT = Path(__file__).resolve().parent.parent
SEVERITY = {"high": "major", "medium": "minor", "low": "trivial"}


# --- inputs -------------------------------------------------------------------
def load_requirements(path: Path = ROOT / "requirements" / "requirements.yaml") -> dict[str, dict]:
    reqs = yaml.safe_load(path.read_text(encoding="utf-8"))["requirements"]
    ids = [r["id"] for r in reqs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate requirement ids")
    return {r["id"]: r for r in reqs}


def parse_protocol(text: str) -> dict:
    """Markdown protocol: '# title', 'Build: x', then a table Step|Req|Action|Expected|Evidence|Auto."""
    title = re.search(r"^#\s+(.+)$", text, re.M).group(1).strip()
    build = re.search(r"^Build:\s*(\S+)", text, re.M).group(1)
    steps = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 6 and re.fullmatch(r"[A-Z]\d{2}", cells[0]):
            step, req, action, expected, evidence, auto = cells
            steps.append({"step": step, "req": req, "action": action, "expected": expected,
                          "evidence_required": evidence, "auto": auto if auto not in ("", "-") else None})
    return {"title": title, "build": build, "steps": steps}


def load_protocol(build: str) -> dict:
    return parse_protocol((ROOT / "protocols" / f"{build}.md").read_text(encoding="utf-8"))


def load_answers(build: str) -> dict:
    return yaml.safe_load((ROOT / "recorded" / f"{build}.yaml").read_text(encoding="utf-8"))


# --- runner -------------------------------------------------------------------
def run_build(build: str, repeats: int = 3, requirements: dict | None = None) -> dict:
    requirements = requirements or load_requirements()
    protocol, answers = load_protocol(build), load_answers(build)
    results = []
    for repeat in range(1, repeats + 1):
        for st in protocol["steps"]:
            if st["req"] not in requirements:
                raise ValueError(f"{build}/{st['step']}: unknown requirement {st['req']}")
            seed = repeat * 1000 + int(st["step"][1:])
            if st["auto"]:
                passed, observed = CHECKS[st["auto"]](Instrument(build, seed=seed))
                result, evidence = ("pass" if passed else "fail"), f"auto:{st['auto']} seed={seed}"
            else:
                ans = answers["answers"].get(st["step"])
                if ans is None:
                    result, observed, evidence = "not_run", "no recorded answer", ""
                else:
                    result, observed, evidence = ans["result"], ans["observed"], ans.get("evidence", "")
            results.append({**st, "build": build, "repeat": repeat, "seed": seed, "result": result,
                            "observed": observed, "evidence": evidence})
    return {"build": build, "protocol": protocol["title"], "tester": answers.get("tester"),
            "date": str(answers.get("date")), "repeats": repeats, "results": results}


def write_defects(runs: list[dict], requirements: dict, out: Path) -> list[dict]:
    """One defect per failing (build, step); occurrences across repeats decide 'flaky'."""
    out.mkdir(parents=True, exist_ok=True)
    grouped: dict[tuple, list] = defaultdict(list)
    for run in runs:
        for r in run["results"]:
            grouped[(run["build"], r["step"])].append(r)
    defects = []
    for (build, step), rs in sorted(grouped.items()):
        fails = [r for r in rs if r["result"] == "fail"]
        if not fails:
            continue
        req = requirements[fails[0]["req"]]
        d = {"id": f"DEF-{build.upper().replace('-', '')}-{step}", "build": build, "step": step, "requirement": req["id"],
             "title": f"{req['title']}: {fails[0]['action']}", "severity": SEVERITY[req["priority"]],
             "expected": fails[0]["expected"], "observed": fails[0]["observed"], "evidence": fails[0]["evidence"],
             "occurrences": f"{len(fails)}/{len(rs)}", "flaky": len(fails) < len(rs), "status": "open"}
        defects.append(d)
        (out / f"{d['id']}.md").write_text(
            f"# {d['id']}: {d['title']}\n\n| Field | Value |\n|---|---|\n"
            + "".join(f"| {k} | {v} |\n" for k, v in d.items() if k not in ("id", "title"))
            + f"\nTrace: {d['requirement']} -> {build}/{step} -> {d['id']}\n", encoding="utf-8")
    (out / "defects.json").write_text(json.dumps(defects, indent=2), encoding="utf-8")
    return defects


# --- analysis -----------------------------------------------------------------
def analyze(runs: list[dict], requirements: dict, pytest_results: list[dict], defects: list[dict]) -> dict:
    builds = [r["build"] for r in runs]
    per_build = {}
    req_status: dict[str, dict] = {rid: {} for rid in requirements}
    flaky, step_fail_builds = [], defaultdict(set)
    for run in runs:
        rs = [r for r in run["results"] if r["result"] != "not_run"]
        per_build[run["build"]] = {"executed": len(rs), "passed": sum(r["result"] == "pass" for r in rs),
                                   "not_run": len(run["results"]) - len(rs)}
        by_step = defaultdict(list)
        for r in run["results"]:
            by_step[r["step"]].append(r)
        for step, srs in by_step.items():
            outcomes = {r["result"] for r in srs}
            req = srs[0]["req"]
            status = "flaky" if outcomes == {"pass", "fail"} else ("fail" if "fail" in outcomes else
                                                                    "pass" if outcomes == {"pass"} else "not_run")
            if status == "flaky":
                flaky.append({"build": run["build"], "step": step, "req": req,
                              "pass_rate": sum(r["result"] == "pass" for r in srs) / len(srs)})
            if "fail" in outcomes:
                step_fail_builds[(step[1:], srs[0]["auto"] or srs[0]["action"], req)].add(run["build"])
            prev = req_status[req].get(run["build"])
            rank = {"fail": 3, "flaky": 2, "not_run": 1, "pass": 0}
            if prev is None or rank[status] > rank[prev]:
                req_status[req][run["build"]] = status
    tests_by_req = defaultdict(list)
    for t in pytest_results:
        for rid in t["reqs"]:
            tests_by_req[rid].append(t)
    recurring = [{"check": name, "req": req, "builds": sorted(b, key=builds.index)}
                 for (_, name, req), b in step_fail_builds.items() if len(b) >= 2]
    signatures = defaultdict(int)
    for run in runs:
        for r in run["results"]:
            if r["result"] == "fail":
                signatures[re.sub(r"\d+(\.\d+)?", "N", r["observed"])] += 1
    final = builds[-1] if builds else None
    gaps = [rid for rid in requirements
            if req_status[rid].get(final) != "pass" and not any(t["outcome"] == "passed" for t in tests_by_req[rid])]
    matrix = [{"req": rid, "title": r["title"], "priority": r["priority"], "builds": req_status[rid],
               "tests": f"{sum(t['outcome'] == 'passed' for t in tests_by_req[rid])}/{len(tests_by_req[rid])}",
               "defects": [d["id"] for d in defects if d["requirement"] == rid]} for rid, r in requirements.items()]
    return {"builds": builds, "per_build": per_build, "matrix": matrix, "flaky": flaky, "recurring": recurring,
            "signatures": sorted(signatures.items(), key=lambda kv: -kv[1]), "gaps": gaps, "final_build": final,
            "pytest": {"total": len(pytest_results), "passed": sum(t["outcome"] == "passed" for t in pytest_results)}}


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "n/a"


def tables(a: dict) -> list[tuple[str, list[str], list[list]]]:
    return [
        ("Pass rate per build", ["Build", "Executed", "Passed", "Pass rate", "Not run"],
         [[b, s["executed"], s["passed"], pct(s["passed"], s["executed"]), s["not_run"]] for b, s in a["per_build"].items()]),
        ("Traceability: requirement -> protocol result per build -> automated tests -> defects",
         ["Requirement", "Title", "Priority", *a["builds"], "pytest passed", "Defects"],
         [[m["req"], m["title"], m["priority"], *[m["builds"].get(b, "-") for b in a["builds"]], m["tests"],
           ", ".join(m["defects"]) or "-"] for m in a["matrix"]]),
        ("Flaky protocol steps (mixed results across repeats)", ["Build", "Step", "Requirement", "Pass rate"],
         [[f["build"], f["step"], f["req"], f"{f['pass_rate']:.0%}"] for f in a["flaky"]]),
        ("Recurring failures (same check failing in 2+ builds)", ["Check", "Requirement", "Builds"],
         [[r["check"], r["req"], ", ".join(r["builds"])] for r in a["recurring"]]),
        ("Failure signatures (numbers normalised)", ["Observed", "Count"], [list(s) for s in a["signatures"]]),
    ]


def to_markdown(a: dict) -> str:
    out = ["# Verification report", "",
           f"pytest: {a['pytest']['passed']}/{a['pytest']['total']} passed. Release gate ({a['final_build']} build or automated test "
           f"must pass every requirement): **{'PASS' if not a['gaps'] else 'FAIL: ' + ', '.join(a['gaps'])}**", ""]
    for title, head, rows in tables(a):
        out += [f"## {title}", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        out += ["| " + " | ".join(map(str, r)) + " |" for r in rows] or ["| " + " | ".join(["none"] + [""] * (len(head) - 1)) + " |"]
        out.append("")
    return "\n".join(out)


def to_html(a: dict) -> str:
    esc = lambda v: html.escape(str(v))  # noqa: E731
    cls = lambda v: f' class="{v}"' if v in ("pass", "fail", "flaky") else ""  # noqa: E731
    parts = ["<!doctype html><html><head><meta charset='utf-8'><title>Verification report</title><style>"
             "body{font-family:system-ui,sans-serif;margin:2rem}table{border-collapse:collapse;margin-bottom:1.5rem}"
             "td,th{border:1px solid #ccc;padding:4px 8px}.pass{background:#dfd}.fail{background:#fdd}.flaky{background:#ffd}"
             "</style></head><body><h1>Verification report</h1>",
             f"<p>pytest {a['pytest']['passed']}/{a['pytest']['total']} passed. Release gate: "
             f"<b>{'PASS' if not a['gaps'] else 'FAIL: ' + esc(', '.join(a['gaps']))}</b></p>"]
    for title, head, rows in tables(a):
        parts.append(f"<h2>{esc(title)}</h2><table><tr>{''.join(f'<th>{esc(h)}</th>' for h in head)}</tr>")
        parts += [f"<tr>{''.join(f'<td{cls(c)}>{esc(c)}</td>' for c in r)}</tr>" for r in rows]
        parts.append("</table>")
    return "".join(parts) + "</body></html>"
