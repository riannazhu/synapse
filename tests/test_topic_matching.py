import unittest
from server.analysis import analyze_entry, configure_extractor
from server.analysis.resolve_topics import resolve_topics
from server.models.gemini import GeminiExtractor


REGISTRY = [{"id": "piano", "label": "Piano", "kind": "topic"}]


def candidate(label="Piano practice", kind="topic"):
    return {"topic_id": None, "label": label, "kind": kind,
            "evidence_spans": [{"start": 0, "end": 5, "quote": "piano"}],
            "resolution": "candidate"}


class Matcher:
    def __init__(self, targets):
        self.targets = iter(targets)
        self.calls = 0

    def match_topics(self, text, candidates, registry):
        self.calls += 1
        target = next(self.targets)
        return {"matches": [{"candidate_id": c["candidate_id"], "topic_id": target} for c in candidates]}


class TopicMatchingTests(unittest.TestCase):
    def test_paraphrase_requires_two_agreeing_decisions(self):
        matcher = Matcher(["piano", "piano"])
        result = resolve_topics([candidate()], REGISTRY, text="piano", resolver=matcher)
        self.assertEqual(result[0]["topic_id"], "piano")
        self.assertEqual(result[0]["label"], "Piano")
        self.assertEqual(result[0]["resolution"], "semantic_confirmed")
        self.assertEqual(matcher.calls, 2)

    def test_disagreement_and_new_topic_remain_candidates(self):
        for targets in [["piano", None], [None, None]]:
            result = resolve_topics([candidate()], REGISTRY, text="piano", resolver=Matcher(targets))
            self.assertIsNone(result[0]["topic_id"])

    def test_person_is_never_semantically_merged(self):
        matcher = Matcher([])
        result = resolve_topics([candidate("Alex", "person")], REGISTRY, text="Alex", resolver=matcher)
        self.assertIsNone(result[0]["topic_id"])
        self.assertEqual(matcher.calls, 0)

    def test_unknown_or_merged_id_rejected(self):
        for registry in [REGISTRY, REGISTRY + [{"id": "old", "label": "Old", "kind": "topic", "merged_into": "piano"}]]:
            with self.assertRaises(ValueError):
                resolve_topics([candidate()], registry, text="piano", resolver=Matcher(["old"]))

    def test_resolved_candidates_are_combined(self):
        result = resolve_topics([candidate(), candidate("Playing piano")], REGISTRY,
                                text="piano", resolver=Matcher(["piano", "piano"]))
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["evidence_spans"]), 1)

    def test_pipeline_uses_matcher_after_validating_extraction(self):
        class Extractor(Matcher):
            def extract(self, text, passages, *, entry_date):
                return {"topics": [{"label": "Playing piano", "kind": "topic",
                                    "evidence_spans": candidate()["evidence_spans"]}], "events": []}
        configure_extractor(Extractor(["piano", "piano"]))
        result = analyze_entry("e", "piano", REGISTRY, entry_date="2026-10-17", revision=1)
        self.assertEqual(result["topics"][0]["topic_id"], "piano")

    def test_gemini_matching_payload(self):
        def transport(url, key, payload):
            self.assertIn("responseJsonSchema", payload["generationConfig"])
            return {"candidates": [{"content": {"parts": [{"text":
                '{"matches":[{"candidate_id":"0","topic_id":"piano"}]}'}]}}]}
        matcher = GeminiExtractor("test", transport=transport)
        result = matcher.match_topics("piano", [{"candidate_id": "0"}], REGISTRY)
        self.assertEqual(result["matches"][0]["topic_id"], "piano")
