"""Worker handler; scheduling/leases/transactions belong to Track A."""
from typing import Protocol

from server.analysis.service import analyze_entry
from server.models.embeddings import embed_text


class AnalysisRepository(Protocol):
    def read_analysis(self, *, user_id, entry_id, revision) -> dict | None: ...
    def publish_analysis(self, *, user_id, entry_id, revision, lease_token, result) -> bool:
        """Atomically recheck live revision/lease, reconcile registry and overrides,
        replace analysis, increment corpus version, invalidate, enqueue refresh.
        """
        ...


class AnalysisHandler:
    def __init__(self, repository: AnalysisRepository, *, embedder=None):
        self.repository, self.embedder = repository, embedder

    def __call__(self, *, user_id, entry_id, revision, lease_token):
        snapshot = self.repository.read_analysis(user_id=user_id, entry_id=entry_id, revision=revision)
        if snapshot is None:
            return {"status": "cancelled"}
        result = analyze_entry(entry_id, snapshot["text"], snapshot["topics"],
                               entry_date=snapshot["entry_date"], revision=revision)
        if self.embedder:
            for passage in result["passages"]:
                vector = embed_text(self.embedder, passage["text"])
                passage["embedding"] = {"model_version": vector.model_version,
                                        "dimension": len(vector.values), "values": list(vector.values)}
        published = self.repository.publish_analysis(
            user_id=user_id, entry_id=entry_id, revision=revision,
            lease_token=lease_token, result=result)
        return {"status": "succeeded" if published else "cancelled", "entry_id": entry_id,
                "revision": revision}
