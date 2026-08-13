import json


SYSTEM_INSTRUCTIONS = """You are a deterministic local Azure documentation ReAct agent.
You must use only evidence returned by the local tools. Never answer from memory.

STATE MACHINE (mandatory):
STATE 1 - no successful tool Observation exists:
- Output exactly one search_documents action. A Final Answer is forbidden.

STATE 2 - at least one successful tool Observation exists:
- If evidence is insufficient, output exactly one new Action.
- If evidence is sufficient, output exactly one Final Answer with observed source URLs.
- Never repeat an Action with identical arguments.

The application, not you, executes Actions and writes Observation lines.
NEVER generate, predict, simulate, or continue an Observation yourself.
Stop immediately after the one-line Action Input JSON or after the Final Answer.

AVAILABLE ACTIONS:
search_documents
Input: {"query":"<concise English query>","top_k":<integer 1-5>}
Purpose: find relevant local Azure documentation. This must be the first action.

read_document
Input: {"document_id":"<exact documentId from a search Observation>"}
Purpose: read a full document only if search snippets are insufficient.

VALID ACTION FORMAT - exactly three labeled fields:
Thought: <one short sentence>
Action: <search_documents or read_document>
Action Input: <one JSON object on one line>

VALID FINAL FORMAT:
Thought: <one short sentence explaining why evidence is sufficient>
Final Answer: <answer in the same language as the user's question>
Sources:
- <exact source URL from an Observation>

VALID FIRST-STEP EXAMPLE:
Thought: I need local documentation evidence before answering.
Action: search_documents
Action Input: {"query":"Azure availability zone datacenter failure","top_k":3}

VALID LATER-STEP EXAMPLE:
Thought: The observed snippets contain enough evidence to answer.
Final Answer: Availability zones provide datacenter-level fault isolation.
Sources:
- https://learn.microsoft.com/en-us/azure/reliability/availability-zones-overview

INVALID OUTPUTS:
- Final Answer before any Observation.
- Thought, Action, Action Input, and Observation all in one response.
- More than one Action.
- Markdown fences, commentary, invented IDs, invented URLs, or Python dictionaries.
- Action: Final Answer. Final Answer is a label, never an Action name.

If the latest Observation reports format_error, correct only the format and emit one valid next step.
"""


def build_react_prompt(
    question: str,
    transcript: tuple[str, ...],
) -> str:
    """Build a state-explicit Phi-3 chat prompt for one ReAct step."""
    history = "\n".join(transcript).strip()

    observation_payloads = tuple(
        payload
        for entry in transcript
        if (payload := _parse_observation(entry)) is not None
    )
    latest_observation = (
        observation_payloads[-1] if observation_payloads else None
    )
    latest_is_format_error = bool(
        latest_observation
        and latest_observation.get("error") == "format_error"
    )
    has_successful_observation = any(
        payload.get("status") == "success"
        for payload in observation_payloads
    )

    if latest_is_format_error:
        state_instruction = (
            "CURRENT STATE: FORMAT RECOVERY. The previous model output was "
            "rejected by the application. Preserve the intended decision, "
            "but emit it again using exactly one valid Action block or one "
            "valid Final Answer block. Never emit an Observation."
        )
        history_block = f"ReAct history:\n{history}\n\n"
    elif has_successful_observation:
        state_instruction = (
            "CURRENT STATE: STATE 2. One or more application-generated "
            "Observations exist below. Use them. Emit exactly one new Action "
            "or one Final Answer. Do not emit an Observation."
        )
        history_block = f"ReAct history:\n{history}\n\n"
    else:
        state_instruction = (
            "CURRENT STATE: STATE 1. No successful tool Observation exists. "
            "You MUST call search_documents now. Do not answer the question "
            "yet."
        )
        history_block = f"ReAct history:\n{history}\n\n" if history else ""

    user_content = (
        f"Question: {question}\n\n"
        f"{state_instruction}\n\n"
        f"{history_block}"
        "Produce the next single ReAct step and stop."
    )

    return (
        "<|system|>\n"
        f"{SYSTEM_INSTRUCTIONS.strip()}<|end|>\n"
        "<|user|>\n"
        f"{user_content}<|end|>\n"
        "<|assistant|>\n"
    )


def _parse_observation(entry: str) -> dict[str, object] | None:
    prefix = "Observation:"
    if not entry.lstrip().startswith(prefix):
        return None
    raw_payload = entry.lstrip()[len(prefix) :].strip()
    try:
        payload = json.loads(raw_payload)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None
