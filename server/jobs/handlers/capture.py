"""Capture workers return reviewable text through A's extraction repository."""
from typing import Protocol


class CaptureRepository(Protocol):
    def read_capture(self, *, user_id, source_id, version) -> dict | None:
        """Authorize and read private bytes/messages, scoped to a live source."""
        ...

    def publish_capture(self, *, user_id, source_id, version, lease_token, result) -> bool:
        """Atomically check source version, tombstone, lease; store needs_review only."""
        ...


class CaptureHandler:
    def __init__(self, repository: CaptureRepository, adapter):
        self.repository, self.adapter = repository, adapter

    def __call__(self, *, user_id, source_id, version, lease_token, kind):
        source = self.repository.read_capture(user_id=user_id, source_id=source_id, version=version)
        if source is None:
            return {"status": "cancelled"}
        if kind == "audio":
            result = self.adapter.transcribe(source["data"], mime_type=source["mime_type"], duration_ms=source["duration_ms"])
        elif kind == "handwriting":
            result = self.adapter.extract_pages(source["pages"])
        elif kind == "summary":
            result = self.adapter.summarize(source["messages"])
        elif kind == "reply":
            result = self.adapter.reply(source["messages"], history_enabled=source.get("history_enabled", False),
                                        evidence=source.get("evidence"))
        else:
            raise ValueError("Unsupported capture job kind")
        published = self.repository.publish_capture(user_id=user_id, source_id=source_id, version=version,
                                                     lease_token=lease_token, result=result)
        return {"status": "succeeded" if published else "cancelled", "source_id": source_id}
