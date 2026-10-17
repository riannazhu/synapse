"""In-memory integration fixture, NOT a replacement for A's persistent worker."""
from copy import deepcopy
from threading import RLock
from time import monotonic
from uuid import NAMESPACE_URL, uuid5

from server.analysis.corrections import apply_overrides
from server.analysis.service import _spans
from server.graphs.layout import generate_positions
from server.graphs.service import GraphService


class MemoryRepository:
    def __init__(self, snapshot):
        self.snapshot = deepcopy(snapshot)
        self.lock = RLock()
        self.leases = {}

    def grant(self, source_id, token, *, seconds=90):
        with self.lock:
            self.leases[source_id] = (token, monotonic()+seconds)

    def _leased(self, source_id, token):
        current = self.leases.get(source_id)
        return current is not None and current[0] == token and current[1] > monotonic()

    def read_analysis(self, *, user_id, entry_id, revision):
        with self.lock:
            entry = next((e for e in self.snapshot["entries"] if e["id"] == entry_id
                          and e["user_id"] == user_id), None)
            if not entry or entry.get("deleted") or not entry.get("approved") or entry["revision"] != revision:
                return None
            return {"text": entry["text"], "entry_date": entry["entry_date"],
                    "topics": deepcopy([t for t in self.snapshot["topics"] if t["user_id"] == user_id])}

    def publish_analysis(self, *, user_id, entry_id, revision, lease_token, result):
        with self.lock:
            if not self._leased(entry_id, lease_token) or self.read_analysis(user_id=user_id, entry_id=entry_id, revision=revision) is None:
                return False
            if (result["entry_id"] != entry_id or result["revision"] != revision):
                raise ValueError("Analysis does not match publishing revision")
            # All work below is committed by one pointer replacement; exceptions
            # cannot partially mutate the fixture. A implements a DB transaction.
            working = deepcopy(self.snapshot)
            entry = next(e for e in working["entries"] if e["id"] == entry_id and e["user_id"] == user_id)
            if result["entry_date"] != entry["entry_date"]:
                return False
            if entry.get("analysis_status") == "succeeded" and entry.get("pipeline_version") == result["pipeline_version"]:
                del self.leases[entry_id]
                return True
            registry = {t["id"]: t for t in working["topics"] if t["user_id"] == user_id}
            assignments = deepcopy(result["topics"])
            for assignment in assignments:
                key = assignment["topic_id"]
                if key:
                    visited = set()
                    while key in registry and registry[key].get("merged_into"):
                        if key in visited:
                            raise ValueError("Cyclic topic redirect")
                        visited.add(key)
                        key = registry[key]["merged_into"]
                    if key not in registry or registry[key]["kind"] != assignment["kind"]:
                        raise ValueError("Unowned or incompatible topic")
                else:
                    normalized = assignment["label"].strip().casefold()
                    matches = [t["id"] for t in registry.values() if not t.get("merged_into")
                               and t["kind"] == assignment["kind"] == "topic"
                               and normalized in {name.strip().casefold() for name in [t["label"], *t.get("aliases", [])]}]
                    key = matches[0] if len(matches) == 1 else None
                    if key is None:
                        # Stable within the retried entry, never across people by name.
                        seed = f"{user_id}/{entry_id}/{revision}/{assignment['kind']}/{normalized}/{len(registry)}"
                        key = str(uuid5(NAMESPACE_URL, seed))
                        topic = {"id": key, "user_id": user_id, "label": assignment["label"],
                                 "kind": assignment["kind"], "aliases": []}
                        working["topics"].append(topic)
                        registry[key] = topic
                        working["topic_version"] = working.get("topic_version", 0)+1
                assignment["topic_id"] = key
                assignment["label"] = registry[key]["label"]
            overrides = [o for o in working.get("overrides", []) if o["user_id"] == user_id and o["entry_id"] == entry_id]
            assignments, reviews = apply_overrides(assignments, overrides, revision=revision)
            for review in reviews:
                for override in working.get("overrides", []):
                    if (override.get("user_id") == review["user_id"] and override.get("entry_id") == review["entry_id"]
                            and override.get("topic_id") == review["topic_id"]
                            and override.get("source_revision") == review["source_revision"]):
                        override["review_needed"] = True
            for override in working.get("mention_overrides", []):
                if override["user_id"] != user_id or override["entry_id"] != entry_id:
                    continue
                if override["source_revision"] != revision or override.get("review_needed"):
                    override["review_needed"] = True
                    continue
                target = registry.get(override["target_topic_id"])
                if not target:
                    raise ValueError("Split override references foreign topic")
                moved = []
                for assignment in assignments:
                    if assignment["topic_id"] != override["source_topic_id"]:
                        continue
                    for span in list(assignment["evidence_spans"]):
                        if all(span[key] == override[key] for key in ("start", "end", "quote")):
                            assignment["evidence_spans"].remove(span)
                            moved.append(span)
                if moved:
                    assignments.append({"topic_id": target["id"], "label": target["label"], "kind": target["kind"],
                                        "resolution": "user", "evidence_spans": moved})
            assignments = [a for a in assignments if a["evidence_spans"]]
            for table in ("mentions", "passages", "goal_events"):
                working[table] = [r for r in working.get(table, []) if not (r["user_id"] == user_id and r["entry_id"] == entry_id)]
            for assignment in assignments:
                if assignment["topic_id"] not in registry:
                    raise ValueError("Override references foreign topic")
                for span in _spans(assignment["evidence_spans"], entry["text"]):
                    seed = f"{user_id}/{entry_id}/{revision}/{assignment['topic_id']}/{span['start']}/{span['end']}"
                    row = {"id": str(uuid5(NAMESPACE_URL, seed)), "user_id": user_id, "entry_id": entry_id,
                           "revision": revision, "topic_id": assignment["topic_id"], **span,
                           "assignment_source": "user" if assignment["resolution"] == "user" else "model"}
                    if not any(m["id"] == row["id"] for m in working["mentions"]):
                        working["mentions"].append(row)
            for passage in result["passages"]:
                working["passages"].append({**deepcopy(passage), "user_id": user_id, "entry_id": entry_id, "revision": revision,
                    "id": str(uuid5(NAMESPACE_URL, f"{user_id}/{entry_id}/{revision}/passage/{passage['start']}"))})
            for mention in working["mentions"]:
                if mention["user_id"] == user_id and mention["entry_id"] == entry_id:
                    mention["passage_id"] = next((p["id"] for p in working["passages"]
                        if p["user_id"] == user_id and p["entry_id"] == entry_id
                        and p["start"] <= mention["start"] < p["end"]), None)
            for event in result["goal_events"]:
                span_keys = _spans(event["evidence_spans"], entry["text"])
                linked = {a["topic_id"] for a in assignments if a["kind"] == "topic" and any(
                    max(s["start"], e["start"]) < min(s["end"], e["end"])
                    for s in a["evidence_spans"] for e in span_keys)}
                working["goal_events"].append({**deepcopy(event), "user_id": user_id,
                    "entry_id": entry_id, "revision": revision, "topic_id": next(iter(linked)) if len(linked) == 1 else None,
                    "review_status": "pending"})
            entry["analysis_status"] = "succeeded"
            entry["pipeline_version"] = result["pipeline_version"]
            graph = GraphService(working, user_id=user_id)
            _, edges, _, _ = graph._aggregate(graph._entries())
            positions = generate_positions(graph.topics, edges,
                {key: {"x": t["x"], "y": t["y"]} for key, t in graph.topics.items() if "x" in t and "y" in t})
            for key, point in positions.items():
                registry[key].update(point)
            working["corpus_version"] = working.get("corpus_version", 0)+1
            working["derived_stale"] = True
            working.setdefault("refresh_keys", []).append(f"{user_id}:{working['corpus_version']}")
            self.snapshot = working
            del self.leases[entry_id]
            return True

    def read_capture(self, *, user_id, source_id, version):
        with self.lock:
            source = next((s for s in self.snapshot.get("captures", []) if s["id"] == source_id
                           and s["user_id"] == user_id and s["version"] == version and not s.get("deleted")), None)
            return deepcopy(source)

    def publish_capture(self, *, user_id, source_id, version, lease_token, result):
        with self.lock:
            if not self._leased(source_id, lease_token) or self.read_capture(user_id=user_id, source_id=source_id, version=version) is None:
                return False
            source = next(s for s in self.snapshot["captures"] if s["id"] == source_id and s["user_id"] == user_id)
            source["result"] = deepcopy(result)
            source["state"] = "needs_review"
            del self.leases[source_id]
            return True
