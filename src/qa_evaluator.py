import json
import math
import re
from collections import defaultdict
from urllib.parse import urldefrag


URL_PATTERN = re.compile(r"https?://[^\s\]\[(){}<>\"']+")
INVALID_OUTCOMES = {"parse_error", "answer_error", "protocol_error"}
SAFE_TERMINAL_STATUSES = {
    "evidence_insufficient", "model_timeout", "tool_timeout", "tool_error",
    "model_error", "parse_error", "correction_limit", "max_steps",
}
ACTION_ALLOWLIST = {"search_documents", "read_document"}


def _observed_evidence(trace: list[dict[str, object]]) -> tuple[set[str], set[str]]:
    sources: set[str] = set()
    document_ids: set[str] = set()
    for step in trace:
        observation = step.get("observation")
        if not isinstance(observation, str):
            continue
        try:
            payload = json.loads(observation)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("status") != "success":
            continue
        sources.update(URL_PATTERN.findall(observation))
        document_id = payload.get("documentId")
        if isinstance(document_id, str):
            document_ids.add(document_id)
        results = payload.get("results")
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                candidate = item.get("documentId")
                if isinstance(candidate, str):
                    document_ids.add(candidate)
    return sources, document_ids


def _dual_rubric(case: dict[str, object], prediction: dict[str, object]) -> tuple[float, float]:
    facts = case["goldFactPoints"]
    reviews = prediction.get("rubricReviews")
    if not isinstance(facts, list) or not isinstance(reviews, list) or len(reviews) < 2:
        raise ValueError("answerable cases require two rubric reviews")
    first, second = reviews[0], reviews[1]
    if not isinstance(first, dict) or not isinstance(second, dict):
        raise ValueError("invalid rubric review")
    if first.get("reviewerId") == second.get("reviewerId"):
        raise ValueError("rubric reviewers must be distinct")
    scores_a = first.get("factPointScores")
    scores_b = second.get("factPointScores")
    if not isinstance(scores_a, list) or not isinstance(scores_b, list):
        raise ValueError("rubric fact scores must be lists")
    if len(scores_a) != len(facts) or len(scores_b) != len(facts):
        raise ValueError("rubric score count must match gold facts")
    if not all(isinstance(value, bool) for value in scores_a + scores_b):
        raise ValueError("rubric fact scores must be boolean")
    consensus = sum(a and b for a, b in zip(scores_a, scores_b)) / len(facts)
    agreement = sum(a == b for a, b in zip(scores_a, scores_b)) / len(facts)
    return consensus, agreement


def score_case(case: dict[str, object], prediction: dict[str, object]) -> dict[str, object]:
    if prediction.get("caseId") != case.get("caseId"):
        raise ValueError("case identity mismatch")
    trace = prediction.get("trace", [])
    if not isinstance(trace, list):
        raise ValueError("trace must be a list")
    answerability = case.get("answerability")
    status = prediction.get("status")
    answer = prediction.get("answer")
    observed_sources, observed_documents = _observed_evidence(trace)
    errors: list[str] = []

    answer_accuracy: float | None = None
    rubric_agreement: float | None = None
    if answerability == "answerable":
        answer_accuracy, rubric_agreement = _dual_rubric(case, prediction)

    answer_urls = set(URL_PATTERN.findall(answer)) if isinstance(answer, str) else set()
    # The frozen metric contract fixes the denominator at completed answers:
    # validly_cited_answers / completed_answers. A case that never produced an
    # answer has no citation to judge and leaves the denominator entirely; it is
    # counted by answerCoverageRate instead, so a high citation validity can
    # never be quoted without the coverage it was measured over.
    answer_produced = answerability == "answerable" and status == "completed"
    if answer_produced:
        allowed = {urldefrag(str(url)).url for url in case.get("goldSources", [])}
        observed = {urldefrag(url).url for url in observed_sources}
        valid_count = sum(urldefrag(url).url in allowed & observed for url in answer_urls)
        valid_citation_rate: float | None = (
            valid_count / len(answer_urls) if answer_urls else 0.0
        )
        if valid_citation_rate < 1.0:
            errors.append("fabricated_citation")
    else:
        valid_citation_rate = None

    required_documents = set(str(item) for item in case.get("requiredDocumentIds", []))
    document_hit: bool | None = (
        required_documents.issubset(observed_documents)
        if answerability == "answerable"
        else None
    )
    invalid_seen = any(step.get("outcome") in INVALID_OUTCOMES for step in trace)
    recovered = invalid_seen and status == "completed"
    unanswerable_recognized = (
        answerability == "unanswerable" and status == "evidence_insufficient"
    )
    safe_degradation = status in SAFE_TERMINAL_STATUSES
    illegal_execution_count = sum(
        bool(step.get("executed"))
        and (
            step.get("action") not in ACTION_ALLOWLIST
            or step.get("outcome") in {"protocol_error", "parse_error"}
        )
        for step in trace
    )
    return {
        "caseId": case["caseId"],
        "language": case.get("language"),
        "category": case.get("category"),
        "difficulty": case.get("difficulty"),
        "answerAccuracy": answer_accuracy,
        "rubricAgreement": rubric_agreement,
        "validCitationRate": valid_citation_rate,
        "answerProduced": answer_produced,
        "documentHit": document_hit,
        "unanswerableRecognized": unanswerable_recognized,
        "recoveryAttempted": invalid_seen,
        "recovered": recovered,
        "safeDegradation": safe_degradation,
        "illegalExecutionCount": illegal_execution_count,
        "latencyMs": float(prediction.get("latencyMs", 0.0)),
        "cacheHit": bool(prediction.get("cacheHit", False)),
        "errors": errors,
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _mean_present(scores: list[dict[str, object]], key: str) -> float | None:
    values = [float(score[key]) for score in scores if score.get(key) is not None]
    return sum(values) / len(values) if values else None


def _bool_rate_present(scores: list[dict[str, object]], key: str) -> float | None:
    values = [bool(score[key]) for score in scores if score.get(key) is not None]
    return sum(values) / len(values) if values else None


def summarize_scores(scores: list[dict[str, object]]) -> dict[str, object]:
    attempted = sum(bool(score.get("recoveryAttempted")) for score in scores)
    latencies = [float(score["latencyMs"]) for score in scores]
    grouped: dict[str, dict[str, dict[str, object]]] = {}
    for field in ("language", "category", "difficulty"):
        buckets: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
        for score in scores:
            buckets[str(score.get(field))].append(score)
        grouped[field] = {
            name: {
                "caseCount": len(items),
                "answerAccuracy": _mean_present(items, "answerAccuracy"),
                "validCitationRate": _mean_present(items, "validCitationRate"),
                "documentHitRate": _bool_rate_present(items, "documentHit"),
            }
            for name, items in sorted(buckets.items())
        }
    return {
        "caseCount": len(scores),
        "answerAccuracy": _mean_present(scores, "answerAccuracy"),
        "rubricAgreement": _mean_present(scores, "rubricAgreement"),
        "validCitationRate": _mean_present(scores, "validCitationRate"),
        "answerCoverageRate": (
            sum(bool(score.get("answerProduced")) for score in scores)
            / sum(score.get("answerAccuracy") is not None for score in scores)
            if any(score.get("answerAccuracy") is not None for score in scores)
            else None
        ),
        "documentHitRate": _bool_rate_present(scores, "documentHit"),
        "unanswerableRecognitionRate": (
            sum(bool(score.get("unanswerableRecognized")) for score in scores)
            / sum(score.get("answerAccuracy") is None for score in scores)
            if any(score.get("answerAccuracy") is None for score in scores)
            else None
        ),
        "recoveryRate": sum(bool(score.get("recovered")) for score in scores) / attempted if attempted else None,
        "safeDegradationCount": sum(bool(score.get("safeDegradation")) for score in scores),
        "illegalExecutionCount": sum(int(score.get("illegalExecutionCount", 0)) for score in scores),
        "cacheHitRate": sum(bool(score.get("cacheHit")) for score in scores) / len(scores) if scores else 0.0,
        "latencyMs": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
        },
        "byGroup": grouped,
    }
