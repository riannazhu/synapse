"""Live fictional evaluation: python3 -m server.analysis.evaluate."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from server.analysis import analyze_entry, configure_extractor
from server.models.gemini import GeminiExtractor, ProviderError


def check_case(case, result):
    """Check annotations, not model self-rated confidence or full correctness."""
    observed = {event["type"] for event in result["goal_events"]}
    people = {topic["label"].casefold() for topic in result["topics"] if topic["kind"] == "person"}
    failures = []
    for expected in case.get("expected_event_types", []):
        if expected not in observed:
            failures.append(f"Missing expected event: {expected}")
    for forbidden in case.get("forbidden_event_types", []):
        if forbidden in observed:
            failures.append(f"Forbidden event returned: {forbidden}")
    for person in case.get("expected_people", []):
        if person.casefold() not in people:
            failures.append(f"Missing expected person: {person}")
    status = "fail" if failures else "manual_review" if case.get("review") else "pass"
    return {"case_id": case["id"], "status": status, "failures": failures,
            "manual_review": case.get("review"), "observed_event_types": sorted(observed),
            "analysis": result}


def run(cases, analyze):
    results = []
    for case in cases:
        try:
            result = analyze(case["id"], case["text"], [],
                             entry_date="2026-10-17", revision=1)
            row = check_case(case, result)
        except (ValueError, ProviderError) as error:
            row = {"case_id": case["id"], "status": "error",
                   "error_type": type(error).__name__, "error": str(error)}
        results.append(row)
        print(f"{case['id']}: {row['status']}", flush=True)
    return {"summary": {status: sum(r["status"] == status for r in results)
                        for status in ("pass", "fail", "manual_review", "error")},
            "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="evaluation/extraction_report.json")
    parser.add_argument("--case", action="append", dest="case_ids",
                        help="Run only this case ID; repeat to select multiple cases")
    args = parser.parse_args()
    cases = json.loads((Path(__file__).resolve().parents[2] / "fixtures/extraction_review.json").read_text())
    if args.case_ids:
        unknown = set(args.case_ids) - {case["id"] for case in cases}
        if unknown:
            parser.error("Unknown case IDs: " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case["id"] in args.case_ids]
    extractor = GeminiExtractor()
    configure_extractor(extractor)
    report = run(cases, analyze_entry)
    report.update(model=extractor.model, pipeline_version="analysis-v3",
                  evaluated_at=datetime.now(timezone.utc).isoformat(),
                  limitations="Small fictional set. Passing annotations do not prove complete correctness. Review full analyses.")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"]))
    print(f"Report: {output}")
    return 1 if report["summary"]["fail"] or report["summary"]["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
