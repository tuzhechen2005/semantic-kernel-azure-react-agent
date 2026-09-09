import json
import tempfile
import unittest
from pathlib import Path

from src.rubric_review import RubricError, build_review_sheets, merge_reviews


CASES = [
    {
        "caseId": "a",
        "question": "q-a",
        "answerability": "answerable",
        "goldFactPoints": ["f1", "f2"],
    },
    {
        "caseId": "u",
        "question": "q-u",
        "answerability": "unanswerable",
        "goldFactPoints": [],
    },
]
PREDICTIONS = [
    {
        "caseId": "a",
        "runId": "r",
        "status": "completed",
        "answer": "ans-a",
        "rawOutput": "x",
    },
    {
        "caseId": "u",
        "runId": "r",
        "status": "evidence_insufficient",
        "answer": None,
        "rawOutput": "y",
    },
]


class RubricReviewTests(unittest.TestCase):
    def test_sheets_cover_only_answerable_cases_with_unfilled_scores(self) -> None:
        sheets = build_review_sheets(
            CASES, PREDICTIONS, reviewer_ids=["reviewer_a", "reviewer_b"]
        )
        self.assertEqual(sorted(sheets), ["reviewer_a", "reviewer_b"])
        sheet = sheets["reviewer_a"]
        self.assertEqual(sheet["reviewerId"], "reviewer_a")
        self.assertEqual([item["caseId"] for item in sheet["items"]], ["a"])
        item = sheet["items"][0]
        self.assertEqual(item["question"], "q-a")
        self.assertEqual(item["modelAnswer"], "ans-a")
        self.assertEqual([fact["text"] for fact in item["factPoints"]], ["f1", "f2"])
        self.assertEqual([fact["correct"] for fact in item["factPoints"]], [None, None])
        with self.assertRaises(RubricError):
            build_review_sheets(CASES, PREDICTIONS, reviewer_ids=["same", "same"])

    def test_merge_requires_two_distinct_fully_filled_reviewers(self) -> None:
        sheets = build_review_sheets(
            CASES, PREDICTIONS, reviewer_ids=["reviewer_a", "reviewer_b"]
        )
        for sheet in sheets.values():
            for item in sheet["items"]:
                for fact in item["factPoints"]:
                    fact["correct"] = True
        sheets["reviewer_b"]["items"][0]["factPoints"][1]["correct"] = False
        merged = merge_reviews(PREDICTIONS, list(sheets.values()))
        reviews = merged[0]["rubricReviews"]
        self.assertEqual(
            [review["reviewerId"] for review in reviews], ["reviewer_a", "reviewer_b"]
        )
        self.assertEqual(reviews[0]["factPointScores"], [True, True])
        self.assertEqual(reviews[1]["factPointScores"], [True, False])
        self.assertNotIn("rubricReviews", merged[1])
        self.assertEqual(merged[0]["rawOutput"], "x")
        sheets["reviewer_a"]["items"][0]["factPoints"][0]["correct"] = None
        with self.assertRaises(RubricError):
            merge_reviews(PREDICTIONS, list(sheets.values()))
        with self.assertRaises(RubricError):
            merge_reviews(PREDICTIONS, [sheets["reviewer_b"]])

    def test_sheets_round_trip_through_json_files(self) -> None:
        sheets = build_review_sheets(
            CASES, PREDICTIONS, reviewer_ids=["reviewer_a", "reviewer_b"]
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for reviewer_id, sheet in sheets.items():
                path = Path(directory) / f"{reviewer_id}.json"
                for item in sheet["items"]:
                    for fact in item["factPoints"]:
                        fact["correct"] = True
                path.write_text(
                    json.dumps(sheet, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                paths.append(path)
            merged = merge_reviews(
                PREDICTIONS,
                [json.loads(path.read_text(encoding="utf-8")) for path in paths],
            )
            self.assertEqual(len(merged[0]["rubricReviews"]), 2)


if __name__ == "__main__":
    unittest.main()
