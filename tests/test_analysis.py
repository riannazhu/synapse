import json
from pathlib import Path
import unittest

from server.analysis import analyze_entry, configure_extractor
from server.analysis.service import segment


class FixtureExtractor:
    def __init__(self, output):
        self.output = output

    def extract(self, text, passages):
        return self.output


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parents[1] / "fixtures/typed_entry.json").read_text())
        configure_extractor(FixtureExtractor(self.fixture["extraction"]))

    def analyze(self):
        f = self.fixture
        return analyze_entry(f["entry_id"], f["text"], f["existing_topics"])

    def test_intention_is_pending_and_alias_reused(self):
        result = self.analyze()
        self.assertEqual(result["topics"][0]["topic_id"], "piano")
        self.assertEqual(result["goal_events"][0]["type"], "intention")
        self.assertEqual(result["goal_events"][0]["review_status"], "pending")

    def test_fabricated_quote_rejected(self):
        self.fixture["extraction"]["topics"][0]["evidence_spans"][0]["quote"] = "guitar"
        with self.assertRaises(ValueError):
            self.analyze()

    def test_person_name_does_not_resolve_identity(self):
        self.fixture["existing_topics"][0]["kind"] = "person"
        self.fixture["extraction"]["topics"][0]["kind"] = "person"
        self.assertIsNone(self.analyze()["topics"][0]["topic_id"])

    def test_unicode_and_long_paragraph_offsets(self):
        text = "🎹 Practice. " * 300 + "\n\nNext paragraph."
        passages = segment(text)
        self.assertTrue(all(p["text"] == text[p["start"]:p["end"]] for p in passages))
        self.assertTrue(all(len(p["text"]) <= 1200 for p in passages))
        self.assertEqual("".join(p["text"] for p in passages), text.replace("\n\n", ""))


if __name__ == "__main__":
    unittest.main()
