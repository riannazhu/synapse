"""Versioned embeddings with exact ranking; no approximate vector index."""
from dataclasses import dataclass
from math import isfinite
from server.retrieval.service import _cosine


@dataclass(frozen=True)
class Vector:
    model_version: str
    values: tuple[float, ...]

    def __post_init__(self):
        if not self.model_version or not self.values or not all(isfinite(v) for v in self.values):
            raise ValueError("Invalid versioned embedding")


def similarity(a: Vector, b: Vector):
    if a.model_version != b.model_version or len(a.values) != len(b.values):
        raise ValueError("Embedding model/version/dimension mismatch")
    return _cosine(a.values, b.values)


def embed_text(model, text, *, task="document"):
    return Vector(model.model, tuple(model.embed(text, task=task)))


class RankedResolver:
    """Bound a small registry to the union of each candidate's five neighbors."""
    def __init__(self, matcher, embedder):
        self.matcher, self.embedder = matcher, embedder
        self.cache = {}

    def _embed(self, text, *, task="document"):
        key = (text, task)
        if key not in self.cache:
            self.cache[key] = embed_text(self.embedder, text, task=task)
        return self.cache[key]

    def match_topics(self, text, candidates, existing_topics):
        vectors = {t["id"]: self._embed(t["label"] + " " + " ".join(t.get("aliases", [])))
                   for t in existing_topics}
        matches = []
        for candidate in candidates:
            vector = self._embed(candidate["label"] + " " + " ".join(
                span["quote"] for span in candidate["evidence_spans"]), task="query")
            neighbors = sorted(existing_topics, key=lambda t: (-similarity(vector, vectors[t["id"]]), t["id"]))[:5]
            result = self.matcher.match_topics(text, [candidate], neighbors)
            if not isinstance(result, dict) or not isinstance(result.get("matches"), list):
                raise ValueError("Invalid grounded matching response")
            allowed = {t["id"] for t in neighbors}
            for match in result.get("matches", []):
                if not isinstance(match, dict):
                    raise ValueError("Invalid grounded matching decision")
                if match.get("topic_id") is not None and match["topic_id"] not in allowed:
                    raise ValueError("Matcher selected a topic outside retrieved neighbors")
            matches.extend(result["matches"])
        return {"matches": matches}
