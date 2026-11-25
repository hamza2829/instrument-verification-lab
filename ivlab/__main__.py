"""CLI: python -m ivlab run-build|analyze ..."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import verify


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ivlab", description="Instrument verification workflow")
    sub = p.add_subparsers(dest="cmd", required=True)
    rb = sub.add_parser("run-build", help="execute a build's protocol (auto checks + recorded answers)")
    rb.add_argument("--build", required=True, choices=["prototype", "pre-series", "series"])
    rb.add_argument("--repeats", type=int, default=3)
    rb.add_argument("--out", type=Path, default=Path("out/results"))
    an = sub.add_parser("analyze", help="defects, analysis, Markdown/HTML report, release gate")
    an.add_argument("--results", type=Path, default=Path("out/results"))
    an.add_argument("--pytest", type=Path, default=Path("out/pytest-reqs.json"))
    an.add_argument("--out", type=Path, default=Path("out"))
    an.add_argument("--gate", action="store_true", help="exit 1 if a requirement lacks a passing test")
    args = p.parse_args(argv)

    if args.cmd == "run-build":
        run = verify.run_build(args.build, args.repeats)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"{args.build}.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
        rs = run["results"]
        print(f"{args.build}: {sum(r['result'] == 'pass' for r in rs)}/{len(rs)} step executions passed "
              f"({run['repeats']} repeats of {len(rs) // run['repeats']} steps)")
        return 0

    reqs = verify.load_requirements()
    order = ["prototype", "pre-series", "series"]
    runs = [json.loads((args.results / f"{b}.json").read_text(encoding="utf-8"))
            for b in order if (args.results / f"{b}.json").exists()]
    pytest_results = json.loads(args.pytest.read_text(encoding="utf-8")) if args.pytest.exists() else []
    defects = verify.write_defects(runs, reqs, args.out / "defects")
    analysis = verify.analyze(runs, reqs, pytest_results, defects)
    args.out.mkdir(parents=True, exist_ok=True)
    md = verify.to_markdown(analysis)
    (args.out / "report.md").write_text(md, encoding="utf-8")
    (args.out / "report.html").write_text(verify.to_html(analysis), encoding="utf-8")
    (args.out / "analysis.json").write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    print(md)
    print(f"{len(defects)} defect reports written to {args.out / 'defects'}")
    if args.gate and analysis["gaps"]:
        print(f"GATE FAILED: requirements without a passing test: {', '.join(analysis['gaps'])}", file=sys.stderr)
        return 1
    if args.gate:
        print("GATE PASSED: every requirement has a passing test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
