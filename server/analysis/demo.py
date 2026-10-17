"""Run a fictional saved entry: python3 -m server.analysis.demo"""
import json

from server.analysis import analyze_entry, configure_extractor
from server.models.gemini import GeminiExtractor


def main():
    configure_extractor(GeminiExtractor())
    result = analyze_entry(
        "fictional-entry-1", "I want to learn piano. Today I practiced piano for twenty minutes.",
        [{"id": "piano", "label": "Piano", "kind": "topic", "aliases": []}],
        entry_date="2026-10-17", revision=1,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
