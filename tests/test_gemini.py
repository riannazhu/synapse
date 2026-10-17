import json
import unittest

from server.analysis import analyze_entry, configure_extractor
from server.models.gemini import GeminiExtractor, ProviderError


def response(data):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(data)}]}}]}


def extraction(quote="piano", occurrence=0):
    return {"topics": [{"label": "Piano", "kind": "topic", "evidence_spans": [
        {"quote": quote, "occurrence": occurrence}]}], "events": []}


class GeminiTests(unittest.TestCase):
    def test_event_dates_and_context(self):
        for source, value in [("explicit", "2026-10-01"),
                              ("relative", "2026-10-16"),
                              ("entry_date", "2026-10-17")]:
            data = {"topics": [], "events": [{
                "goal_label": "Piano", "type": "practice",
                "event_date": value, "date_source": source,
                "evidence_spans": [{"quote": "I practiced piano.", "occurrence": 0}]}]}
            def transport(url, key, payload):
                context = json.loads(payload["contents"][0]["parts"][0]["text"])
                self.assertEqual(context["entry_date"], "2026-10-17")
                return response(data)
            model = GeminiExtractor("test", transport=transport)
            result = model.extract("I practiced piano.", [], entry_date="2026-10-17")
            self.assertEqual(result["events"][0]["event_date"], value)

    def test_invalid_event_date_gets_one_repair(self):
        data = {"topics": [], "events": [{"goal_label": "Piano", "type": "practice",
            "event_date": "2026-02-30", "date_source": "relative",
            "evidence_spans": [{"quote": "piano", "occurrence": 0}]}]}
        replies = [response(data), response({"topics": [], "events": []})]
        model = GeminiExtractor("test", transport=lambda *args: replies.pop(0))
        self.assertEqual(model.extract("piano", [], entry_date="2026-10-17")["events"], [])
        self.assertEqual(replies, [])

    def test_pipeline_and_unicode_offsets(self):
        def transport(url, key, payload):
            self.assertIn("responseJsonSchema", payload["generationConfig"])
            self.assertEqual(key, "test-key")
            return response(extraction(occurrence=1))
        configure_extractor(GeminiExtractor("test-key", transport=transport))
        text = "🎹 piano and piano"
        result = analyze_entry("fictional", text, [], entry_date="2026-10-17", revision=1)
        self.assertEqual(result["topics"][0]["evidence_spans"],
                         [{"start": 12, "end": 17, "quote": "piano"}])

    def test_invalid_quote_is_repaired_once(self):
        replies = [response(extraction("invented")), response(extraction())]
        calls = []
        def transport(*args):
            calls.append(1)
            return replies.pop(0)
        result = GeminiExtractor("test", transport=transport).extract("piano", [], entry_date="2026-10-17")
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["topics"][0]["evidence_spans"][0]["start"], 0)

    def test_invalid_output_fails_after_two_calls(self):
        calls = []
        def transport(*args):
            calls.append(1)
            return response(extraction("invented"))
        with self.assertRaisesRegex(ValueError, "one repair"):
            GeminiExtractor("test", transport=transport).extract("piano", [], entry_date="2026-10-17")
        self.assertEqual(len(calls), 2)

    def test_provider_failure_is_not_schema_retried(self):
        calls = []
        def transport(*args):
            calls.append(1)
            raise ProviderError("rate limited", retryable=True)
        with self.assertRaises(ProviderError) as caught:
            GeminiExtractor("test", transport=transport).extract("piano", [], entry_date="2026-10-17")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(len(calls), 1)

    def test_empty_extraction_is_valid(self):
        model = GeminiExtractor("test", transport=lambda *args: response({"topics": [], "events": []}))
        self.assertEqual(model.extract("Nothing to report.", [], entry_date="2026-10-17"), {"topics": [], "events": []})
