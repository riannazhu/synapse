"""Fictional RAG example: python3 -m server.retrieval.demo."""
import json
from server.retrieval import JournalEntry, answer_question
from server.models.config import build_models


if __name__ == "__main__":
    entries = [
        JournalEntry("fictional-user", "early", 1, "2025-01-10",
                     "I want to focus on getting promoted this year.", ("career",)),
        JournalEntry("fictional-user", "later", 1, "2026-09-10",
                     "I am making more time for friends and piano, even when work is busy.",
                     ("friends", "piano", "career")),
    ]
    print(json.dumps(answer_question(
        "How have my priorities changed?", entries, user_id="fictional-user",
        history_enabled=True, strategy="broad", generator=build_models().answerer,
    ), indent=2))
