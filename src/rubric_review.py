"""Dual-reviewer rubric sheets for Task 2 answer accuracy.

Sheets are generated from raw predictions for answerable cases only. Two
distinct human reviewers fill ``correct`` for every fact point; merging refuses
partial sheets, duplicate reviewers, or sheets that drift from the predictions.
Raw model output is never modified.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class RubricError(ValueError):
    """Raised when reviewer sheets cannot be trusted."""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_review_sheets(
    cases: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    reviewer_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Build one unfilled sheet per reviewer covering answerable cases."""
    if len(reviewer_ids) < 2 or len(set(reviewer_ids)) != len(reviewer_ids):
        raise RubricError("at least two distinct reviewer IDs are required")
    if any(not isinstance(item, str) or not item.strip() for item in reviewer_ids):
        raise RubricError("reviewer IDs must be nonblank strings")
    prediction_by_id = {str(row.get("caseId")): row for row in predictions}
    if len(prediction_by_id) != len(predictions):
        raise RubricError("duplicate prediction caseId")
    items: list[dict[str, Any]] = []
    for case in cases:
        if case.get("answerability") != "answerable":
            continue
        case_id = str(case.get("caseId"))
        prediction = prediction_by_id.get(case_id)
        if prediction is None:
            raise RubricError(f"prediction missing for answerable case {case_id}")
        facts = case.get("goldFactPoints")
        if not isinstance(facts, list) or not facts:
            raise RubricError(f"answerable case {case_id} has no gold fact points")
        items.append(
            {
                "caseId": case_id,
                "question": case.get("question"),
                "status": prediction.get("status"),
                "modelAnswer": prediction.get("answer"),
                "factPoints": [
                    {"index": index, "text": str(fact), "correct": None}
                    for index, fact in enumerate(facts)
                ],
                "note": "",
            }
        )
    return {
        reviewer_id: {
            "reviewerId": reviewer_id,
            "runId": predictions[0].get("runId") if predictions else None,
            "instructions": (
                "对每个事实点独立判断模型答案是否正确表达该事实，只看答案文本，"
                "不看其他 reviewer 的结果；correct 只能填 true 或 false；不确定填 false 并在 note 说明。"
            ),
            "items": json.loads(json.dumps(items, ensure_ascii=False)),
        }
        for reviewer_id in reviewer_ids
    }


def merge_reviews(
    predictions: list[dict[str, Any]],
    sheets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach rubricReviews to predictions; fail closed on any gap or drift."""
    if len(sheets) < 2:
        raise RubricError("two reviewer sheets are required")
    reviewer_ids = [str(sheet.get("reviewerId")) for sheet in sheets]
    if len(set(reviewer_ids)) != len(reviewer_ids):
        raise RubricError("reviewer sheets must come from distinct reviewers")
    per_case: dict[str, list[dict[str, Any]]] = {}
    expected_cases: set[str] | None = None
    for sheet in sheets:
        items = sheet.get("items")
        if not isinstance(items, list):
            raise RubricError("sheet items must be a list")
        case_ids = {str(item.get("caseId")) for item in items}
        if expected_cases is None:
            expected_cases = case_ids
        elif case_ids != expected_cases:
            raise RubricError("reviewer sheets cover different case sets")
        for item in items:
            facts = item.get("factPoints")
            if not isinstance(facts, list) or not facts:
                raise RubricError(f"sheet item {item.get('caseId')} has no fact points")
            scores: list[bool] = []
            for fact in facts:
                value = fact.get("correct") if isinstance(fact, dict) else None
                if not isinstance(value, bool):
                    raise RubricError(
                        f"reviewer {sheet.get('reviewerId')} left {item.get('caseId')} unfilled"
                    )
                scores.append(value)
            per_case.setdefault(str(item.get("caseId")), []).append(
                {"reviewerId": str(sheet.get("reviewerId")), "factPointScores": scores}
            )
    merged: list[dict[str, Any]] = []
    for row in predictions:
        case_id = str(row.get("caseId"))
        reviews = per_case.get(case_id)
        if reviews is None:
            merged.append(dict(row))
            continue
        if len(reviews) != len(sheets):
            raise RubricError(f"case {case_id} is missing a reviewer")
        merged.append({**row, "rubricReviews": reviews})
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--cases", type=Path, required=True)
    build.add_argument("--raw", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--reviewer", action="append", required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("--raw", type=Path, required=True)
    merge.add_argument("--sheet", type=Path, action="append", required=True)
    merge.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        sheets = build_review_sheets(
            _read_jsonl(args.cases), _read_jsonl(args.raw), reviewer_ids=args.reviewer
        )
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for reviewer_id, sheet in sheets.items():
            path = args.output_dir / f"{reviewer_id}.json"
            path.write_text(
                json.dumps(sheet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(path)
        return 0
    merged = merge_reviews(
        _read_jsonl(args.raw),
        [json.loads(path.read_text(encoding="utf-8")) for path in args.sheet],
    )
    with args.output.open("x", encoding="utf-8") as handle:
        for row in merged:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
