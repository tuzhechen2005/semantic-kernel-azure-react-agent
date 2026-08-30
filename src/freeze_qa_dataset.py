import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.corpus_contract import build_corpus_manifest, write_corpus_manifest
from src.qa_dataset import build_frozen_cases, validate_cases, write_jsonl_exclusive


def freeze_qa_dataset(
    *,
    corpus_dir: Path,
    corpus_manifest_path: Path,
    dataset_path: Path,
    dataset_manifest_path: Path,
    frozen_at: str,
) -> dict[str, object]:
    try:
        parsed_frozen_at = datetime.fromisoformat(frozen_at)
    except ValueError as exc:
        raise ValueError("frozen_at must be a valid ISO-8601 timestamp") from exc
    if parsed_frozen_at.tzinfo is None or parsed_frozen_at.utcoffset() is None:
        raise ValueError("frozen_at must include a UTC offset")

    targets = (corpus_manifest_path, dataset_path, dataset_manifest_path)
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"freeze targets already exist: {existing}")

    corpus_manifest = build_corpus_manifest(corpus_dir)
    cases = build_frozen_cases(corpus_manifest)
    validation = validate_cases(cases, corpus_manifest, require_frozen_gates=True)
    write_corpus_manifest(corpus_manifest_path, corpus_manifest)
    write_jsonl_exclusive(dataset_path, cases)

    dataset_bytes = dataset_path.read_bytes()
    case_ids = "\n".join(str(case["caseId"]) for case in cases).encode()
    questions = "\n".join(str(case["question"]) for case in cases).encode()
    manifest: dict[str, object] = {
        "datasetName": dataset_path.stem,
        "split": "frozen_test",
        "frozenAt": frozen_at,
        "filename": dataset_path.name,
        "sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "lineCount": len(dataset_bytes.splitlines()),
        "sampleCount": len(cases),
        "idsSha256": hashlib.sha256(case_ids).hexdigest(),
        "questionsSha256": hashlib.sha256(questions).hexdigest(),
        "corpusSha256": corpus_manifest["corpusSha256"],
        "validationReport": validation,
        "contaminationControls": {
            "modelOutputsObservedBeforeFreeze": False,
            "labels": "human_authored_questions_and_corpus_derived_fact_points",
            "frozenResultsMayDrivePromptChanges": False,
        },
    }
    dataset_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with dataset_manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--frozen-at", required=True)
    args = parser.parse_args()
    manifest = freeze_qa_dataset(
        corpus_dir=args.corpus_dir,
        corpus_manifest_path=args.corpus_manifest,
        dataset_path=args.dataset,
        dataset_manifest_path=args.dataset_manifest,
        frozen_at=args.frozen_at,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
