"""Owner-scoped prototype RAG over approved, current journal revisions."""
from collections import defaultdict
from dataclasses import dataclass
from math import isfinite, sqrt

from server.analysis.dates import validate_date
from server.analysis.service import segment


@dataclass(frozen=True)
class JournalEntry:
    user_id: str
    entry_id: str
    revision: int
    entry_date: str
    text: str
    topic_ids: tuple[str, ...] = ()
    current_revision: int = 1
    approved: bool = True
    deleted: bool = False
    analyzed: bool = True


def _cosine(a, b):
    if not a or len(a) != len(b) or any(not isfinite(x) for x in [*a, *b]):
        raise ValueError("Incompatible or invalid embedding vectors")
    norm = sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / norm if norm else 0.0


def answer_question(
    question: str, entries: list[JournalEntry], *, user_id: str,
    history_enabled: bool = False, strategy: str = "broad",
    topic_ids: tuple[str, ...] = (), from_date: str | None = None,
    to_date: str | None = None, limit: int = 12,
    embedder=None, generator=None,
) -> dict:
    """Track A supplies an authorized snapshot. Strategy is explicit, not guessed.

    broad: round-robin evidence across calendar quarters, then across entries.
    semantic: exact cosine ranking using the supplied embedding adapter.
    filtered: explicit canonical topic IDs and/or half-open date range.
    counts: distinct analyzed entry membership, without generation.
    """
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise ValueError("Question must contain 1–4,000 characters")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Authenticated user_id is required")
    if strategy not in {"broad", "semantic", "filtered", "counts"}:
        raise ValueError("Unknown retrieval strategy")
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("limit must be between 1 and 30")
    for value in (from_date, to_date):
        if value is not None:
            validate_date(value)
    if from_date and to_date and from_date >= to_date:
        raise ValueError("Date range must be nonempty [from_date, to_date)")
    if strategy == "filtered" and not (topic_ids or from_date or to_date):
        raise ValueError("Filtered retrieval needs explicit topic/date filters")
    if not history_enabled:
        return {"status": "history_disabled", "strategy": strategy, "claims": [], "evidence": []}

    scoped = {}
    for entry in entries:
        if (entry.user_id != user_id or not entry.approved or entry.deleted
                or entry.revision != entry.current_revision):
            continue
        validate_date(entry.entry_date)
        if (from_date and entry.entry_date < from_date) or (to_date and entry.entry_date >= to_date):
            continue
        if topic_ids and not set(topic_ids).intersection(entry.topic_ids):
            continue
        if entry.entry_id in scoped and scoped[entry.entry_id] != entry:
            raise ValueError("Conflicting current entry records")
        scoped[entry.entry_id] = entry
    selected_entries = sorted(scoped.values(), key=lambda e: (e.entry_date, e.entry_id))
    if strategy == "counts":
        membership = defaultdict(set)
        analyzed = [e for e in selected_entries if e.analyzed]
        for entry in analyzed:
            for topic in set(entry.topic_ids):
                membership[topic].add(entry.entry_id)
        return {"status": "ok", "strategy": strategy,
                "total_entries": len(selected_entries), "analyzed_entries": len(analyzed),
                "topics": [{"topic_id": topic, "count": len(ids),
                            "share": len(ids)/len(analyzed), "entry_ids": sorted(ids)}
                           for topic, ids in sorted(membership.items(), key=lambda p: (-len(p[1]), p[0]))]}

    # Alternate passages across entries before selecting a second passage from
    # any entry. This prevents one long entry dominating broad reflection.
    chunks = []
    per_entry = [segment(e.text) for e in selected_entries]
    for index in range(max((len(p) for p in per_entry), default=0)):
        for entry, passages in zip(selected_entries, per_entry):
            if index < len(passages):
                p = passages[index]
                chunks.append({"entry_id": entry.entry_id, "revision": entry.revision,
                               "entry_date": entry.entry_date, "start": p["start"],
                               "end": p["end"], "quote": p["text"]})
    periods = sorted({c["entry_date"][:4] + "-Q" + str((int(c["entry_date"][5:7])-1)//3+1) for c in chunks})
    if strategy == "semantic" and chunks:
        if embedder is None:
            raise ValueError("Semantic retrieval requires an embedding adapter")
        query = embedder.embed(question, task="query")
        # Same adapter/model/dimension for the entire search; no mixed caches.
        chunks.sort(key=lambda c: -_cosine(query, embedder.embed(c["quote"], task="document")))
    elif strategy == "broad":
        buckets = defaultdict(list)
        for chunk in chunks:
            period = chunk["entry_date"][:4] + "-Q" + str((int(chunk["entry_date"][5:7])-1)//3+1)
            buckets[period].append(chunk)
        # Spread a small budget over the entire history, including endpoints.
        if len(periods) > limit:
            chosen = [periods[round(i*(len(periods)-1)/(limit-1))] for i in range(limit)] if limit > 1 else [periods[-1]]
        else:
            chosen = periods
        chunks = [buckets[p][i] for i in range(max((len(buckets[p]) for p in chosen), default=0))
                  for p in chosen if i < len(buckets[p])]
    evidence = [{"id": f"source-{i+1}", **c} for i, c in enumerate(chunks[:limit])]
    result = {"status": "ok" if evidence else "insufficient_evidence", "strategy": strategy,
              "claims": [], "evidence": evidence,
              "coverage": {"eligible_entries": len(selected_entries),
                           "retrieved_entries": len({e["entry_id"] for e in evidence}),
                           "available_quarters": periods,
                           "sampled": True}}
    if not evidence:
        return result
    if generator is None:
        raise ValueError("Answer generation requires a grounded generator")
    raw = generator.answer(question, evidence)
    if not isinstance(raw, dict) or set(raw) != {"claims"} or not isinstance(raw["claims"], list):
        raise ValueError("Invalid answer format")
    valid_ids = {e["id"] for e in evidence}
    for claim in raw["claims"]:
        if (not isinstance(claim, dict) or set(claim) != {"text", "evidence_ids"}
                or not isinstance(claim["text"], str) or not claim["text"].strip()
                or not isinstance(claim["evidence_ids"], list) or not claim["evidence_ids"]
                or any(not isinstance(ref, str) or ref not in valid_ids for ref in claim["evidence_ids"])):
            raise ValueError("Every answer claim must cite retrieved evidence")
    result["claims"] = raw["claims"]
    if not raw["claims"]:
        result["status"] = "insufficient_evidence"
    return result
