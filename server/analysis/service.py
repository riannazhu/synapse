"""Pure analysis boundary. Track A supplies approved text and owner-scoped topics."""

from typing import Protocol
import re
from .dates import validate_date, event_date_fields
from .resolve_topics import resolve_topics


class Extractor(Protocol):
    def extract(self, text: str, passages: list[dict], *, entry_date: str) -> dict:
        """Return topics/events with absolute Unicode offsets and exact quotes."""
        ...


_extractor: Extractor | None = None
_embedder = None


def configure_extractor(extractor: Extractor, *, embedder=None) -> None:
    """Configure once at server startup; providers never receive user authority."""
    global _extractor, _embedder
    _extractor = extractor
    _embedder = embedder


def segment(text: str, target: int = 1200) -> list[dict]:
    """Split paragraphs, then long paragraphs, without changing source text."""
    result = []
    for paragraph in re.finditer(r"\S[^\n]*(?:\n(?!\s*\n)[^\n]*)*", text):
        start, stop = paragraph.span()
        while start < stop:
            end = min(start + target, stop)
            if end < stop:
                boundaries = list(re.finditer(r"[.!?]\s+|\s+", text[start:end]))
                if boundaries:
                    end = start + boundaries[-1].end()
            result.append({"start": start, "end": end, "text": text[start:end]})
            start = end
    return result


def _spans(value: object, text: str) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ValueError("Evidence spans must be a nonempty list")
    result = []
    for span in value:
        if not isinstance(span, dict):
            raise ValueError("Invalid evidence span")
        start, end, quote = (span.get(key) for key in ("start", "end", "quote"))
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text)
                or quote != text[start:end]):
            raise ValueError("Evidence must match exact approved text offsets")
        result.append({"start": start, "end": end, "quote": quote})
    return result


def analyze_entry(
    entry_id: str,
    text: str,
    existing_topics: list,
    *,
    entry_date: str,
    revision: int,
) -> dict:
    """Analyze approved text; return proposals without writing or confirming goals.

    existing_topics must already be restricted to the authenticated owner.
    Unmatched candidates are returned for registry reconciliation by Track A.
    """
    validate_date(entry_date)
    if type(revision) is not int or revision < 1:
        raise ValueError("revision must be a positive integer")
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise ValueError("entry_id must be a nonempty string")
    if not isinstance(text, str) or not text.strip() or len(text) > 50_000:
        raise ValueError("text must contain 1–50,000 approved characters")
    if not isinstance(existing_topics, list):
        raise ValueError("existing_topics must be a list")
    aliases: dict[tuple[str, str], set[str]] = {}
    for topic in existing_topics:
        if (not isinstance(topic, dict) or not isinstance(topic.get("id"), str)
                or not isinstance(topic.get("label"), str)
                or topic.get("kind") not in {"topic", "person"}):
            raise ValueError("Existing topics require id, label, and kind")
        if topic.get("merged_into"):
            continue
        names = topic.get("aliases", [])
        if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
            raise ValueError("Topic aliases must be strings")
        for name in [topic["label"], *names]:
            aliases.setdefault((topic["kind"], name.strip().casefold()), set()).add(topic["id"])
    if _extractor is None:
        raise RuntimeError("Configure a model extractor before analyzing entries")
    passages = segment(text)
    raw = _extractor.extract(text, passages, entry_date=entry_date)
    if not isinstance(raw, dict) or any(not isinstance(raw.get(k), list) for k in ("topics", "events")):
        raise ValueError("Extraction requires topics and events lists")
    topics = []
    for candidate in raw["topics"]:
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("label"), str)
                or not candidate["label"].strip() or candidate.get("kind") not in {"topic", "person"}):
            raise ValueError("Invalid topic candidate")
        label, kind = candidate["label"].strip(), candidate["kind"]
        matches = aliases.get((kind, label.casefold()), set())
        # A name alone cannot establish a person's identity.
        topic_id = next(iter(matches)) if kind == "topic" and len(matches) == 1 else None
        topics.append({"topic_id": topic_id, "label": label, "kind": kind,
                       "evidence_spans": _spans(candidate.get("evidence_spans"), text),
                       "resolution": "exact_alias" if topic_id else "candidate"})
    events = []
    for event in raw["events"]:
        if (not isinstance(event, dict) or event.get("type") not in {"intention", "practice", "milestone"}
                or not isinstance(event.get("goal_label"), str) or not event["goal_label"].strip()):
            raise ValueError("Invalid goal-event candidate")
        events.append({"type": event["type"], "goal_label": event["goal_label"],
                       **event_date_fields(event, entry_date),
                       "evidence_spans": _spans(event.get("evidence_spans"), text),
                       "review_status": "pending"})
    resolver = _extractor if callable(getattr(_extractor, "match_topics", None)) else None
    if resolver is not None and _embedder is not None:
        from server.models.embeddings import RankedResolver
        resolver = RankedResolver(resolver, _embedder)
    topics = resolve_topics(topics, existing_topics, text=text, resolver=resolver)
    for event in events:
        linked = {topic["topic_id"] for topic in topics if topic["topic_id"] is not None
                  and topic["kind"] == "topic" and any(
                      max(a["start"], b["start"]) < min(a["end"], b["end"])
                      for a in topic["evidence_spans"] for b in event["evidence_spans"])}
        event["topic_id"] = next(iter(linked)) if len(linked) == 1 else None
    return {"entry_id": entry_id, "entry_date": entry_date, "revision": revision,
            "pipeline_version": "analysis-v4",
            "passages": passages, "topics": topics, "goal_events": events}
