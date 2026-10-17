"""Run a fictional saved entry: python3 -m server.analysis.demo"""
import json

from server.analysis import analyze_entry, configure_extractor
from server.models.config import build_models
from server.models.fixtures import load_fixture


def main():
    models = build_models()
    configure_extractor(models.extractor, embedder=models.embedder)
    entry = load_fixture()["entries"][0]
    result = analyze_entry(
        entry["id"], entry["text"], load_fixture()["topics"],
        entry_date=entry["entry_date"], revision=entry["revision"],
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
