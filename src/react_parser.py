import json
import re
from dataclasses import dataclass
from typing import Any, Literal


ALLOWED_ACTIONS = {
    "search_documents",
    "read_document",
}

CODE_FENCE_PATTERN = re.compile(
    r"^\s*```(?:text|json|markdown)?\s*\n(?P<body>.*?)\n```\s*$",
    re.IGNORECASE | re.DOTALL,
)
LABEL_PATTERN = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?"
    r"(?P<label>Thought|Action\s+Input|Action|Final\s+Answer)"
    r"\s*[:：]\s*"
)


class ReactParseError(ValueError):
    """Raised when a model response cannot be safely parsed as one ReAct step."""


@dataclass(frozen=True)
class ReactAction:
    kind: Literal["action"]
    thought: str
    action: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ReactFinalAnswer:
    kind: Literal["final"]
    thought: str
    answer: str


ReactStep = ReactAction | ReactFinalAnswer


def parse_react_output(raw_output: str) -> ReactStep:
    """Parse one ReAct action or final answer with bounded syntax tolerance.

    The parser tolerates presentation-only differences such as a single outer
    code fence, label casing, a full-width colon, list bullets, and multiline
    JSON. It never guesses action names, adds parameters, or accepts multiple
    actions/final answers.
    """
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise ReactParseError("模型输出为空")

    text = _strip_outer_code_fence(raw_output.strip())
    fields = _extract_fields(text)

    thoughts = fields.get("thought", [])
    actions = fields.get("action", [])
    action_inputs = fields.get("action input", [])
    final_answers = fields.get("final answer", [])

    if len(thoughts) != 1:
        raise ReactParseError("输出必须且只能包含一个 Thought")

    thought = thoughts[0].strip()
    if not thought:
        raise ReactParseError("Thought 不能为空")

    has_action = bool(actions or action_inputs)
    has_final = bool(final_answers)
    if has_action and has_final:
        raise ReactParseError("同一轮不能同时包含 Action 和 Final Answer")

    if has_action:
        if len(actions) != 1 or len(action_inputs) != 1:
            raise ReactParseError(
                "工具调用必须且只能包含一个 Action 和一个 Action Input"
            )

        action = actions[0].strip().lower()
        if not re.fullmatch(r"[a-z_]+", action):
            raise ReactParseError(f"Action 名称格式无效：{action}")
        if action not in ALLOWED_ACTIONS:
            raise ReactParseError(f"未知 Action：{action}")

        arguments = _parse_action_input(action_inputs[0])
        _validate_action_arguments(action, arguments)
        return ReactAction(
            kind="action",
            thought=thought,
            action=action,
            arguments=arguments,
        )

    if has_final:
        if len(final_answers) != 1:
            raise ReactParseError("输出必须且只能包含一个 Final Answer")
        answer = final_answers[0].strip()
        if not answer:
            raise ReactParseError("Final Answer 不能为空")
        return ReactFinalAnswer(
            kind="final",
            thought=thought,
            answer=answer,
        )

    raise ReactParseError(
        "输出缺少 Action + Action Input 或 Final Answer"
    )


def _strip_outer_code_fence(text: str) -> str:
    match = CODE_FENCE_PATTERN.fullmatch(text)
    return match.group("body").strip() if match else text


def _extract_fields(text: str) -> dict[str, list[str]]:
    matches = list(LABEL_PATTERN.finditer(text))
    if not matches:
        raise ReactParseError("未找到 ReAct 标签")

    leading_text = text[: matches[0].start()].strip()
    if leading_text:
        raise ReactParseError("第一个 ReAct 标签前不能包含额外内容")

    fields: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        value_start = match.end()
        value_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
        label = re.sub(r"\s+", " ", match.group("label").lower())
        value = text[value_start:value_end].strip()
        fields.setdefault(label, []).append(value)
    return fields


def _parse_action_input(raw_input: str) -> dict[str, Any]:
    candidate = raw_input.strip()
    json_match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if json_match is None:
        raise ReactParseError("Action Input 必须包含 JSON 对象")

    prefix = candidate[: json_match.start()].strip()
    suffix = candidate[json_match.end() :].strip()
    if prefix or suffix:
        raise ReactParseError("Action Input 的 JSON 对象前后不能包含额外内容")

    try:
        arguments = json.loads(json_match.group(0))
    except json.JSONDecodeError as exc:
        raise ReactParseError(
            f"Action Input 不是合法 JSON：{exc.msg}"
        ) from exc

    if not isinstance(arguments, dict):
        raise ReactParseError("Action Input 必须是 JSON 对象")
    return arguments


def _validate_action_arguments(
    action: str,
    arguments: dict[str, Any],
) -> None:
    if action == "search_documents":
        allowed_keys = {"query", "top_k"}
        required_keys = {"query"}
    else:
        allowed_keys = {"document_id"}
        required_keys = {"document_id"}

    argument_keys = set(arguments)
    missing_keys = required_keys - argument_keys
    extra_keys = argument_keys - allowed_keys

    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise ReactParseError(f"Action Input 缺少参数：{missing}")
    if extra_keys:
        extra = ", ".join(sorted(extra_keys))
        raise ReactParseError(f"Action Input 包含多余参数：{extra}")

    if action == "search_documents":
        query = arguments["query"]
        if not isinstance(query, str) or not query.strip():
            raise ReactParseError("query 必须是非空字符串")

        top_k = arguments.get("top_k", 3)
        if isinstance(top_k, bool) or not isinstance(top_k, int):
            raise ReactParseError("top_k 必须是整数")
        if top_k < 1 or top_k > 5:
            raise ReactParseError("top_k 必须在 1 至 5 之间")
        return

    document_id = arguments["document_id"]
    if not isinstance(document_id, str) or not document_id.strip():
        raise ReactParseError("document_id 必须是非空字符串")
