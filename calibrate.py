#!/usr/bin/env python3
"""
Calibration Tool — прогоняет все демо-кейсы через scoring engine,
сравнивает expected vs actual top issue, выводит таблицу.

Использование:
  python calibrate.py                    # таблица pass/fail
  python calibrate.py --export scores.json   # экспорт полных score в JSON
  python calibrate.py --case tomato_phytophthora_rain  # один кейс с debug
  python calibrate.py --threshold 0.05   # другой min_score порог
"""
import sys
import json
import argparse
from pathlib import Path

# Добавляем текущую директорию в путь для импорта приложения
sys.path.insert(0, str(Path(__file__).parent))

from app.services.scoring_engine import ScoringEngine, compute_urgency, get_confidence_label
from app.services.explanation_service import ExplanationService
from app.schemas.analyze import QuestionnaireAnswers

FIXTURES_PATH = Path(__file__).parent / "app" / "fixtures" / "demo_cases.json"

COL_W = {"id": 36, "crop": 12, "expected": 22, "actual": 22, "score": 7, "status": 8}


def load_fixtures() -> list[dict]:
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_case(case: dict, engine: ScoringEngine) -> dict:
    questionnaire = QuestionnaireAnswers(**case["questionnaire"])
    scored, signals = engine.analyze(
        crop=case["crop"],
        plant_stage=case["plant_stage"],
        questionnaire=questionnaire,
    )
    urgency_level, urgency_reason = compute_urgency(scored)

    actual_top = scored[0].id if scored else "—"
    actual_score = scored[0].score if scored else 0.0
    expected = case["expected_top_issue"]
    passed = actual_top == expected

    return {
        "id": case["id"],
        "label": case["label"],
        "crop": case["crop"],
        "expected": expected,
        "actual_top": actual_top,
        "actual_score": actual_score,
        "urgency": urgency_level,
        "passed": passed,
        "all_scored": [
            {
                "id": i.id,
                "score": i.score,
                "urgency": i.urgency,
                "confidence": get_confidence_label(i.score),
            }
            for i in scored
        ],
        "signals": signals,
    }


def print_table(results: list[dict]) -> None:
    def col(text: str, width: int) -> str:
        return str(text)[:width].ljust(width)

    header = (
        col("CASE ID", COL_W["id"])
        + col("CROP", COL_W["crop"])
        + col("EXPECTED", COL_W["expected"])
        + col("ACTUAL", COL_W["actual"])
        + col("SCORE", COL_W["score"])
        + col("STATUS", COL_W["status"])
    )
    sep = "-" * len(header)

    print(f"\n{sep}")
    print(header)
    print(sep)

    passed = 0
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        if r["passed"]:
            passed += 1
        print(
            col(r["id"], COL_W["id"])
            + col(r["crop"], COL_W["crop"])
            + col(r["expected"], COL_W["expected"])
            + col(r["actual_top"], COL_W["actual"])
            + col(f"{r['actual_score']:.3f}", COL_W["score"])
            + col(status, COL_W["status"])
        )

    print(sep)
    total = len(results)
    print(f"Result: {passed}/{total} passed ({passed / total * 100:.0f}%)\n")


def print_debug_case(result: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"Case: {result['id']}")
    print(f"Crop: {result['crop']}  |  Urgency: {result['urgency']}")
    print(f"Expected: {result['expected']}  →  Actual: {result['actual_top']} ({result['actual_score']:.4f})")
    status = "PASS" if result["passed"] else "FAIL"
    print(f"Status: {status}")

    print(f"\n--- Active signals ---")
    for k, v in sorted(result["signals"].items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k:<35} {v:.3f}")

    print(f"\n--- Top issues ranked ---")
    for i, issue in enumerate(result["all_scored"]):
        marker = " ← TOP" if i == 0 else ""
        expected_marker = " ← EXPECTED" if issue["id"] == result["expected"] else ""
        print(f"  {i+1}. {issue['id']:<30} score={issue['score']:.4f}  {issue['confidence']}  {issue['urgency']}{marker}{expected_marker}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Calibration tool for scoring engine")
    parser.add_argument("--export", metavar="FILE", help="Export full results to JSON file")
    parser.add_argument("--case", metavar="FIXTURE_ID", help="Run single case with debug output")
    parser.add_argument("--threshold", type=float, default=0.05, help="Min score threshold (default: 0.05)")
    args = parser.parse_args()

    engine = ScoringEngine(top_n=5, min_score=args.threshold)
    fixtures = load_fixtures()

    if args.case:
        case = next((c for c in fixtures if c["id"] == args.case), None)
        if not case:
            print(f"Error: case '{args.case}' not found")
            print(f"Available: {', '.join(c['id'] for c in fixtures)}")
            sys.exit(1)
        result = run_case(case, engine)
        print_debug_case(result)

        # Also run debug scoring
        from app.rules.loader import get_all_issues_for_crop
        from app.schemas.analyze import QuestionnaireAnswers
        from app.services.scoring_engine import SignalExtractor

        questionnaire = QuestionnaireAnswers(**case["questionnaire"])
        signals = SignalExtractor().extract(questionnaire, None, None)
        debug = engine.score_issues_debug(case["crop"], case["plant_stage"], signals)

        print("--- Score breakdown (top 5) ---")
        for issue in debug["scored_issues"][:5]:
            bd = issue["breakdown"]
            print(f"\n  [{issue['id']}] final={issue['final_score']:.4f}  urgency={issue['urgency']}")
            print(f"    raw_core={bd['raw_core']:.4f}  penalty={bd['raw_penalty']:.4f}  max_core={bd['max_core']:.4f}")
            print(f"    normalized={bd['normalized_core']:.4f}  cv_bonus={bd['cv_bonus']:.4f}")
            print(f"    multiplier={bd['crop_stage_multiplier']:.3f}  env={bd['env_factors']}  weather={bd['weather_factors']}")

        if debug["gated_issues"]:
            print(f"\n--- Gated issues ({len(debug['gated_issues'])}) ---")
            for g in debug["gated_issues"]:
                print(f"  {g['id']:<30} gated_by={g['gated_by']}  required_any={g['required_any']}  required_all={g['required_all']}")
        return

    # Full calibration run
    results = [run_case(c, engine) for c in fixtures]
    print_table(results)

    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"Full results exported to: {args.export}")


if __name__ == "__main__":
    main()
