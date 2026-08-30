import json
import tempfile
import unittest
from pathlib import Path

from src.qa_pipeline import append_raw_prediction, score_prediction_files


class QaPipelineTests(unittest.TestCase):
    def test_raw_append_preserves_bytes_and_rejects_duplicate_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.jsonl"
            row = {"runId": "dev-1", "caseId": "one", "rawOutput": "  raw\ntext  "}
            append_raw_prediction(path, row)
            loaded = json.loads(path.read_text())
            self.assertEqual(loaded["rawOutput"], "  raw\ntext  ")
            with self.assertRaises(ValueError):
                append_raw_prediction(path, row)

    def test_scoring_is_one_to_one_hashed_and_exclusive(self) -> None:
        case = {
            "caseId": "one", "language": "en", "category": "single_document",
            "difficulty": "easy", "answerability": "answerable",
            "goldFactPoints": ["fact"], "goldSources": ["https://learn.microsoft.com/doc"],
            "requiredDocumentIds": ["doc"],
        }
        prediction = {
            "runId": "dev-1", "caseId": "one", "status": "completed",
            "answer": "fact https://learn.microsoft.com/doc", "latencyMs": 1,
            "rawOutput": "raw bytes", "cacheHit": False,
            "trace": [{"outcome": "action", "observation": json.dumps({
                "status": "success", "documentId": "doc", "source": "https://learn.microsoft.com/doc"
            })}],
            "rubricReviews": [
                {"reviewerId": "r1", "factPointScores": [True]},
                {"reviewerId": "r2", "factPointScores": [True]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path, raw_path = root / "cases.jsonl", root / "raw.jsonl"
            case_path.write_text(json.dumps(case) + "\n")
            raw_path.write_text(json.dumps(prediction) + "\n")
            result = score_prediction_files(case_path, raw_path, root / "out")
            evaluated = json.loads((root / "out" / "evaluated_cases.jsonl").read_text())
            self.assertRegex(evaluated["rawOutputSha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(result["caseCount"], 1)
            with self.assertRaises(FileExistsError):
                score_prediction_files(case_path, raw_path, root / "out")


if __name__ == "__main__":
    unittest.main()
