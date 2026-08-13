import unittest

from src.react_prompt import build_react_prompt


class ReactPromptTests(unittest.TestCase):
    def test_first_step_requires_search(self) -> None:
        prompt = build_react_prompt("Which disk suits backups?", ())

        self.assertIn("CURRENT STATE: STATE 1", prompt)
        self.assertIn("MUST call search_documents", prompt)
        self.assertIn("NEVER generate", prompt)
        self.assertTrue(prompt.endswith("<|assistant|>\n"))

    def test_history_is_included_verbatim(self) -> None:
        history = (
            "Thought: Search first.\nAction: search_documents\n"
            'Action Input: {"query":"Azure disks"}',
            'Observation: {"status":"success"}',
        )

        prompt = build_react_prompt("Question", history)

        self.assertIn(history[0], prompt)
        self.assertIn(history[1], prompt)
        self.assertIn("CURRENT STATE: STATE 2", prompt)
        self.assertIn("Do not emit an Observation", prompt)
        self.assertIn("Produce the next single ReAct step", prompt)

    def test_prompt_contains_valid_examples_and_invalid_patterns(self) -> None:
        prompt = build_react_prompt("Question", ())

        self.assertIn("VALID FIRST-STEP EXAMPLE", prompt)
        self.assertIn("VALID LATER-STEP EXAMPLE", prompt)
        self.assertIn("INVALID OUTPUTS", prompt)
        self.assertIn("format_error", prompt)

    def test_format_error_selects_recovery_state(self) -> None:
        history = (
            "unstructured output",
            'Observation: {"status": "error", "error": "format_error"}',
        )

        prompt = build_react_prompt("Question", history)

        self.assertIn("CURRENT STATE: FORMAT RECOVERY", prompt)
        self.assertIn("Never emit an Observation", prompt)

    def test_old_format_error_does_not_make_recovery_state_permanent(self) -> None:
        history = (
            "bad output",
            'Observation: {"status":"error","error":"format_error"}',
            "Thought: Search correctly.\nAction: search_documents\n"
            'Action Input: {"query":"Azure disks"}',
            'Observation: {"status":"success","results":[]}',
        )

        prompt = build_react_prompt("Question", history)

        self.assertIn("CURRENT STATE: STATE 2", prompt)
        self.assertNotIn("CURRENT STATE: FORMAT RECOVERY", prompt)

    def test_error_observation_does_not_unlock_answer_state(self) -> None:
        history = (
            "Thought: Search.\nAction: search_documents\n"
            'Action Input: {"query":""}',
            'Observation: {"status":"error","error":"invalid_query"}',
        )

        prompt = build_react_prompt("Question", history)

        self.assertIn("CURRENT STATE: STATE 1", prompt)
        self.assertIn("MUST call search_documents", prompt)


if __name__ == "__main__":
    unittest.main()
