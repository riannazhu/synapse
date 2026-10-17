"""Deterministic normalized layout; persist returned coordinates in Track A."""
import hashlib
import math
from copy import deepcopy


def _angle(key):
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16) / 16**12 * math.tau


def generate_positions(topic_ids, edges, existing=None):
    ids = sorted(set(topic_ids))
    fixed = {key: dict(value) for key, value in (existing or {}).items() if key in ids}
    positions = dict(fixed)
    for key in ids:
        if key in positions:
            continue
        neighbors = []
        for (a, b), weight in sorted(edges.items()):
            other = b if a == key else a if b == key else None
            if other in fixed:
                neighbors.append((fixed[other], weight))
        angle = _angle(key)
        if neighbors:
            total = sum(w for _, w in neighbors)
            x = sum(p["x"]*w for p, w in neighbors)/total + .04*math.cos(angle)
            y = sum(p["y"]*w for p, w in neighbors)/total + .04*math.sin(angle)
        else:
            x, y = .5 + .42*math.cos(angle), .5 + .42*math.sin(angle)
        positions[key] = {"x": min(.98, max(.02, x)), "y": min(.98, max(.02, y))}
    # Seeded force relaxation. Existing coordinates remain exactly fixed.
    for _ in range(80):
        delta = {key: [0., 0.] for key in ids if key not in fixed}
        for key in delta:
            for other in ids:
                if other == key:
                    continue
                dx = positions[key]["x"] - positions[other]["x"]
                dy = positions[key]["y"] - positions[other]["y"]
                distance = max(dx*dx + dy*dy, .001)
                delta[key][0] += .00012*dx/distance
                delta[key][1] += .00012*dy/distance
        for (a, b), weight in sorted(edges.items()):
            if a not in positions or b not in positions:
                continue
            for key, other in ((a, b), (b, a)):
                if key in delta:
                    delta[key][0] += .003*math.log1p(weight)*(positions[other]["x"]-positions[key]["x"])
                    delta[key][1] += .003*math.log1p(weight)*(positions[other]["y"]-positions[key]["y"])
        for key, (dx, dy) in delta.items():
            positions[key] = {"x": min(.98, max(.02, positions[key]["x"]+dx)),
                              "y": min(.98, max(.02, positions[key]["y"]+dy))}
    return positions


def reorganize(snapshot, *, user_id, expected_layout_version):
    """Explicit initial-import/reorganize action; never call from date filters."""
    from .service import GraphService
    if snapshot.get("layout_version", 0) != expected_layout_version:
        raise ValueError("Layout version conflict")
    result = deepcopy(snapshot)
    graph = GraphService(result, user_id=user_id)
    _, edges, _, _ = graph._aggregate(graph._entries())
    positions = generate_positions(graph.topics, edges)
    for topic in result["topics"]:
        if topic["user_id"] == user_id and topic["id"] in positions:
            topic.update(positions[topic["id"]])
    result["layout_version"] = expected_layout_version+1
    return result
