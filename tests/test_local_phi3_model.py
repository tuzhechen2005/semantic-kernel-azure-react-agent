import tempfile
import unittest
from pathlib import Path

from src.local_phi3_model import LocalPhi3Model, Phi3GenerationConfig


class LocalPhi3ModelTests(unittest.TestCase):
    def test_missing_model_is_rejected_before_import(self) -> None:
        missing_path = Path(tempfile.gettempdir()) / "missing-phi3-model.gguf"

        with self.assertRaises(FileNotFoundError):
            LocalPhi3Model(missing_path)

    def test_default_stops_prevent_fake_tool_observations(self) -> None:
        stops = Phi3GenerationConfig().stop

        self.assertIn("<|end|>", stops)
        self.assertIn("\nObservation:", stops)
        self.assertIn("\n- response from tool:", stops)
        self.assertIn("\n- response:", stops)
        self.assertIn("\n\nThought:", stops)


if __name__ == "__main__":
    unittest.main()
