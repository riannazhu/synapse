"""Canonical reconciliation without mutating Track A's registry."""


def resolve_topics(topics, registry, *, text, resolver=None):
    active = {t["id"]: t for t in registry if not t.get("merged_into")}
    if len(active) != len([t for t in registry if not t.get("merged_into")]):
        raise ValueError("Duplicate active topic IDs")
    unresolved = []
    for index, topic in enumerate(topics):
        if topic["topic_id"] is None and topic["kind"] == "topic":
            unresolved.append({"candidate_id": str(index), "label": topic["label"],
                               "kind": topic["kind"], "evidence_spans": topic["evidence_spans"]})
    # Person identity needs richer identity evidence; never merge names here.
    compatible = [{"id": t["id"], "label": t["label"], "kind": t["kind"],
                   "aliases": t.get("aliases", [])}
                  for t in active.values() if t["kind"] == "topic"]
    if unresolved and compatible and resolver is not None:
        first = _decisions(resolver.match_topics(text, unresolved, compatible), unresolved, active)
        # Independent grounded confirmation; no first-pass decision is supplied.
        second = _decisions(resolver.match_topics(text, unresolved, compatible), unresolved, active)
        for candidate in unresolved:
            key = candidate["candidate_id"]
            if first[key] is not None and first[key] == second[key]:
                topics[int(key)]["topic_id"] = first[key]
                topics[int(key)]["resolution"] = "semantic_confirmed"
    result = []
    by_id = {}
    for topic in topics:
        topic_id = topic["topic_id"]
        if topic_id is not None:
            topic = {**topic, "label": active[topic_id]["label"]}
        if topic_id is None or topic_id not in by_id:
            topic = {**topic, "evidence_spans": list(topic["evidence_spans"])}
            result.append(topic)
            if topic_id is not None:
                by_id[topic_id] = topic
        else:
            prior = by_id[topic_id]
            for span in topic["evidence_spans"]:
                if span not in prior["evidence_spans"]:
                    prior["evidence_spans"].append(span)
    return result


def _decisions(raw, candidates, active):
    if not isinstance(raw, dict) or set(raw) != {"matches"} or not isinstance(raw["matches"], list):
        raise ValueError("Invalid topic matching response")
    expected = {c["candidate_id"] for c in candidates}
    decisions = {}
    for match in raw["matches"]:
        if not isinstance(match, dict) or set(match) != {"candidate_id", "topic_id"}:
            raise ValueError("Invalid topic match")
        key, target = match["candidate_id"], match["topic_id"]
        if not isinstance(key, str) or key not in expected or key in decisions:
            raise ValueError("Unknown or duplicate candidate ID")
        if target is not None and (not isinstance(target, str) or target not in active or active[target]["kind"] != "topic"):
            raise ValueError("Topic match must use an active compatible registry ID")
        decisions[key] = target
    if set(decisions) != expected:
        raise ValueError("Missing topic matching decisions")
    return decisions
