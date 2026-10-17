"""Offline Track B integration: python3 -m server.demo (zero API calls)."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from server.analysis import configure_extractor
from server.graphs import GraphService
from server.graphs.layout import reorganize
from server.jobs.fixtures import MemoryRepository
from server.jobs.handlers import AnalysisHandler, CaptureHandler
from server.models.config import build_models
from server.models.fixtures import load_fixture
from server.retrieval import JournalEntry, answer_question


def demo(output):
    models = build_models("fixture")  # Deliberately cannot spend quota.
    fixture = load_fixture()
    owner = fixture["user_id"]
    snapshot = {"entries": [{k: v for k, v in e.items() if k != "extraction"} for e in fixture["entries"]],
                "topics": fixture["topics"], "mentions": [], "corpus_version": 0,
                "topic_version": 0, "layout_version": 1,
                "captures": [
                    {"id": "audio", "user_id": owner, "version": 1,
                     "data": fixture["capture"]["audio_token"].encode(), "mime_type": "audio/wav", "duration_ms": 5000},
                    {"id": "page", "user_id": owner, "version": 1,
                     "pages": [{"data": fixture["capture"]["page_token"].encode(), "mime_type": "image/png"}]},
                    {"id": "chat", "user_id": owner, "version": 1, "messages": [
                        {"id": "u1", "role": "user", "text": fixture["entries"][1]["text"]},
                        {"id": "a1", "role": "assistant", "text": "An assistant suggestion is not evidence."}]}]}
    repository = MemoryRepository(snapshot)
    capture_handler = CaptureHandler(repository, models.capture)
    for source, kind in (("audio", "audio"), ("page", "handwriting"), ("chat", "summary")):
        repository.grant(source, source+"-lease")
        capture_handler(user_id=owner, source_id=source, version=1, lease_token=source+"-lease", kind=kind)
    configure_extractor(models.extractor, embedder=models.embedder)
    handler = AnalysisHandler(repository, embedder=models.embedder)
    for entry in snapshot["entries"]:
        repository.grant(entry["id"], "analysis-lease")
        handler(user_id=owner, entry_id=entry["id"], revision=1, lease_token="analysis-lease")
    repository.snapshot = reorganize(repository.snapshot, user_id=owner, expected_layout_version=1)
    graph = GraphService(repository.snapshot, user_id=owner)
    all_time = graph.graph()
    comparison = graph.compare("2025-01-01", "2026-01-01", "2026-01-01", "2027-01-01")
    entries = [JournalEntry(owner, e["id"], e["revision"], e["entry_date"], e["text"],
                            tuple(graph.membership[e["id"]]), current_revision=e["revision"])
               for e in repository.snapshot["entries"]]
    rag = answer_question("How have my priorities changed?", entries, user_id=owner,
                          history_enabled=True, generator=models.answerer)
    # Exact three-entry LLD fixture for C, alongside the full five-entry demo.
    three = deepcopy(repository.snapshot)
    three["entries"] = three["entries"][:3]
    deleted = deepcopy(three)
    deleted["entries"][0]["deleted"] = True
    captures = [{"id": c["id"], "state": c["state"], "result": c["result"]}
                for c in repository.snapshot["captures"]]
    artifacts = {"graph.json": all_time, "graph_three_entries.json": GraphService(three, user_id=owner).graph(),
                 "graph_after_delete.json": GraphService(deleted, user_id=owner).graph(),
                 "journal_entries.json": repository.snapshot["entries"],
                 "comparison.json": comparison, "piano_evidence.json": graph.supporting_entries("piano"),
                 "piano_friends_evidence.json": graph.supporting_entries("piano", other_topic_id="friends"),
                 "piano_trend.json": graph.trend("piano", "2025-01-01", "2027-01-01"),
                 "capture_review.json": captures, "rag.json": rag,
                 "goal_events.json": repository.snapshot["goal_events"]}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in artifacts.items():
        (output/name).write_text(json.dumps(value, indent=2)+"\n")
    return {"mode": "fixture", "api_calls": 0, "analyzed_entries": all_time["analyzed_entries"],
            "nodes": {n["label"]: n["count"] for n in all_time["nodes"]},
            "artifacts": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="fixtures/generated")
    print(json.dumps(demo(parser.parse_args().output), indent=2))
