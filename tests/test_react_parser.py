import unittest

from src.react_parser import (
    ReactAction,
    ReactFinalAnswer,
    ReactParseError,
    parse_react_output,
)


class ReactParserTests(unittest.TestCase):
    def test_parses_search_action(self) -> None:
        result = parse_react_output(
            "Thought: I need relevant disk documentation.\n"
            "Action: search_documents\n"
            'Action Input: {"query":"Azure disk backup","top_k":2}'
        )

        self.assertIsInstance(result, ReactAction)
        self.assertEqual(result.action, "search_documents")
        self.assertEqual(
            result.arguments,
            {"query": "Azure disk backup", "top_k": 2},
        )

    def test_parses_read_action(self) -> None:
        result = parse_react_output(
            "Thought: I should read the selected document.\n"
            "Action: read_document\n"
            'Action Input: {"document_id":"managed_disk_types"}'
        )

        self.assertIsInstance(result, ReactAction)
        self.assertEqual(result.action, "read_document")

    def test_parses_multiline_final_answer(self) -> None:
        result = parse_react_output(
            "Thought: The observation is sufficient.\n"
            "Final Answer: Standard HDD is suitable for backups.\n"
            "Source: Azure Managed Disk Types"
        )

        self.assertIsInstance(result, ReactFinalAnswer)
        self.assertIn("Standard HDD", result.answer)
        self.assertIn("Source:", result.answer)

    def test_rejects_unknown_action(self) -> None:
        with self.assertRaisesRegex(ReactParseError, "未知 Action"):
            parse_react_output(
                "Thought: I will access another file.\n"
                "Action: read_file\n"
                'Action Input: {"path":"../../secret"}'
            )

    def test_accepts_safe_presentation_variations(self) -> None:
        result = parse_react_output(
            "```text\n"
            "- thought： Search first.\n"
            "- ACTION： SEARCH_DOCUMENTS\n"
            "- Action Input： {\n"
            '  "query": "Azure zones",\n'
            '  "top_k": 2\n'
            "}\n"
            "```"
        )

        self.assertIsInstance(result, ReactAction)
        self.assertEqual(result.action, "search_documents")
        self.assertEqual(result.arguments["top_k"], 2)

    def test_rejects_leading_commentary(self) -> None:
        with self.assertRaisesRegex(ReactParseError, "额外内容"):
            parse_react_output(
                "Here is the next step:\n"
                "Thought: Search first.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure zones"}'
            )

    def test_rejects_extra_argument(self) -> None:
        with self.assertRaisesRegex(ReactParseError, "多余参数"):
            parse_react_output(
                "Thought: Search first.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure zones","path":"/tmp"}'
            )

    def test_rejects_invalid_top_k(self) -> None:
        with self.assertRaisesRegex(ReactParseError, "1 至 5"):
            parse_react_output(
                "Thought: Search many documents.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure zones","top_k":100}'
            )

    def test_rejects_extra_action_before_final_answer(self) -> None:
        with self.assertRaises(ReactParseError):
            parse_react_output(
                "Thought: Evidence is sufficient.\n"
                "Action: Final Answer\n\n"
                "Final Answer: The answer."
            )

    def test_rejects_multiple_actions(self) -> None:
        with self.assertRaisesRegex(ReactParseError, "只能包含一个 Action"):
            parse_react_output(
                "Thought: Search twice.\n"
                "Action: search_documents\n"
                'Action Input: {"query":"Azure zones"}\n'
                "Action: search_documents\n"
                'Action Input: {"query":"Azure disks"}'
            )


if __name__ == "__main__":
    unittest.main()
