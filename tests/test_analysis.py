import json
from pathlib import Path
import unittest

from server.analysis import analyze_entry, configure_extractor
from server.analysis.service import segment


class FixtureExtractor:
    def __init__(self, output):
        self.output = output

    def extract(self, text, passages, *, entry_date):
        return self.output


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parents[1] / "fixtures/typed_entry.json").read_text())
        configure_extractor(FixtureExtractor(self.fixture["extraction"]))

    def analyze(self):
        f = self.fixture
        return analyze_entry(f["entry_id"], f["text"], f["existing_topics"], entry_date=f["entry_date"], revision=f["revision"])

    def test_intention_is_pending_and_alias_reused(self):
        result = self.analyze()
        self.assertEqual(result["topics"][0]["topic_id"], "piano")
        self.assertEqual(result["goal_events"][0]["type"], "intention")
        self.assertEqual(result["goal_events"][0]["review_status"], "pending")

    def test_fabricated_quote_rejected(self):
        self.fixture["extraction"]["topics"][0]["evidence_spans"][0]["quote"] = "guitar"
        with self.assertRaises(ValueError):
            self.analyze()

    def test_revision_and_date_are_preserved(self):
        result = self.analyze()
        self.assertEqual(result["revision"], 1)
        self.assertEqual(result["entry_date"], "2026-10-17")
        self.assertEqual(result["goal_events"][0]["event_date"], "2026-10-17")

    def test_invalid_calendar_dates_and_revisions(self):
        for value in ["2026-02-30", "20261017", "2026-1-01", None]:
            with self.subTest(date=value), self.assertRaises(ValueError):
                analyze_entry("e", "text", [], entry_date=value, revision=1)
        for value in [0, -1, True, "1"]:
            with self.subTest(revision=value), self.assertRaises(ValueError):
                analyze_entry("e", "text", [], entry_date="2026-10-17", revision=value)

    def test_incorrect_fallback_date_is_rejected(self):
        self.fixture["extraction"]["events"][0]["event_date"] = "2026-10-16"
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
