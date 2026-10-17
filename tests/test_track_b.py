from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from server.analysis import analyze_entry, configure_extractor
from server.analysis.corrections import merge_topics, split_topic
from server.demo import demo
from server.graphs import GraphService
from server.graphs.layout import generate_positions
from server.jobs.fixtures import MemoryRepository
from server.jobs.handlers import AnalysisHandler, CaptureHandler
from server.models.config import build_models
from server.models.embeddings import Vector, similarity, RankedResolver
from server.models.fixtures import load_fixture


def repository():
    fixture = load_fixture()
    return MemoryRepository({"topics": fixture["topics"],
        "entries": [{k: v for k, v in e.items() if k != "extraction"} for e in fixture["entries"]],
        "mentions": [], "topic_version": 0, "layout_version": 1, "corpus_version": 0})


def analyze_all(repo):
    models = build_models("fixture")
    configure_extractor(models.extractor, embedder=models.embedder)
    handler = AnalysisHandler(repo, embedder=models.embedder)
    for entry in list(repo.snapshot["entries"]):
        repo.grant(entry["id"], "lease")
        handler(user_id="fictional-user", entry_id=entry["id"], revision=1, lease_token="lease")
    return repo


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = analyze_all(repository()).snapshot

    def graph(self, snapshot=None):
        return GraphService(snapshot or self.snapshot, user_id="fictional-user")

    def test_three_entry_fixture_and_duplicate_spans(self):
        self.snapshot["entries"] = self.snapshot["entries"][:3]
        self.snapshot["mentions"].append(deepcopy(self.snapshot["mentions"][0]))
        result = self.graph().graph()
        self.assertEqual({n["id"]: n["count"] for n in result["nodes"]}, {"piano": 2, "friends": 2, "home": 1})
        edges = {(e["source"], e["target"]): e["shared_entry_count"] for e in result["edges"]}
        self.assertEqual(edges, {("friends", "piano"): 1, ("friends", "home"): 1})

    def test_deletion_stale_and_invalid_quotes_removed(self):
        self.snapshot["entries"] = self.snapshot["entries"][:3]
        self.snapshot["entries"][0]["deleted"] = True
        graph = self.graph()
        self.assertEqual({n["id"]: n["count"] for n in graph.graph()["nodes"]}, {"piano": 1, "friends": 1, "home": 1})
        self.snapshot["entries"][1]["revision"] = 2
        self.snapshot["mentions"][-1]["quote"] = "fabricated"
        self.assertEqual(self.graph().graph()["nodes"][0]["count"], 1)

    def test_compare_preserves_positions_and_scale_and_empty_share(self):
        graph = self.graph()
        comparison = graph.compare("2025-01-01", "2026-01-01", "2026-01-01", "2027-01-01")
        for a, b in zip(comparison["period_a"]["nodes"], comparison["period_b"]["nodes"]):
            self.assertEqual((a["id"], a["x"], a["y"]), (b["id"], b["x"], b["y"]))
        self.assertEqual(comparison["period_a"]["scale"], comparison["period_b"]["scale"])
        empty = graph.graph("2030-01-01", "2031-01-01")
        self.assertTrue(all(n["share"] is None and n["brightness"] == 0 for n in empty["nodes"]))
        self.assertEqual(empty["scale"], graph.graph()["scale"])

    def test_edge_evidence_and_pending_denominator(self):
        graph = self.graph()
        self.assertEqual([e["entry_id"] for e in graph.supporting_entries("piano", other_topic_id="friends")], ["E1", "E4"])
        self.snapshot["entries"][4]["analysis_status"] = "failed"
        result = self.graph().graph()
        self.assertEqual(result["analyzed_entries"], 4)
        self.assertEqual(result["failed_entries"], 1)
        self.assertEqual(result["total_entries"], 5)

    def test_foreign_mentions_hidden_topics_and_trend(self):
        self.snapshot["mentions"][0]["user_id"] = "other"
        self.snapshot["topics"][1]["hidden"] = True
        graph = self.graph()
        self.assertNotIn("friends", [n["id"] for n in graph.graph()["nodes"]])
        trend = graph.trend("piano", "2025-01-01", "2025-04-01")
        self.assertEqual([m["count"] for m in trend], [0, 1, 0])

    def test_layout_additions_keep_old_coordinates(self):
        old = {"piano": {"x": .2, "y": .3}}
        new = generate_positions(["piano", "friends"], {("friends", "piano"): 2}, old)
        self.assertEqual(new["piano"], old["piano"])
        self.assertEqual(new, generate_positions(["friends", "piano"], {("friends", "piano"): 2}, old))


class WorkerCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.repo = repository()
        self.models = build_models("fixture")
        configure_extractor(self.models.extractor)

    def result(self):
        e = self.repo.snapshot["entries"][0]
        return analyze_entry(e["id"], e["text"], self.repo.snapshot["topics"], entry_date=e["entry_date"], revision=1)

    def publish(self, result, token="lease"):
        return self.repo.publish_analysis(user_id="fictional-user", entry_id="E1", revision=1, lease_token=token, result=result)

    def test_old_lease_and_stale_revision_cannot_publish(self):
        result = self.result()
        self.repo.grant("E1", "new")
        self.assertFalse(self.publish(result, "old"))
        self.repo.snapshot["entries"][0]["revision"] = 2
        self.assertFalse(self.publish(result, "new"))
        self.assertEqual(self.repo.snapshot["mentions"], [])

    def test_expired_and_deleted_jobs_cancel(self):
        result = self.result()
        self.repo.grant("E1", "lease", seconds=-1)
        self.assertFalse(self.publish(result))
        self.repo.grant("E1", "lease")
        self.repo.snapshot["entries"][0]["deleted"] = True
        self.assertFalse(self.publish(result))

    def test_retry_does_not_duplicate_rows_or_versions(self):
        result = self.result()
        self.repo.grant("E1", "lease")
        self.assertTrue(self.publish(result))
        before = deepcopy(self.repo.snapshot)
        self.repo.grant("E1", "retry")
        self.assertTrue(self.publish(result, "retry"))
        self.assertEqual(self.repo.snapshot, before)
        self.assertEqual(self.repo.snapshot["goal_events"][0]["review_status"], "pending")
        self.assertEqual(self.repo.snapshot["goal_events"][0]["topic_id"], "piano")

    def test_merge_keeps_target_positions_and_counts(self):
        snapshot = analyze_all(self.repo).snapshot
        target = next(t for t in snapshot["topics"] if t["id"] == "piano")
        merged = merge_topics(snapshot, user_id="fictional-user", source_ids=["friends"], target_id="piano", expected_topic_version=0)
        node = next(n for n in GraphService(merged, user_id="fictional-user").graph()["nodes"] if n["id"] == "piano")
        self.assertEqual(node["count"], 5)
        self.assertEqual(node["x"], target["x"])
        self.assertTrue(merged["derived_stale"])

    def test_split_only_explicit_mentions_and_survives_reanalysis(self):
        snapshot = analyze_all(self.repo).snapshot
        mention = next(m for m in snapshot["mentions"] if m["topic_id"] == "piano" and m["entry_id"] == "E1")
        snapshot = split_topic(snapshot, user_id="fictional-user", source_id="piano",
            new_topic={"id": "lesson", "user_id": "fictional-user", "label": "Lessons", "kind": "topic", "x": .1, "y": .1},
            mention_ids=[mention["id"]], expected_topic_version=0)
        self.assertEqual(next(m for m in snapshot["mentions"] if m["id"] == mention["id"])["topic_id"], "lesson")
        self.repo.snapshot = snapshot
        self.repo.snapshot["entries"][0]["analysis_status"] = "queued"
        self.repo.grant("E1", "lease")
        self.assertTrue(self.publish(self.result()))
        self.assertTrue(any(m["topic_id"] == "lesson" and m["entry_id"] == "E1" for m in self.repo.snapshot["mentions"]))

    def test_outdated_override_flagged(self):
        self.repo.snapshot["overrides"] = [{"user_id": "fictional-user", "entry_id": "E1", "topic_id": "piano",
                                            "action": "exclude", "source_revision": 0}]
        self.repo.grant("E1", "lease")
        self.assertTrue(self.publish(self.result()))
        self.assertTrue(self.repo.snapshot["overrides"][0]["review_needed"])

    def test_capture_deleted_during_generation_cannot_publish(self):
        self.repo.snapshot["captures"] = [{"id": "audio", "user_id": "fictional-user", "version": 1,
            "data": self.models.capture.fixture["capture"]["audio_token"].encode(), "mime_type": "audio/wav", "duration_ms": 1000}]
        self.repo.grant("audio", "lease")
        model = self.models.capture
        original = model.transcribe
        def transcribe(*args, **kwargs):
            result = original(*args, **kwargs)
            self.repo.snapshot["captures"][0]["deleted"] = True
            return result
        model.transcribe = transcribe
        result = CaptureHandler(self.repo, model)(user_id="fictional-user", source_id="audio", version=1, lease_token="lease", kind="audio")
        self.assertEqual(result["status"], "cancelled")


class OfflineTests(unittest.TestCase):
    def test_full_demo_never_opens_network(self):
        with tempfile.TemporaryDirectory() as output, patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), patch("server.models.gemini.urlopen", side_effect=AssertionError("network forbidden")):
            result = demo(output)
            self.assertEqual(result["api_calls"], 0)
            self.assertEqual(result["nodes"], {"Piano": 4, "Friends": 3, "Home": 1})
            capture = json.loads((Path(output)/"capture_review.json").read_text())
            self.assertTrue(all(c["state"] == "needs_review" for c in capture))

    def test_fixture_unknown_input_fails_without_live_fallback(self):
        with self.assertRaises(ValueError):
            build_models("fixture").extractor.extract("Real journal", [], entry_date="2026-10-17")

    def test_versioned_vectors_reject_mixed_models(self):
        with self.assertRaises(ValueError):
            similarity(Vector("v1", (1., 0.)), Vector("v2", (1., 0.)))

    def test_top_five_candidates_only_and_cache_reuse(self):
        class Embedder:
            model = "test-v1"
            def __init__(self): self.calls = 0
            def embed(self, *args, **kwargs):
                self.calls += 1
                return [1., 0.]
        class Matcher:
            def match_topics(self, text, candidates, registry):
                assert len(registry) == 5
                return {"matches": [{"candidate_id": "0", "topic_id": None}]}
        embedder = Embedder()
        resolver = RankedResolver(Matcher(), embedder)
        candidate = [{"candidate_id": "0", "label": "Piano", "evidence_spans": [{"quote": "piano"}]}]
        topics = [{"id": str(i), "label": str(i), "kind": "topic"} for i in range(8)]
        resolver.match_topics("piano", candidate, topics)
        resolver.match_topics("piano", candidate, topics)
        self.assertEqual(embedder.calls, 9)
