from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.core.enums import BatchStatus, DocumentStatus, DocumentType


class BatchCreateRequest(BaseModel):
    created_by: Optional[str] = Field(default=None, max_length=128)


class BatchCreateResponse(BaseModel):
    batch_id: uuid.UUID


class BatchUploadResponse(BaseModel):
    saved: List[str]


class DocumentSummary(BaseModel):
    id: uuid.UUID
    filename: str
    status: DocumentStatus
    doc_type: DocumentType
    pages: int = 0


class BatchSummary(BaseModel):
    id: uuid.UUID
    status: BatchStatus
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    documents: List[DocumentSummary]


class ReviewField(BaseModel):
    doc_id: uuid.UUID
    document_filename: str
    field_key: str
    value: Optional[str]
    confidence: float
    required: bool
    threshold: float
    source: str
    page: Optional[int]
    bbox: Optional[List[float]]
    token_refs: Optional[List[str]]
    doc_type: DocumentType


class ReviewResponse(BaseModel):
    batch_id: uuid.UUID
    status: BatchStatus
    low_conf_threshold: float
    fields: List[ReviewField]


class FieldUpdateRequest(BaseModel):
    value: Optional[str]
    bbox: Optional[List[float]] = None
    token_refs: Optional[List[str]] = None


class ReviewCompleteResponse(BaseModel):
    batch_id: uuid.UUID
    status: BatchStatus


class ValidationRef(BaseModel):
    doc_id: Optional[uuid.UUID]
    field_key: Optional[str]
    page: Optional[int]
    bbox: Optional[List[float]]


class ValidationResult(BaseModel):
    rule_id: str
    severity: str
    message: str
    refs: List[ValidationRef] = Field(default_factory=list)


class BatchReportResponse(BaseModel):
    batch_id: uuid.UUID
    status: BatchStatus
    validations: List[ValidationResult]
    meta: dict = Field(default_factory=dict)


class ArchiveEntry(BaseModel):
    id: uuid.UUID
    status: BatchStatus
    created_at: datetime
    updated_at: datetime
    document_count: int
    report_url: Optional[str]


class ArchiveResponse(BaseModel):
    batches: List[ArchiveEntry]


class SystemStatusResponse(BaseModel):
    workers_busy: int
    workers_total: int
    queue_depth: int
    active_batches: int
    active_docs: int
    updated_at: datetime
