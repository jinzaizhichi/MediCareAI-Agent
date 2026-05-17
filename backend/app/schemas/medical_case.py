"""Medical case and document schemas — Plan C."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.medical_case import CaseStatus, DocumentType


# ─── MedicalDocument ───────────────────────────────────────────

class MedicalDocumentBase(BaseModel):
    document_type: DocumentType = DocumentType.OTHER
    title: str = Field(..., min_length=1, max_length=255)
    file_path: str | None = Field(None, max_length=500)
    file_size: int | None = None
    mime_type: str | None = Field(None, max_length=100)
    content_text: str | None = None


class MedicalDocumentCreate(MedicalDocumentBase):
    pass


class MedicalDocumentUpdate(BaseModel):
    document_type: DocumentType | None = None
    title: str | None = Field(None, max_length=255)
    content_text: str | None = None


class MedicalDocumentResponse(MedicalDocumentBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    case_id: uuid.UUID
    uploaded_by: uuid.UUID | None
    created_at: datetime


# ─── MedicalCase ───────────────────────────────────────────

class MedicalCaseBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    status: CaseStatus = CaseStatus.PENDING_REVIEW
    chief_complaint: str | None = None
    ai_diagnosis_summary: str | None = None
    severity: str | None = None
    is_emergency: bool = False


class MedicalCaseCreate(MedicalCaseBase):
    source_session_id: uuid.UUID | None = None


class MedicalCaseUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str | None = None
    status: CaseStatus | None = None
    chief_complaint: str | None = None
    severity: str | None = None


class MedicalCaseDoctorUpdate(BaseModel):
    doctor_diagnosis: str | None = None
    doctor_notes: str | None = None
    treatment_plan: dict | None = None
    status: CaseStatus | None = None
    follow_up_due_at: datetime | None = None
    assigned_doctor_id: uuid.UUID | None = None


class MedicalCaseResponse(MedicalCaseBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    patient_id: uuid.UUID
    assigned_doctor_id: uuid.UUID | None
    source_session_id: uuid.UUID | None
    doctor_diagnosis: str | None
    doctor_notes: str | None
    treatment_plan: dict | None
    follow_up_due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    documents: list[MedicalDocumentResponse] = []


class MedicalCaseListResponse(BaseModel):
    total: int
    items: list[MedicalCaseResponse]
