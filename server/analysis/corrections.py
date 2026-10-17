"""Pure topic correction transforms; Track A commits under its registry lock."""
from copy import deepcopy


def _registry(snapshot, user_id):
    return {t["id"]: t for t in snapshot["topics"] if t["user_id"] == user_id}


def _invalidate(snapshot):
    snapshot["topic_version"] = snapshot.get("topic_version", 0) + 1
    snapshot["corpus_version"] = snapshot.get("corpus_version", 0) + 1
    snapshot["derived_stale"] = True


def merge_topics(snapshot, *, user_id, source_ids, target_id, expected_topic_version):
    result = deepcopy(snapshot)
    topics = _registry(result, user_id)
    if result.get("topic_version", 0) != expected_topic_version:
        raise ValueError("Topic version conflict")
    sources = set(source_ids)
    if not sources or target_id in sources or any(key not in topics for key in sources | {target_id}):
        raise ValueError("Invalid topic merge")
    target = topics[target_id]
    if target.get("merged_into") or any(topics[k].get("merged_into") or topics[k]["kind"] != target["kind"] for k in sources):
        raise ValueError("Merge requires active topics of the same kind")
    aliases = set(target.get("aliases", []))
    for key in sources:
        source = topics[key]
        aliases.update([source["label"], *source.get("aliases", [])])
        source["merged_into"] = target_id
    target["aliases"] = sorted(aliases)
    for table in ("mentions", "overrides", "goal_events", "goals", "suppressions"):
        for row in result.get(table, []):
            if row.get("user_id") == user_id and row.get("topic_id") in sources:
                row["topic_id"] = target_id
    for row in result.get("mention_overrides", []):
        if row["user_id"] == user_id:
            for key in ("source_topic_id", "target_topic_id"):
                if row.get(key) in sources:
                    row[key] = target_id
    # Redirects from older merges must follow the newest canonical identity.
    for topic in topics.values():
        if topic.get("merged_into") in sources:
            topic["merged_into"] = target_id
    _invalidate(result)
    return result


def split_topic(snapshot, *, user_id, source_id, new_topic, mention_ids, expected_topic_version):
    result = deepcopy(snapshot)
    topics = _registry(result, user_id)
    if result.get("topic_version", 0) != expected_topic_version:
        raise ValueError("Topic version conflict")
    source = topics.get(source_id)
    if (not source or source.get("merged_into") or new_topic.get("user_id") != user_id
            or not new_topic.get("id") or any(t["id"] == new_topic["id"] for t in result["topics"])
            or not new_topic.get("label", "").strip() or new_topic.get("kind") != source["kind"]):
        raise ValueError("Invalid split target")
    selected = set(mention_ids)
    rows = {m["id"]: m for m in result.get("mentions", [])
            if m["user_id"] == user_id and m["topic_id"] == source_id}
    if not selected or not selected <= rows.keys():
        raise ValueError("Split requires explicit owned mention IDs")
    for key in selected:
        mention = rows[key]
        result.setdefault("mention_overrides", []).append({
            "user_id": user_id, "entry_id": mention["entry_id"], "source_revision": mention["revision"],
            "source_topic_id": source_id, "target_topic_id": new_topic["id"],
            "start": mention["start"], "end": mention["end"], "quote": mention["quote"],
            "review_needed": False})
        rows[key]["topic_id"] = new_topic["id"]
        rows[key]["assignment_source"] = "user"
    result["topics"].append(deepcopy(new_topic))
    _invalidate(result)
    return result


def apply_overrides(assignments, overrides, *, revision):
    result = deepcopy(assignments)
    reviews = []
    for override in overrides:
        if override["source_revision"] != revision or override.get("review_needed"):
            reviews.append({**override, "review_needed": True})
            continue
        if override["action"] == "exclude":
            result = [a for a in result if a["topic_id"] != override["topic_id"]]
        elif override["action"] == "include":
            # Includes need current exact evidence; no unsupported synthetic spans.
            spans = override.get("evidence_spans")
            if not spans:
                raise ValueError("Include override requires current evidence spans")
            result.append({"topic_id": override["topic_id"], "label": override["label"],
                           "kind": override["kind"], "evidence_spans": spans,
                           "resolution": "user"})
        else:
            raise ValueError("Invalid override action")
    return result, reviews
