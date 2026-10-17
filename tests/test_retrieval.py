import unittest

from server.retrieval import JournalEntry, answer_question
from server.models.rag import GeminiAnswerer, GeminiEmbedder


def entry(id, date="2026-01-01", **kwargs):
    return JournalEntry("owner", id, 1, date, "Piano practice.", **kwargs)


class Answerer:
    def answer(self, question, evidence):
        return {"claims": [{"text": "A tentative reflection.",
                            "evidence_ids": [evidence[0]["id"]]}]}


class RetrievalTests(unittest.TestCase):
    def ask(self, entries, **kwargs):
        return answer_question("How have my priorities changed?", entries,
                               user_id="owner", history_enabled=True,
                               generator=Answerer(), **kwargs)

    def test_broad_covers_early_and_late_periods(self):
        rows = [entry("early", "2025-01-01"), entry("middle", "2025-06-01"),
                entry("late", "2026-01-01")]
        result = self.ask(rows, limit=2)
        self.assertEqual([e["entry_id"] for e in result["evidence"]], ["early", "late"])

    def test_scope_and_revision_and_deletion(self):
        rows = [entry("valid"), entry("deleted", deleted=True),
                entry("draft", approved=False), entry("stale", current_revision=2),
                JournalEntry("other", "foreign", 1, "2026-01-01", "Private")]
        self.assertEqual([e["entry_id"] for e in self.ask(rows)["evidence"]], ["valid"])

    def test_history_opt_in(self):
        result = answer_question("Question", [entry("e")], user_id="owner")
        self.assertEqual(result["status"], "history_disabled")

    def test_half_open_topic_date_filters(self):
        rows = [entry("a", "2026-01-01", topic_ids=("piano",)),
                entry("b", "2026-02-01", topic_ids=("piano",)), entry("c")]
        result = self.ask(rows, strategy="filtered", topic_ids=("piano",),
                          from_date="2026-01-01", to_date="2026-02-01")
        self.assertEqual([e["entry_id"] for e in result["evidence"]], ["a"])

    def test_counts_deduplicate_and_use_analyzed_denominator(self):
        result = self.ask([entry("a", topic_ids=("piano", "piano")), entry("b"),
                           entry("pending", analyzed=False)], strategy="counts")
        self.assertEqual(result["topics"][0]["count"], 1)
        self.assertEqual(result["topics"][0]["share"], .5)
        self.assertEqual(result["total_entries"], 3)

    def test_semantic_ranking(self):
        class Embedder:
            def embed(self, text, *, task):
                return [1, 0] if task == "query" or "Piano" in text else [0, 1]
        rows = [JournalEntry("owner", "home", 1, "2026-01-01", "Home."), entry("music")]
        result = self.ask(rows, strategy="semantic", embedder=Embedder(), limit=1)
        self.assertEqual(result["evidence"][0]["entry_id"], "music")

    def test_unknown_citation_rejected(self):
        class BadAnswerer:
            def answer(self, *args):
                return {"claims": [{"text": "Invented", "evidence_ids": ["unknown"]}]}
        with self.assertRaises(ValueError):
            answer_question("Question", [entry("a")], user_id="owner",
                            history_enabled=True, generator=BadAnswerer())

    def test_empty_evidence_abstains_without_model(self):
        self.assertEqual(self.ask([])["status"], "insufficient_evidence")

    def test_gemini_provider_payloads(self):
        def embedding_transport(url, key, payload):
            self.assertEqual(payload["taskType"], "RETRIEVAL_QUERY")
            return {"embedding": {"values": [1., 0.]}}
        self.assertEqual(GeminiEmbedder("test", transport=embedding_transport).embed(
            "Question", task="query"), [1., 0.])
        def answer_transport(url, key, payload):
            self.assertIn("responseJsonSchema", payload["generationConfig"])
            return {"candidates": [{"content": {"parts": [{"text": '{"claims": []}'}]}}]}
        self.assertEqual(GeminiAnswerer("test", transport=answer_transport).answer(
            "Question", []), {"claims": []})
