"""Hard-coded responses for named fictional inputs. Makes zero network calls."""
from copy import deepcopy
import json
from pathlib import Path

from .capture import _messages


def load_fixture():
    return json.loads((Path(__file__).resolve().parents[2] / "fixtures/demo_journal.json").read_text())


class FixtureModels:
    model = "fixture-v1-not-semantic"

    def __init__(self):
        self.fixture = load_fixture()
        self.evaluation = json.loads((Path(__file__).resolve().parents[2] / "fixtures/extraction_responses.json").read_text())

    def extract(self, text, passages, *, entry_date):
        for entry in self.fixture["entries"]:
            if entry["text"] == text and entry["entry_date"] == entry_date:
                return deepcopy(entry["extraction"])
        if entry_date == "2026-10-17" and text in self.evaluation:
            return deepcopy(self.evaluation[text])
        raise ValueError("Offline extractor supports only named fictional cases; choose live mode explicitly for other entries")

    def match_topics(self, text, candidates, existing_topics):
        allowed = {t["id"] for t in existing_topics}
        decisions = []
        for candidate in candidates:
            target = self.fixture["semantic_matches"].get(candidate["label"])
            decisions.append({"candidate_id": candidate["candidate_id"], "topic_id": target if target in allowed else None})
        return {"matches": decisions}

    def embed(self, text, *, task):
        # Deterministic toy vectors for exercising interfaces, not actual ML.
        vector = [float(text.casefold().count(word)) for word in self.fixture["embedding_vocabulary"]]
        return vector if any(vector) else [1., *([0.]*(len(vector)-1))]

    def transcribe(self, audio, *, mime_type, duration_ms):
        if audio != self.fixture["capture"]["audio_token"].encode():
            raise ValueError("Offline audio supports only the named mock token, not real media")
        text = self.fixture["capture"]["audio_text"]
        return {"text": text, "segments": [], "uncertain_spans": [],
                "provider_version": self.model, "state": "needs_review"}

    def extract_pages(self, pages):
        if len(pages) != 1 or pages[0]["data"] != self.fixture["capture"]["page_token"].encode():
            raise ValueError("Offline handwriting supports only the named mock page")
        return {"pages": [{"page": 1, "text": self.fixture["capture"]["page_text"], "uncertain_spans": []}],
                "provider_version": self.model, "state": "needs_review"}

    def reply(self, messages, *, history_enabled=False, evidence=None):
        _messages(messages)
        if evidence and not history_enabled:
            raise ValueError("Historical retrieval requires opt-in")
        return {"text": "What would you like to reflect on next?", "evidence_ids": [],
                "state": "draft", "provider_version": self.model}

    def summarize(self, messages):
        _messages(messages)
        users = [m for m in messages if m["role"] == "user"]
        if not users:
            raise ValueError("No user statements")
        refs, offset = [], 0
        for message in users:
            refs.append({"start": offset, "end": offset+len(message["text"]),
                         "message_id": message["id"], "quote": message["text"]})
            offset += len(message["text"])+1
        return {"draft_text": " ".join(m["text"] for m in users), "source_refs": refs,
                "state": "needs_review", "provider_version": self.model}

    def answer(self, question, evidence):
        # Fixture quotes exercise citation plumbing without invented synthesis.
        return {"claims": [{"text": "Fictional source: " + e["quote"], "evidence_ids": [e["id"]]}
                           for e in evidence[:2]]}
