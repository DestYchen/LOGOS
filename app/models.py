from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.enums import BatchStatus, DocumentStatus, DocumentType, ValidationSeverity


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""

    pass


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[BatchStatus] = mapped_column(Enum(BatchStatus), default=BatchStatus.NEW)
    meta: Mapped[Dict[str, object]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    documents: Mapped[List["Document"]] = relationship("Document", back_populates="batch", cascade="all, delete-orphan")
    validations: Mapped[List["Validation"]] = relationship("Validation", back_populates="batch", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    mime: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    doc_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), default=DocumentType.UNKNOWN)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.NEW)
    ocr_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filled_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    batch: Mapped["Batch"] = relationship("Batch", back_populates="documents")
    fields: Mapped[List["FilledField"]] = relationship("FilledField", back_populates="document", cascade="all, delete-orphan")


class FilledField(Base):
    __tablename__ = "filled_fields"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    field_key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bbox: Mapped[Optional[List[float]]] = mapped_column(JSONB, nullable=True)
    token_refs: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String, default="unknown")
    version: Mapped[int] = mapped_column(Integer, default=1)
    latest: Mapped[bool] = mapped_column(Boolean, default=True)
    edited_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="fields")


class Validation(Base):
    __tablename__ = "validations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[ValidationSeverity] = mapped_column(Enum(ValidationSeverity), nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    refs: Mapped[Optional[List[Dict[str, object]]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    batch: Mapped["Batch"] = relationship("Batch", back_populates="validations")


class SystemStatusSnapshot(Base):
    __tablename__ = "system_status"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=datetime.utcnow)
    workers_busy: Mapped[int] = mapped_column(Integer, default=0)
    workers_total: Mapped[int] = mapped_column(Integer, default=0)
    queue_depth: Mapped[int] = mapped_column(Integer, default=0)
    active_batches: Mapped[int] = mapped_column(Integer, default=0)
    active_docs: Mapped[int] = mapped_column(Integer, default=0)
