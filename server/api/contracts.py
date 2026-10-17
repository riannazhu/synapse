"""Shared wire schemas. Dates are calendar dates; ranges are half-open."""
from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')

class CreateEntry(Contract):
    entry_date: date
    mode: Literal['text','chat','voice','handwriting']

class Block(Contract):
    id: UUID
    text: str = Field(max_length=50000)
    source_kind: Literal['text','transcript','summary','handwriting','chat'] = 'text'
    attachment_id: UUID | None = None
    reviewed: bool = False
    included: bool = True
    @model_validator(mode='after')
    def source(self):
        if self.source_kind in ('transcript','handwriting') and not self.attachment_id:
            raise ValueError('Media block requires attachment_id')
        return self

class Draft(Contract):
    expected_draft_version: int = Field(ge=1)
    blocks: list[Block] = Field(max_length=100)
    entry_date: date
    @model_validator(mode='after')
    def unique_blocks(self):
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError('Duplicate block IDs')
        if sum(len(b.text) for b in self.blocks) > 50000:
            raise ValueError('Draft exceeds 50000 characters')
        return self

class Commit(Contract):
    expected_draft_version: int = Field(ge=1)
    included_block_ids: list[UUID] = Field(min_length=1,max_length=100)
    approval: Literal[True]

class Upload(Contract):
    filename: str = Field(min_length=1,max_length=255)
    mime_type: Literal['image/jpeg','image/png','audio/mpeg','audio/mp4','audio/wav','audio/webm']
    byte_size: int = Field(gt=0,le=26214400)
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')

class Complete(Contract):
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')

class Conversation(Contract):
    entry_id: UUID
    history_enabled: bool = False
    retain_transcript: bool = False

class Message(Contract):
    client_message_id: UUID
    text: str = Field(min_length=1,max_length=10000)

class ConversationDraft(Contract):
    through_sequence: int = Field(ge=1)

class TopicEdit(Contract):
    expected_topic_version: int = Field(ge=0)
    label: str | None = Field(default=None,min_length=1,max_length=200)
    hidden: bool | None = None

class Evidence(Contract):
    entry_id: UUID
    revision: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str

class Topic(Contract):
    id: UUID
    label: str
    kind: Literal['topic','person']
    hidden: bool = False
    x: float | None = None
    y: float | None = None

class GraphNode(Topic):
    count: int = Field(ge=0)
    share: float | None
    brightness: float

class GraphEdge(Contract):
    source: UUID
    target: UUID
    shared_entry_count: int = Field(ge=1)
    width: float

class GraphResponse(Contract):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_entries: int
    analyzed_entries: int
    pending_entries: int
    failed_entries: int
    scale: dict
    versions: dict

class GoalEvent(Contract):
    id: UUID
    type: Literal['intention','practice','milestone']
    review_status: Literal['pending','confirmed','rejected']
    evidence: list[Evidence]

class ReportCard(Contract):
    id: UUID
    kind: str
    text: str
    metrics: dict
    evidence_ids: list[UUID]
    action: dict | None = None
    status: str

class CheckUp(ReportCard):
    pass

class Extraction(Contract):
    text: str
    uncertain_spans: list[dict] = Field(default_factory=list)
    segments: list[dict] = Field(default_factory=list)
    provider_version: str | None = None

class Attachment(Contract):
    id: UUID
    state: Literal['uploading','uploaded','processing','needs_review','ready','failed']
    extraction: Extraction | None
    extraction_version: int
    error_code: str | None

class Job(Contract):
    id: UUID
    status: Literal['queued','running','succeeded','failed','cancelled']
    progress_stage: str
    result: dict | None
    error_code: str | None
    attempt: int

class Entry(Contract):
    id: UUID
    entry_date: date
    draft_version: int
    current_revision: int | None
    blocks: list[Block]
    attachments: list[dict]
    analysis_status: str | None
    saved: dict | None
