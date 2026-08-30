import tempfile
import unittest
from pathlib import Path

from src.corpus_contract import build_corpus_manifest, write_corpus_manifest


class CorpusContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = Path(__file__).resolve().parent.parent / "docs" / "corpus"

    def test_manifest_records_version_source_sections_and_hash(self) -> None:
        manifest = build_corpus_manifest(self.corpus)

        self.assertGreaterEqual(manifest["documentCount"], 6)
        self.assertEqual(len(manifest["documents"]), manifest["documentCount"])
        for document in manifest["documents"]:
            self.assertRegex(document["sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(document["updated"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(document["version"])
            self.assertTrue(document["source"].startswith("https://learn.microsoft.com/"))
            self.assertTrue(document["sections"])
            self.assertTrue(all("#" in section for section in document["sections"]))

    def test_manifest_writer_refuses_overwrite(self) -> None:
        manifest = build_corpus_manifest(self.corpus)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            write_corpus_manifest(target, manifest)
            with self.assertRaises(FileExistsError):
                write_corpus_manifest(target, manifest)


if __name__ == "__main__":
    unittest.main()
