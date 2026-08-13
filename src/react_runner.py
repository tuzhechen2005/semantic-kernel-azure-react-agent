import json
import re
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
    ]
    thought: str | None = None
    action: str | None = None
    arguments: dict[str, object] | None = None
    observation: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ReactRunResult:
    status: Literal[
        "completed",
        "max_steps",
        "parse_error",
        "model_error",
        "tool_error",
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
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 必须大于或等于 1")
        if max_parse_retries < 0:
            raise ValueError("max_parse_retries 必须大于或等于 0")

        self.kernel = kernel
        self.model = model
        self.prompt_builder = prompt_builder
        self.plugin_name = plugin_name
        self.max_steps = max_steps
        self.max_parse_retries = max_parse_retries

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

        for step_number in range(1, self.max_steps + 1):
            prompt = self.prompt_builder(
                normalized_question,
                tuple(transcript),
            )
            try:
                raw_output = await self.model.generate(prompt)
            except Exception as exc:
                error = f"本地模型生成失败：{exc}"
                trace.append(
                    ReactTraceStep(
                        step_number=step_number,
                        prompt=prompt,
                        raw_model_output="",
                        outcome="model_error",
                        error=error,
                    )
                )
                return ReactRunResult(
                    status="model_error",
                    question=normalized_question,
                    answer=None,
                    trace=tuple(trace),
                    error=error,
                )

            try:
                parsed_step = parse_react_output(raw_output)
            except ReactParseError as exc:
                consecutive_parse_errors += 1
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
                transcript.extend(
                    (
                        raw_output.strip(),
                        f"Observation: {observation}",
                    )
                )
                continue

            consecutive_parse_errors = 0

            if isinstance(parsed_step, ReactFinalAnswer):
                answer_error = self._validate_answer_sources(
                    parsed_step.answer,
                    evidence_urls,
                )
                if answer_error is not None:
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
                        )
                    )
                    transcript.extend(
                        (
                            raw_output.strip(),
                            f"Observation: {observation}",
                        )
                    )
                    continue

                trace.append(
                    ReactTraceStep(
                        step_number=step_number,
                        prompt=prompt,
                        raw_model_output=raw_output,
                        outcome="final",
                        thought=parsed_step.thought,
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
            if protocol_error is not None:
                observation = json.dumps(
                    {
                        "status": "error",
                        "error": "protocol_error",
                        "message": protocol_error,
                    },
                    ensure_ascii=False,
                )
            elif action_signature in executed_actions:
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
                try:
                    observation = await self._invoke_action(parsed_step)
                except ToolInvocationError as exc:
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
                        )
                    )
                    return ReactRunResult(
                        status="tool_error",
                        question=normalized_question,
                        answer=None,
                        trace=tuple(trace),
                        error=error,
                    )
                observation_succeeded = self._observation_succeeded(
                    observation
                )
                if observation_succeeded:
                    executed_actions.add(action_signature)
                    successful_action_count += 1

            if self._observation_succeeded(observation):
                evidence_urls.update(URL_PATTERN.findall(observation))
                observed_document_ids.update(
                    self._extract_document_ids(observation)
                )
            trace.append(
                ReactTraceStep(
                    step_number=step_number,
                    prompt=prompt,
                    raw_model_output=raw_output,
                    outcome=(
                        "protocol_error"
                        if protocol_error is not None
                        else "action"
                    ),
                    thought=parsed_step.thought,
                    action=parsed_step.action,
                    arguments=dict(parsed_step.arguments),
                    observation=observation,
                )
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
    def _observation_succeeded(observation: str) -> bool:
        """Return True only for an explicit structured success response."""
        try:
            payload = json.loads(observation)
        except (json.JSONDecodeError, TypeError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("status") == "success"
        )

    @staticmethod
    def _validate_answer_sources(
        answer: str,
        evidence_urls: set[str],
    ) -> str | None:
        answer_urls = set(URL_PATTERN.findall(answer))
        if not answer_urls:
            return "Final Answer 必须包含至少一个来自 Observation 的来源 URL"

        evidence_documents = {
            urldefrag(url).url
            for url in evidence_urls
        }
        invalid_urls = {
            url
            for url in answer_urls
            if urldefrag(url).url not in evidence_documents
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
