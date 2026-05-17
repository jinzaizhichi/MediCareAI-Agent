"""Medical case and document models.

Plan C (Layered Model):
- MedicalCase is a lightweight wrapper referencing AgentSession as the clinical source of truth.
- Redundant fields (chief_complaint, ai_diagnosis_summary, severity, is_emergency)
  are written once at case creation for fast list display and P0-2 context injection.
- Full clinical data is loaded via source_session_id -> AgentSession.
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class CaseStatus(str, PyEnum):
    PENDING_REVIEW = "pending_review"
    IN_PROGRESS = "in_progress"
    AWAITING_PATIENT = "awaiting_patient"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class DocumentType(str, PyEnum):
    REPORT = "report"
    PRESCRIPTION = "prescription"
    IMAGE = "image"
    LAB_RESULT = "lab_result"
    DISCHARGE_SUMMARY = "discharge_summary"
    OTHER = "other"


class MedicalCase(Base):
    """A patient's episode of care — layered design."""

    __tablename__ = "medical_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── Ownership & Assignment ──
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Patient who owns this case",
    )
    assigned_doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Doctor assigned to this case",
    )

    # ── Reference: AI consultation source ──
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="AgentSession that produced the AI diagnosis",
    )

    # ── Redundant layer: written once at diagnosis completion ──
    chief_complaint: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Patient's chief complaint (from InterviewState)",
    )
    ai_diagnosis_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="AI diagnosis summary (from structured_output.primary_diagnosis)",
    )
    severity: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="mild / moderate / severe / emergency",
    )
    is_emergency: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Whether this is an emergency case",
    )

    # ── Management layer ──
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus), default=CaseStatus.PENDING_REVIEW, nullable=False
    )

    doctor_diagnosis: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Doctor-confirmed or corrected diagnosis",
    )
    doctor_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Doctor's clinical notes",
    )

    treatment_plan: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="Treatment plan (structured JSON)",
    )

    follow_up_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Next follow-up due date",
    )

    # ── Timestamps ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When the case was resolved",
    )

    # ── Relationships ──
    documents: Mapped[list["MedicalDocument"]] = relationship(
        "MedicalDocument",
        back_populates="medical_case",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    source_session: Mapped["AgentSession | None"] = relationship(
        "AgentSession",
        foreign_keys=[source_session_id],
        lazy="selectin",
    )


class MedicalDocument(Base):
    """A document attached to a medical case."""

    __tablename__ = "medical_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medical_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType), default=DocumentType.OTHER, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="Storage path or URL"
    )
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="OCR-extracted or plain text content"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    # Relationships
    medical_case: Mapped["MedicalCase"] = relationship(
        "MedicalCase", back_populates="documents"
    )
