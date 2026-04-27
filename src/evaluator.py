from __future__ import annotations

import json
from pathlib import Path

from src.classifier import ReturnReasonClassifier

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = BASE_DIR / "data" / "synthetic_returns.json"
RESULTS_PATH = BASE_DIR / "evals" / "results.json"
FALSE_CONFIDENCE_THRESHOLD = 0.7


def run_evaluation() -> dict[str, object]:
    classifier = ReturnReasonClassifier()
    cases = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    rows: list[dict[str, object]] = []
    certain_cases = 0
    certain_correct = 0
    uncertain_cases = 0
    uncertain_correct = 0
    false_confident = 0
    schema_valid_count = 0

    for case in cases:
        run = classifier.classify_with_metadata(text=case["text"], language=case["language"])
        result = run.result

        schema_valid_count += int(run.schema_valid)
        expected_uncertain = case["expected_is_uncertain"]
        expected_action = case["expected_action"]
        actual_action = result.action
        actual_uncertain = bool(result.is_uncertain and result.action is None)

        if expected_uncertain:
            uncertain_cases += 1
            if actual_uncertain:
                uncertain_correct += 1
            if not actual_uncertain and result.confidence >= FALSE_CONFIDENCE_THRESHOLD:
                false_confident += 1
        else:
            certain_cases += 1
            if actual_action == expected_action and not result.is_uncertain:
                certain_correct += 1

        rows.append(
            {
                "id": case["id"],
                "text": case["text"],
                "language": case["language"],
                "notes": case["notes"],
                "expected_action": expected_action,
                "expected_is_uncertain": expected_uncertain,
                "actual_action": actual_action,
                "actual_is_uncertain": result.is_uncertain,
                "actual_confidence": result.confidence,
                "actual_uncertainty_reason": result.uncertainty_reason,
                "reasoning_en": result.reasoning_en,
                "reasoning_ar": result.reasoning_ar,
                "used_fallback": run.used_fallback,
                "schema_valid": run.schema_valid,
                "error": run.error,
                "action_match": actual_action == expected_action and not expected_uncertain,
                "uncertainty_match": actual_uncertain == expected_uncertain,
            }
        )

    summary = {
        "total_cases": len(cases),
        "model": "fallback-rules" if classifier.fallback_mode else "meta-llama/llama-3.3-70b-instruct:free",
        "fallback_mode": classifier.fallback_mode,
        "false_confidence_threshold": FALSE_CONFIDENCE_THRESHOLD,
        "action_accuracy": round(certain_correct / certain_cases, 4) if certain_cases else 0.0,
        "uncertainty_recall": round(uncertain_correct / uncertain_cases, 4) if uncertain_cases else 0.0,
        "false_confidence_rate": round(false_confident / uncertain_cases, 4) if uncertain_cases else 0.0,
        "schema_validity": round(schema_valid_count / len(cases), 4) if cases else 0.0,
        "counts": {
            "certain_cases": certain_cases,
            "certain_correct": certain_correct,
            "uncertain_cases": uncertain_cases,
            "uncertain_correct": uncertain_correct,
            "false_confident": false_confident,
            "schema_valid_count": schema_valid_count,
        },
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps({"summary": summary, "results": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print_summary(summary)
    return {"summary": summary, "results": rows}


def print_summary(summary: dict[str, object]) -> None:
    counts = summary["counts"]
    print()
    print("MumzReturn AI Evaluation Summary")
    print("=" * 36)
    print(f"{'Metric':<24} {'Value':>10}")
    print("-" * 36)
    print(
        f"{'Action accuracy':<24} "
        f"{summary['action_accuracy'] * 100:>6.1f}% "
        f"({counts['certain_correct']}/{counts['certain_cases']})"
    )
    print(
        f"{'Uncertainty recall':<24} "
        f"{summary['uncertainty_recall'] * 100:>6.1f}% "
        f"({counts['uncertain_correct']}/{counts['uncertain_cases']})"
    )
    print(
        f"{'False confidence rate':<24} "
        f"{summary['false_confidence_rate'] * 100:>6.1f}% "
        f"({counts['false_confident']}/{counts['uncertain_cases']})"
    )
    print(
        f"{'Schema validity':<24} "
        f"{summary['schema_validity'] * 100:>6.1f}% "
        f"({counts['schema_valid_count']}/{summary['total_cases']})"
    )
    print("-" * 36)
    print(f"Model: {summary['model']}")
    print(f"Fallback mode: {summary['fallback_mode']}")
    print()


if __name__ == "__main__":
    run_evaluation()
