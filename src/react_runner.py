import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urldefrag

from semantic_kernel import Kernel

from src.react_parser import (
    ReactAction,
    ReactFinalAnswer,
    ReactParseError,
    parse_react_output,
)


class TextGenerationModel(Protocol):
    """Minimal model interface required by the ReAct runner."""

    async def generate(self, prompt: str) -> str:
        """Generate one ReAct step from the current prompt."""
        ...


class ToolInvocationError(RuntimeError):
    """Raised when Semantic Kernel cannot execute an approved action."""


PromptBuilder = Callable[[str, tuple[str, ...]], str]

URL_PATTERN = re.compile(r"https?://[^\s\]\[(){}<>\"']+")
SAFE_FALLBACK_PREFIX = "INSUFFICIENT_EVIDENCE:"


@dataclass(frozen=True)
class ReactTraceStep:
    step_number: int
    prompt: str
    raw_model_output: str
    outcome: Literal[
        "action",
        "final",
        "answer_error",
        "parse_error",
        "protocol_error",
        "model_error",
        "tool_error",
        "model_timeout",
        "tool_timeout",
    ]
    thought: str | None = None
    action: str | None = None
    arguments: dict[str, object] | None = None
    observation: str | None = None
    error: str | None = None
    model_latency_ms: float | None = None
    tool_latency_ms: float | None = None
    validation_result: str | None = None
    retry_count: int = 0
    candidate_documents: tuple[dict[str, object], ...] = ()
    read_document_id: str | None = None
    termination_reason: str | None = None


@dataclass(frozen=True)
class ReactRunResult:
    status: Literal[
        "completed",
        "max_steps",
        "parse_error",
        "model_error",
        "tool_error",
        "model_timeout",
        "tool_timeout",
        "evidence_insufficient",
        "correction_limit",
    ]
    question: str
    answer: str | None
    trace: tuple[ReactTraceStep, ...]
    error: str | None = None


class ReactRunner:
    def __init__(
        self,
        kernel: Kernel,
        model: TextGenerationModel,
        prompt_builder: PromptBuilder,
        *,
        plugin_name: str = "azure_docs",
        max_steps: int = 5,
        max_parse_retries: int = 2,
        max_corrections: int = 2,
        model_timeout_seconds: float = 120.0,
        tool_timeout_seconds: float = 10.0,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 必须大于或等于 1")
        if not 0 <= max_parse_retries <= 2:
            raise ValueError("max_parse_retries 必须在 0 到 2 之间")
        if not 0 <= max_corrections <= 2:
            raise ValueError("max_corrections 必须在 0 到 2 之间")
        if model_timeout_seconds <= 0 or tool_timeout_seconds <= 0:
            raise ValueError("timeout 必须大于 0")

        self.kernel = kernel
        self.model = model
        self.prompt_builder = prompt_builder
        self.plugin_name = plugin_name
        self.max_steps = max_steps
        self.max_parse_retries = max_parse_retries
        self.max_corrections = max_corrections
        self.model_timeout_seconds = model_timeout_seconds
        self.tool_timeout_seconds = tool_timeout_seconds

    async def run(self, question: str) -> ReactRunResult:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("用户问题不能为空")

        transcript: list[str] = []
        trace: list[ReactTraceStep] = []
        executed_actions: set[str] = set()
        evidence_urls: set[str] = set()
        observed_document_ids: set[str] = set()
        successful_action_count = 0
        consecutive_parse_errors = 0
        correction_count = 0

        for step_number in range(1, self.max_steps + 1):
            prompt = self.prompt_builder(
                normalized_question,
                tuple(transcript),
            )
            model_started = time.perf_counter()
            try:
                raw_output = await asyncio.wait_for(
                    self.model.generate(prompt),
                    timeout=self.model_timeout_seconds,
                )
            except asyncio.TimeoutError:
                model_latency_ms = (time.perf_counter() - model_started) * 1000
                error = "本地模型生成超时"
                trace.append(
                    ReactTraceStep(
                        step_number=step_number,
                        prompt=prompt,
                        raw_model_output="",
                        outcome="model_timeout",
                        error=error,
                        model_latency_ms=model_latency_ms,
                        termination_reason="model_timeout",
                    )
                )
                return ReactRunResult(
                    status="model_timeout",
                    question=normalized_question,
                    answer=None,
                    trace=tuple(trace),
                    error=error,
                )
            except Exception as exc:
                model_latency_ms = (time.perf_counter() - model_started) * 1000
                error = f"本地模型生成失败：{exc}"
                trace.append(
                    ReactTraceStep(
                        step_number=step_number,
                        prompt=prompt,
                        raw_model_output="",
                        outcome="model_error",
                        error=error,
                        model_latency_ms=model_latency_ms,
                        termination_reason="model_error",
                    )
                )
                return ReactRunResult(
                    status="model_error",
                    question=normalized_question,
                    answer=None,
                    trace=tuple(trace),
                    error=error,
                )
            model_latency_ms = (time.perf_counter() - model_started) * 1000

            try:
                parsed_step = parse_react_output(raw_output)
            except ReactParseError as exc:
                consecutive_parse_errors += 1
                correction_count += 1
                error = str(exc)
                observation = self._format_error_observation(error)
                trace.append(
                    ReactTraceStep(
                        step_number=step_number,
                        prompt=prompt,
                        raw_model_output=raw_output,
                        outcome="parse_error",
                        observation=observation,
                        error=error,
                        model_latency_ms=model_latency_ms,
                        validation_result="invalid_format",
                        retry_count=correction_count,
                        termination_reason=(
                            "parse_error"
                            if consecutive_parse_errors > self.max_parse_retries
                            else (
                                "correction_limit"
                                if correction_count > self.max_corrections
                                else None
                            )
                        ),
                    )
                )
                if consecutive_parse_errors > self.max_parse_retries:
                    return ReactRunResult(
                        status="parse_error",
                        question=normalized_question,
                        answer=None,
                        trace=tuple(trace),
                        error=(
                            "模型连续输出无效 ReAct 格式，已达到纠错上限："
                            f"{self.max_parse_retries}"
                        ),
                    )
                if correction_count > self.max_corrections:
                    return ReactRunResult(
                        status="correction_limit",
                        question=normalized_question,
                        answer=None,
                        trace=tuple(trace),
                        error=f"达到全局纠错上限：{self.max_corrections}",
                    )
                transcript.extend(
                    (
                        raw_output.strip(),
                        f"Observation: {observation}",
                    )
                )
                continue

            consecutive_parse_errors = 0

            if isinstance(parsed_step, ReactFinalAnswer):
                is_safe_fallback = parsed_step.answer.strip().startswith(
                    SAFE_FALLBACK_PREFIX
                )
                if is_safe_fallback and successful_action_count == 0:
                    correction_count += 1
                    error = "安全降级前必须完成至少一次受控检索"
                    observation = json.dumps(
                        {
                            "status": "error",
                            "error": "protocol_error",
                            "message": error,
                        },
                        ensure_ascii=False,
                    )
                    trace.append(
                        ReactTraceStep(
                            step_number=step_number,
                            prompt=prompt,
                            raw_model_output=raw_output,
                            outcome="protocol_error",
                            thought=parsed_step.thought,
                            observation=observation,
                            error=error,
                            model_latency_ms=model_latency_ms,
                            validation_result="retrieval_required",
                            retry_count=correction_count,
                            termination_reason=(
                                "correction_limit"
                                if correction_count > self.max_corrections
                                else None
                            ),
                        )
                    )
                    if correction_count > self.max_corrections:
                        return ReactRunResult(
                            status="correction_limit",
                            question=normalized_question,
                            answer=None,
                            trace=tuple(trace),
                            error=f"达到全局纠错上限：{self.max_corrections}",
                        )
                    transcript.extend(
                        (raw_output.strip(), f"Observation: {observation}")
                    )
                    continue
                if is_safe_fallback:
                    trace.append(
                        ReactTraceStep(
                            step_number=step_number,
                            prompt=prompt,
                            raw_model_output=raw_output,
                            outcome="final",
                            thought=parsed_step.thought,
                            model_latency_ms=model_latency_ms,
                            validation_result="safe_fallback",
                            retry_count=correction_count,
                            termination_reason="insufficient_evidence",
                        )
                    )
                    return ReactRunResult(
                        status="evidence_insufficient",
                        question=normalized_question,
                        answer=parsed_step.answer,
                        trace=tuple(trace),
                    )
                answer_error = self._validate_answer_sources(
                    parsed_step.answer,
                    evidence_urls,
                )
                if answer_error is not None:
                    correction_count += 1
                    observation = json.dumps(
                        {
                            "status": "error",
                            "error": "invalid_answer_sources",
                            "message": answer_error,
                            "allowedSourceUrls": sorted(evidence_urls),
                        }
                    )
                    trace.append(
                        ReactTraceStep(
                            step_number=step_number,
                            prompt=prompt,
                            raw_model_output=raw_output,
                            outcome="answer_error",
                            thought=parsed_step.thought,
                            observation=observation,
                            error=answer_error,
                            model_latency_ms=model_latency_ms,
                            validation_result="invalid_sources",
                            retry_count=correction_count,
                            termination_reason=(
                                "correction_limit"
                                if correction_count > self.max_corrections
                                else None
                            ),
                        )
                    )
                    transcript.extend(
                        (
                            raw_output.strip(),
                            f"Observation: {observation}",
                        )
                    )
                    if correction_count > self.max_corrections:
                        return ReactRunResult(
                            status="correction_limit",
                            question=normalized_question,
                            answer=None,
                            trace=tuple(trace),
                            error=f"达到全局纠错上限：{self.max_corrections}",
                        )
                    continue

                trace.append(
                    ReactTraceStep(
                        step_number=step_number,
                        prompt=prompt,
                        raw_model_output=raw_output,
                        outcome="final",
                        thought=parsed_step.thought,
                        model_latency_ms=model_latency_ms,
                        validation_result="valid_sources",
                        retry_count=correction_count,
                        termination_reason="completed",
                    )
                )
                return ReactRunResult(
                    status="completed",
                    question=normalized_question,
                    answer=parsed_step.answer,
                    trace=tuple(trace),
                )

            protocol_error = self._validate_action_state(
                parsed_step,
                successful_action_count=successful_action_count,
                observed_document_ids=observed_document_ids,
            )
            action_signature = self._action_signature(parsed_step)
            was_duplicate = (
                protocol_error is None and action_signature in executed_actions
            )
            tool_latency_ms: float | None = None
            if protocol_error is not None:
                correction_count += 1
                observation = json.dumps(
                    {
                        "status": "error",
                        "error": "protocol_error",
                        "message": protocol_error,
                    },
                    ensure_ascii=False,
                )
            elif was_duplicate:
                correction_count += 1
                observation = json.dumps(
                    {
                        "status": "error",
                        "error": "duplicate_action",
                        "message": (
                            "This exact action has already been executed. "
                            "Use the existing observations and produce a Final Answer."
                        ),
                    }
                )
            else:
                tool_started = time.perf_counter()
                try:
                    observation = await asyncio.wait_for(
                        self._invoke_action(parsed_step),
                        timeout=self.tool_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    tool_latency_ms = (time.perf_counter() - tool_started) * 1000
                    error = "插件调用超时"
                    trace.append(
                        ReactTraceStep(
                            step_number=step_number,
                            prompt=prompt,
                            raw_model_output=raw_output,
                            outcome="tool_timeout",
                            thought=parsed_step.thought,
                            action=parsed_step.action,
                            arguments=dict(parsed_step.arguments),
                            error=error,
                            model_latency_ms=model_latency_ms,
                            tool_latency_ms=tool_latency_ms,
                            retry_count=correction_count,
                            termination_reason="tool_timeout",
                        )
                    )
                    return ReactRunResult(
                        status="tool_timeout",
                        question=normalized_question,
                        answer=None,
                        trace=tuple(trace),
                        error=error,
                    )
                except ToolInvocationError as exc:
                    tool_latency_ms = (time.perf_counter() - tool_started) * 1000
                    error = str(exc)
                    trace.append(
                        ReactTraceStep(
                            step_number=step_number,
                            prompt=prompt,
                            raw_model_output=raw_output,
                            outcome="tool_error",
                            thought=parsed_step.thought,
                            action=parsed_step.action,
                            arguments=dict(parsed_step.arguments),
                            error=error,
                            model_latency_ms=model_latency_ms,
                            tool_latency_ms=tool_latency_ms,
                            retry_count=correction_count,
                            termination_reason="tool_error",
                        )
                    )
                    return ReactRunResult(
                        status="tool_error",
                        question=normalized_question,
                        answer=None,
                        trace=tuple(trace),
                        error=error,
                    )
                tool_latency_ms = (time.perf_counter() - tool_started) * 1000
                observation_succeeded = self._observation_succeeded(observation)
                if observation_succeeded:
                    executed_actions.add(action_signature)
                    successful_action_count += 1

            if self._observation_succeeded(observation):
                evidence_urls.update(URL_PATTERN.findall(observation))
                observed_document_ids.update(self._extract_document_ids(observation))
            trace.append(
                ReactTraceStep(
                    step_number=step_number,
                    prompt=prompt,
                    raw_model_output=raw_output,
                    outcome=(
                        "protocol_error" if protocol_error is not None else "action"
                    ),
                    thought=parsed_step.thought,
                    action=parsed_step.action,
                    arguments=dict(parsed_step.arguments),
                    observation=observation,
                    model_latency_ms=model_latency_ms,
                    tool_latency_ms=tool_latency_ms,
                    validation_result=(
                        "protocol_error"
                        if protocol_error is not None
                        else (
                            "duplicate_action"
                            if was_duplicate
                            else "observation_validated"
                        )
                    ),
                    retry_count=correction_count,
                    candidate_documents=self._extract_candidates(observation),
                    read_document_id=(
                        str(parsed_step.arguments.get("document_id"))
                        if parsed_step.action == "read_document"
                        else None
                    ),
                    termination_reason=(
                        "correction_limit"
                        if correction_count > self.max_corrections
                        else None
                    ),
                )
            )
            if correction_count > self.max_corrections:
                return ReactRunResult(
                    status="correction_limit",
                    question=normalized_question,
                    answer=None,
                    trace=tuple(trace),
                    error=f"达到全局纠错上限：{self.max_corrections}",
                )
            transcript.extend(
                (
                    raw_output.strip(),
                    f"Observation: {observation}",
                )
            )

        return ReactRunResult(
            status="max_steps",
            question=normalized_question,
            answer=None,
            trace=tuple(trace),
            error=f"达到最大 ReAct 步数：{self.max_steps}",
        )

    @staticmethod
    def _format_error_observation(error: str) -> str:
        return json.dumps(
            {
                "status": "error",
                "error": "format_error",
                "message": error,
                "requiredFormats": {
                    "action": (
                        "Thought: <one sentence>\\n"
                        "Action: <search_documents or read_document>\\n"
                        "Action Input: <one JSON object>"
                    ),
                    "final": (
                        "Thought: <one sentence>\\n"
                        "Final Answer: <answer with observed source URL>"
                    ),
                },
                "instruction": (
                    "Correct the format in the next response. Emit exactly "
                    "one Action or one Final Answer. Do not emit Observation."
                ),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _action_signature(step: ReactAction) -> str:
        arguments = json.dumps(
            step.arguments,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return f"{step.action}:{arguments}"

    @staticmethod
    def _validate_action_state(
        step: ReactAction,
        *,
        successful_action_count: int,
        observed_document_ids: set[str],
    ) -> str | None:
        if successful_action_count == 0 and step.action != "search_documents":
            return "The first valid action must be search_documents"

        if step.action == "read_document":
            document_id = str(step.arguments["document_id"]).strip()
            if document_id not in observed_document_ids:
                return (
                    "read_document may only use an exact documentId returned "
                    "by a previous search_documents Observation"
                )
        return None

    @staticmethod
    def _extract_document_ids(observation: str) -> set[str]:
        try:
            payload = json.loads(observation)
        except (json.JSONDecodeError, TypeError):
            return set()

        ids: set[str] = set()
        if isinstance(payload, dict):
            document_id = payload.get("documentId")
            if isinstance(document_id, str) and document_id.strip():
                ids.add(document_id.strip())
            results = payload.get("results")
            if isinstance(results, list):
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    candidate = result.get("documentId")
                    if isinstance(candidate, str) and candidate.strip():
                        ids.add(candidate.strip())
        return ids

    @staticmethod
    def _extract_candidates(observation: str) -> tuple[dict[str, object], ...]:
        try:
            payload = json.loads(observation)
        except (json.JSONDecodeError, TypeError):
            return ()
        if not isinstance(payload, dict):
            return ()
        telemetry = payload.get("telemetry")
        if not isinstance(telemetry, dict):
            return ()
        candidates = telemetry.get("candidates")
        if not isinstance(candidates, list):
            return ()
        return tuple(dict(item) for item in candidates if isinstance(item, dict))

    @staticmethod
    def _observation_succeeded(observation: str) -> bool:
        """Return True only for an explicit structured success response."""
        try:
            payload = json.loads(observation)
        except (json.JSONDecodeError, TypeError):
            return False
        return isinstance(payload, dict) and payload.get("status") == "success"

    @staticmethod
    def _validate_answer_sources(
        answer: str,
        evidence_urls: set[str],
    ) -> str | None:
        answer_urls = set(URL_PATTERN.findall(answer))
        if not answer_urls:
            return "Final Answer 必须包含至少一个来自 Observation 的来源 URL"

        evidence_documents = {urldefrag(url).url for url in evidence_urls}
        invalid_urls = {
            url for url in answer_urls if urldefrag(url).url not in evidence_documents
        }
        if invalid_urls:
            invalid = ", ".join(sorted(invalid_urls))
            return f"Final Answer 包含未在 Observation 中出现的 URL：{invalid}"

        return None

    async def _invoke_action(
        self,
        step: ReactAction,
    ) -> str:
        try:
            result = await self.kernel.invoke(
                plugin_name=self.plugin_name,
                function_name=step.action,
                **step.arguments,
            )
            if result is None:
                raise RuntimeError("插件没有返回结果")
            return str(result)
        except Exception as exc:
            raise ToolInvocationError(f"插件调用失败：{exc}") from exc


def build_test_prompt(
    question: str,
    transcript: tuple[str, ...],
) -> str:
    """Small deterministic prompt used only for runner tests."""
    history = "\n".join(transcript) if transcript else "(none)"
    return f"Question: {question}\nHistory:\n{history}"


class ScriptedModel:
    """Deterministic fake model used to test orchestration without inference."""

    def __init__(self, outputs: list[str]) -> None:
        if not outputs:
            raise ValueError("outputs 不能为空")
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._outputs:
            raise RuntimeError("假模型没有剩余输出")
        return self._outputs.pop(0)
