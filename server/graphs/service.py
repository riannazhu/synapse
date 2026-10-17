"""Snapshot-based graph calculations. No database or model calls."""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
from itertools import combinations
from math import log1p

from server.analysis.dates import validate_date


class GraphService:
    def __init__(self, snapshot, *, user_id):
        """A supplies one consistent snapshot; all records carry authoritative user_id."""
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("Authenticated user_id is required")
        snapshot = deepcopy(snapshot)
        self.versions = {key: snapshot.get(key, 0) for key in ("corpus_version", "topic_version", "layout_version")}
        self.goal_events = [e for e in snapshot.get("goal_events", []) if e["user_id"] == user_id]
        self.registry = {t["id"]: t for t in snapshot["topics"] if t["user_id"] == user_id}
        self.topics = {key: t for key, t in self.registry.items() if not t.get("hidden") and not t.get("merged_into")}
        self.entries = {e["id"]: e for e in snapshot["entries"]
                        if e["user_id"] == user_id and not e.get("deleted") and e.get("approved", False)}
        for entry in self.entries.values():
            validate_date(entry["entry_date"])
        self.membership = defaultdict(set)
        self.evidence = defaultdict(list)
        for mention in snapshot.get("mentions", []):
            entry = self.entries.get(mention["entry_id"])
            if (mention["user_id"] != user_id or not entry
                    or entry.get("analysis_status") != "succeeded"
                    or mention["revision"] != entry["revision"]):
                continue
            topic_id = self.canonical(mention["topic_id"])
            if topic_id not in self.topics:
                continue
            start, end = mention["start"], mention["end"]
            if (type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(entry["text"])
                    or mention["quote"] != entry["text"][start:end]):
                continue
            self.membership[entry["id"]].add(topic_id)
            self.evidence[(entry["id"], topic_id)].append({**mention, "topic_id": topic_id})

    def canonical(self, key):
        seen = set()
        while key in self.registry and self.registry[key].get("merged_into"):
            if key in seen:
                raise ValueError("Cyclic topic redirect")
            seen.add(key)
            key = self.registry[key]["merged_into"]
        return key

    def _entries(self, from_date=None, to_date=None):
        for value in (from_date, to_date):
            if value is not None:
                validate_date(value)
        if from_date and to_date and from_date >= to_date:
            raise ValueError("Expected a nonempty half-open date range")
        return [e for e in self.entries.values()
                if (not from_date or e["entry_date"] >= from_date)
                and (not to_date or e["entry_date"] < to_date)]

    def _aggregate(self, entries):
        nodes, edges = Counter(), Counter()
        node_entries, edge_entries = defaultdict(list), defaultdict(list)
        for entry in sorted(entries, key=lambda e: (e["entry_date"], e["id"])):
            ids = sorted(self.membership[entry["id"]])
            nodes.update(ids)
            for key in ids:
                node_entries[key].append(entry["id"])
            pairs = list(combinations(ids, 2))
            edges.update(pairs)
            for pair in pairs:
                edge_entries[pair].append(entry["id"])
        return nodes, edges, node_entries, edge_entries

    def _render(self, entries, selected, scale, edge_scale):
        counts, edges, node_entries, edge_entries = self._aggregate(entries)
        analyzed = sum(e.get("analysis_status") == "succeeded" for e in entries)
        nodes = []
        for key in selected:
            topic = self.topics[key]
            if "x" not in topic or "y" not in topic:
                raise ValueError("Generate and persist layout coordinates before graph reads")
            count = counts[key]
            nodes.append({"id": key, "label": topic["label"], "kind": topic["kind"],
                          "x": topic["x"], "y": topic["y"], "count": count,
                          "share": count/analyzed if analyzed else None,
                          "brightness": .25+.75*log1p(count)/log1p(scale) if count else 0,
                          "entry_ids": node_entries[key]})
        return {"nodes": nodes,
                "edges": [{"source": a, "target": b, "shared_entry_count": weight,
                           "width": 1+3*log1p(weight)/log1p(edge_scale),
                           "entry_ids": edge_entries[(a, b)]}
                          for (a, b), weight in sorted(edges.items()) if a in selected and b in selected],
                "total_entries": len(entries), "analyzed_entries": analyzed,
                "pending_entries": sum(e.get("analysis_status") in {"queued", "running"} for e in entries),
                "failed_entries": sum(e.get("analysis_status") == "failed" for e in entries),
                "share_denominator": "analyzed_entries", "scale": scale,
                "edge_scale": edge_scale, "versions": self.versions}

    def graph(self, from_date=None, to_date=None, *, topic_ids=None):
        all_counts, all_edges, _, _ = self._aggregate(self._entries())
        selected = self._select(all_counts, topic_ids, 30)
        return self._render(self._entries(from_date, to_date), selected,
                            max([1, *all_counts.values()]), max([1, *all_edges.values()]))

    def _select(self, counts, topic_ids, limit):
        if topic_ids is not None:
            if any(key not in self.topics for key in topic_ids):
                raise ValueError("Unknown or hidden topic selection")
            return list(dict.fromkeys(topic_ids))[:limit]
        return sorted(self.topics, key=lambda key: (-counts[key], key))[:limit]

    def compare(self, a_from, a_to, b_from, b_to, *, topic_ids=None):
        a, b = self._entries(a_from, a_to), self._entries(b_from, b_to)
        ac, ae, _, _ = self._aggregate(a)
        bc, be, _, _ = self._aggregate(b)
        selected = self._select(ac+bc, topic_ids, 50)
        scale = max([1, *ac.values(), *bc.values()])
        edge_scale = max([1, *ae.values(), *be.values()])
        return {"positions": {key: {"x": self.topics[key]["x"], "y": self.topics[key]["y"]} for key in selected},
                "period_a": self._render(a, selected, scale, edge_scale),
                "period_b": self._render(b, selected, scale, edge_scale), "shared_scale": scale}

    def supporting_entries(self, topic_id, *, other_topic_id=None, from_date=None, to_date=None):
        if topic_id not in self.topics or (other_topic_id and other_topic_id not in self.topics):
            raise ValueError("Unknown or hidden topic")
        required = {topic_id} | ({other_topic_id} if other_topic_id else set())
        return [{"entry_id": e["id"], "revision": e["revision"], "entry_date": e["entry_date"],
                 "evidence": [span for key in sorted(required) for span in self.evidence[(e["id"], key)]]}
                for e in sorted(self._entries(from_date, to_date), key=lambda e: (e["entry_date"], e["id"]))
                if required <= self.membership[e["id"]]]

    def trend(self, topic_id, from_date, to_date):
        if topic_id not in self.topics:
            raise ValueError("Unknown or hidden topic")
        entries = self._entries(from_date, to_date)
        cursor = date.fromisoformat(from_date).replace(day=1)
        stop = date.fromisoformat(to_date)
        result = []
        while cursor < stop:
            month = cursor.isoformat()[:7]
            rows = [e for e in entries if e["entry_date"].startswith(month)]
            analyzed = sum(e.get("analysis_status") == "succeeded" for e in rows)
            count = sum(topic_id in self.membership[e["id"]] for e in rows)
            result.append({"month": month, "count": count, "total_entries": len(rows),
                           "analyzed_entries": analyzed, "share": count/analyzed if analyzed else None})
            cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        return result

    def goal_timeline(self, topic_id, from_date=None, to_date=None):
        if topic_id not in self.topics:
            raise ValueError("Unknown or hidden topic")
        entries = {e["id"]: e for e in self._entries(from_date, to_date)}
        result = []
        for event in self.goal_events:
            entry = entries.get(event["entry_id"])
            if (not entry or event["revision"] != entry["revision"]
                    or entry.get("analysis_status") != "succeeded"
                    or self.canonical(event.get("topic_id")) != topic_id):
                continue
            spans = event.get("evidence_spans", [])
            if not spans or any(type(s.get("start")) is not int or type(s.get("end")) is not int
                or not 0 <= s["start"] < s["end"] <= len(entry["text"])
                or s.get("quote") != entry["text"][s["start"]:s["end"]] for s in spans):
                continue
            validate_date(event["event_date"])
            result.append(dict(event))
        return sorted(result, key=lambda e: (e["event_date"], e["entry_id"]))
