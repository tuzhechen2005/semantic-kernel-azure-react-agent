import json
import unittest

from src.qa_evaluator import score_case, summarize_scores


SOURCE = "https://learn.microsoft.com/disk-types"


def answerable_case() -> dict[str, object]:
    return {
        "caseId": "case-1",
        "language": "en",
        "category": "single_document",
        "difficulty": "easy",
        "answerability": "answerable",
        "goldFactPoints": ["Standard HDD is for backup.", "It is lower performance."],
        "goldSources": [SOURCE],
        "requiredDocumentIds": ["managed_disk_types"],
    }


class QaEvaluatorTests(unittest.TestCase):
    def test_dual_rubric_and_observed_citation_score_answer(self) -> None:
        prediction = {
            "caseId": "case-1",
            "status": "completed",
            "answer": f"Use Standard HDD. Source: {SOURCE}",
            "latencyMs": 25,
            "trace": [{
                "outcome": "action",
                "action": "read_document",
                "observation": json.dumps({
                    "status": "success", "documentId": "managed_disk_types", "source": SOURCE
                }),
            }],
            "rubricReviews": [
                {"reviewerId": "r1", "factPointScores": [True, True]},
                {"reviewerId": "r2", "factPointScores": [True, False]},
            ],
        }
        score = score_case(answerable_case(), prediction)

        self.assertEqual(score["answerAccuracy"], 0.5)
        self.assertEqual(score["rubricAgreement"], 0.5)
        self.assertEqual(score["validCitationRate"], 1.0)
        self.assertTrue(score["documentHit"])

    def test_fabricated_url_fails_even_when_rubric_is_positive(self) -> None:
        case = answerable_case()
        bad = "https://invented.example/doc"
        prediction = {
            "caseId": "case-1",
            "status": "completed",
            "answer": f"Claim. Source: {bad}",
            "latencyMs": 10,
            "trace": [],
            "rubricReviews": [
                {"reviewerId": "r1", "factPointScores": [True, True]},
                {"reviewerId": "r2", "factPointScores": [True, True]},
            ],
        }
        score = score_case(case, prediction)

        self.assertEqual(score["validCitationRate"], 0.0)
        self.assertIn("fabricated_citation", score["errors"])

    def test_safe_fallback_is_recognition_not_answer_correctness(self) -> None:
        case = {
            **answerable_case(),
            "caseId": "case-2",
            "answerability": "unanswerable",
            "goldFactPoints": [],
            "goldSources": [],
            "requiredDocumentIds": [],
        }
        prediction = {
            "caseId": "case-2", "status": "evidence_insufficient",
            "answer": "INSUFFICIENT_EVIDENCE: not in corpus", "latencyMs": 2,
            "trace": [], "rubricReviews": [],
        }
        score = score_case(case, prediction)

        self.assertTrue(score["unanswerableRecognized"])
        self.assertIsNone(score["answerAccuracy"])
        self.assertIsNone(score["documentHit"])
        self.assertTrue(score["safeDegradation"])

    def test_summary_distinguishes_recovery_degradation_and_cache(self) -> None:
        scores = [
            {
                **score_case(answerable_case(), {
                    "caseId": "case-1", "status": "completed", "answer": f"A {SOURCE}",
                    "latencyMs": 10, "cacheHit": False,
                    "trace": [
                        {"outcome": "parse_error"},
                        {"outcome": "action", "observation": json.dumps({"status": "success", "documentId": "managed_disk_types", "source": SOURCE})},
                    ],
                    "rubricReviews": [
                        {"reviewerId": "r1", "factPointScores": [True, True]},
                        {"reviewerId": "r2", "factPointScores": [True, True]},
                    ],
                })
            },
            {
                "caseId": "case-2", "answerAccuracy": None, "rubricAgreement": None,
                "validCitationRate": None, "documentHit": None,
                "unanswerableRecognized": True, "recovered": False,
                "safeDegradation": True, "illegalExecutionCount": 0,
                "latencyMs": 30, "cacheHit": True, "errors": [],
                "language": "zh", "category": "unanswerable", "difficulty": "hard",
            },
        ]
        summary = summarize_scores(scores)

        self.assertEqual(summary["answerAccuracy"], 1.0)
        self.assertEqual(summary["illegalExecutionCount"], 0)
        self.assertEqual(summary["recoveryRate"], 1.0)
        self.assertEqual(summary["safeDegradationCount"], 1)
        self.assertEqual(summary["cacheHitRate"], 0.5)
        self.assertEqual(summary["latencyMs"]["p50"], 20.0)


if __name__ == "__main__":
    unittest.main()


class ValidCitationDenominatorTests(unittest.TestCase):
    """The frozen metric contract fixes the denominator at completed answers."""

    def _case(self, case_id: str) -> dict[str, object]:
        return {
            "caseId": case_id,
            "language": "en",
            "category": "single_document",
            "difficulty": "easy",
            "answerability": "answerable",
            "goldFactPoints": ["fact"],
            "goldSources": ["https://learn.microsoft.com/doc"],
            "requiredDocumentIds": ["doc"],
        }

    def _prediction(self, case_id: str, *, status: str, answer: str | None) -> dict[str, object]:
        return {
            "runId": "r",
            "caseId": case_id,
            "status": status,
            "answer": answer,
            "latencyMs": 1.0,
            "rawOutput": "raw",
            "cacheHit": False,
            "trace": [
                {
                    "outcome": "action",
                    "executed": True,
                    "action": "search_documents",
                    "observation": json.dumps(
                        {
                            "status": "success",
                            "documentId": "doc",
                            "source": "https://learn.microsoft.com/doc",
                        }
                    ),
                }
            ],
            "rubricReviews": [
                {"reviewerId": "a", "factPointScores": [True]},
                {"reviewerId": "b", "factPointScores": [True]},
            ],
        }

    def test_case_without_a_completed_answer_leaves_the_denominator(self) -> None:
        score = score_case(
            self._case("c1"),
            self._prediction("c1", status="parse_error", answer=None),
        )
        self.assertIsNone(score["validCitationRate"])
        self.assertFalse(score["answerProduced"])
        self.assertNotIn("fabricated_citation", score["errors"])

    def test_completed_answer_citing_observed_gold_source_is_valid(self) -> None:
        score = score_case(
            self._case("c2"),
            self._prediction(
                "c2", status="completed", answer="fact https://learn.microsoft.com/doc"
            ),
        )
        self.assertEqual(score["validCitationRate"], 1.0)
        self.assertTrue(score["answerProduced"])
        self.assertEqual(score["errors"], [])

    def test_completed_answer_citing_an_unobserved_url_still_fails(self) -> None:
        score = score_case(
            self._case("c3"),
            self._prediction(
                "c3", status="completed", answer="fact https://evil.example/doc"
            ),
        )
        self.assertEqual(score["validCitationRate"], 0.0)
        self.assertIn("fabricated_citation", score["errors"])

    def test_summary_reports_coverage_next_to_citation_validity(self) -> None:
        scores = [
            score_case(self._case("c1"), self._prediction("c1", status="parse_error", answer=None)),
            score_case(
                self._case("c2"),
                self._prediction("c2", status="completed", answer="fact https://learn.microsoft.com/doc"),
            ),
        ]
        summary = summarize_scores(scores)
        self.assertEqual(summary["validCitationRate"], 1.0)
        self.assertEqual(summary["answerCoverageRate"], 0.5)
