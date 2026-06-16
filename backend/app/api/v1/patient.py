"""Patient-side API endpoints.

Phase 2a: Health profile, care plans, reminders, and health check-ins.
"""
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.agent import CarePlan, MonitoringEvent, PatientHealthProfile
from app.models.medical_case import MedicalCase
from app.models.user import User, UserRole

router = APIRouter(dependencies=[Depends(get_current_user)])


VALID_CHRONIC_DISEASES = {
    "E11": "2型糖尿病", "I10": "原发性高血压", "I25": "冠心病",
    "I50": "慢性心力衰竭", "I48": "心房颤动", "I63": "脑梗死",
    "E78": "高脂血症", "J44": "慢阻肺", "J45": "支气管哮喘",
    "N18": "慢性肾病", "K76.0": "脂肪肝", "B18.1": "慢性乙型肝炎",
    "E05": "甲亢", "E03": "甲减", "M81": "骨质疏松",
    "M06": "类风湿关节炎", "M17": "膝骨关节炎",
    "G20": "帕金森病", "F32": "抑郁症", "F41": "焦虑障碍",
}


# ═══════════════════════════════════════════════════════════════
# Health Profile
# ═══════════════════════════════════════════════════════════════

@router.get("/profile")
async def get_profile(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get patient health profile (flat format, matches frontend PatientProfile)."""
    result = await db.execute(
        select(PatientHealthProfile).where(
            PatientHealthProfile.patient_id == current_user.id
        )
    )
    profile = result.scalar_one_or_none()
    return {
        "id": str(current_user.id),
        "name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone,
        "date_of_birth": getattr(current_user, 'date_of_birth', None),
        "gender": current_user.gender,
        "height": profile.height if profile else None,
        "weight": profile.weight if profile else None,
        "allergies": profile.allergies if profile else [],
        "chronic_diseases": profile.chronic_diseases if profile else [],
        "medications": profile.current_medications if profile else [],
    }


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    phone: str | None = Field(None, max_length=20)
    gender: str | None = Field(None, pattern=r'^(male|female|男|女)$')
    height: int | None = Field(None, ge=50, le=300)
    weight: int | None = Field(None, ge=10, le=500)
    allergies: list[str] | None = None
    chronic_diseases: list[dict] | None = None
    medications: list[dict] | None = None


@router.patch("/profile")
async def update_profile(
    data: ProfileUpdateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update patient profile (flat format)."""
    if data.name is not None:
        current_user.full_name = data.name
    if data.phone is not None:
        current_user.phone = data.phone
    if data.gender is not None:
        current_user.gender = data.gender

    profile = await db.scalar(
        select(PatientHealthProfile).where(
            PatientHealthProfile.patient_id == current_user.id
        )
    )
    if not profile:
        profile = PatientHealthProfile(patient_id=current_user.id)
        db.add(profile)

    if data.height is not None:
        profile.height = data.height
    if data.weight is not None:
        profile.weight = data.weight
    if data.allergies is not None:
        profile.allergies = data.allergies
    if data.chronic_diseases is not None:
        profile.chronic_diseases = data.chronic_diseases
    if data.medications is not None:
        profile.current_medications = data.medications
    profile.last_updated = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(current_user)
    await db.refresh(profile)
    return {
        "id": str(current_user.id),
        "name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone,
        "gender": current_user.gender,
        "height": profile.height,
        "weight": profile.weight,
        "allergies": profile.allergies or [],
        "chronic_diseases": profile.chronic_diseases or [],
        "medications": profile.current_medications or [],
    }


# ═══════════════════════════════════════════════════════════════
# Medical Cases
# ═══════════════════════════════════════════════════════════════

@router.get("/cases")
async def list_cases(
    current_user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List patient's medical cases."""
    stmt = (
        select(MedicalCase)
        .where(MedicalCase.patient_id == current_user.id)
        .order_by(MedicalCase.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "description": c.description,
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "diagnosis": getattr(c, "diagnosis", None),
        }
        for c in result.scalars().all()
    ]


# ═══════════════════════════════════════════════════════════════
# Care Plans
# ═══════════════════════════════════════════════════════════════

@router.get("/care-plans")
async def list_care_plans(
    current_user: CurrentUser,
    status: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List patient's care plans."""
    stmt = (
        select(CarePlan)
        .where(CarePlan.patient_id == current_user.id)
        .order_by(CarePlan.created_at.desc())
    )
    if status:
        stmt = stmt.where(CarePlan.status == status)
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "description": p.description,
            "goals": [],
            "tasks": p.tasks or {},
            "status": p.status,
            "progress_percent": p.progress_percent or 0,
            "start_date": p.start_date.isoformat() if p.start_date else None,
            "end_date": p.end_date.isoformat() if p.end_date else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in result.scalars().all()
    ]


@router.get("/care-plans/{plan_id}")
async def get_care_plan(
    plan_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a specific care plan."""
    result = await db.execute(
        select(CarePlan).where(
            CarePlan.id == plan_id,
            CarePlan.patient_id == current_user.id,
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {
        "id": str(p.id),
        "title": p.title,
        "description": p.description,
        "diagnosis_summary": p.diagnosis_summary,
        "goals": [],
        "tasks": p.tasks or {},
        "status": p.status,
        "progress_percent": p.progress_percent or 0,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.post("/care-plans/{plan_id}/ack")
async def ack_task(
    plan_id: str,
    task_id: Annotated[str, Query(alias="task_id")],
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge (complete) a task in a care plan."""
    result = await db.execute(
        select(CarePlan).where(
            CarePlan.id == plan_id,
            CarePlan.patient_id == current_user.id,
        )
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    tasks = plan.tasks or {}
    # Accept either dict tasks or AcknowledgeRequest body
    if task_id:
        if isinstance(tasks, dict) and "tasks" in tasks:
            for t in tasks["tasks"]:
                if t.get("id") == task_id:
                    t["status"] = "completed"
        elif isinstance(tasks, list):
            for t in tasks:
                if t.get("id") == task_id:
                    t["completed"] = True
    plan.tasks = tasks
    await db.commit()
    return {"success": True, "task_id": task_id}


# ═══════════════════════════════════════════════════════════════
# Reminders
# ═══════════════════════════════════════════════════════════════

@router.get("/reminders")
async def list_reminders(
    current_user: CurrentUser,
    status: Annotated[str | None, Query()] = "pending",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List patient's scheduled reminders."""
    stmt = (
        select(MonitoringEvent)
        .where(MonitoringEvent.patient_id == current_user.id)
        .order_by(MonitoringEvent.scheduled_at.desc())
    )
    if status:
        stmt = stmt.where(MonitoringEvent.status == status)
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "payload": e.payload,
            "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
            "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
            "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
            "status": e.status,
            "plan_id": str(e.plan_id) if e.plan_id else None,
        }
        for e in result.scalars().all()
    ]


@router.patch("/reminders/{reminder_id}/acknowledge")
async def acknowledge_reminder(
    reminder_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge a specific reminder."""
    result = await db.execute(
        select(MonitoringEvent).where(
            MonitoringEvent.id == reminder_id,
            MonitoringEvent.patient_id == current_user.id,
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Reminder not found")
    event.acknowledged_at = datetime.now(timezone.utc)
    event.status = "acknowledged"
    await db.commit()
    return {"success": True, "id": reminder_id}


# ═══════════════════════════════════════════════════════════════
# Check-in
# ═══════════════════════════════════════════════════════════════

class CheckInRequest(BaseModel):
    plan_id: str
    task_id: str
    value: float | None = None
    notes: str | None = None


@router.post("/check-in")
async def check_in(
    data: CheckInRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Patient check-in: mark a task as completed with optional value/notes."""
    result = await db.execute(
        select(CarePlan).where(
            CarePlan.id == data.plan_id,
            CarePlan.patient_id == current_user.id,
        )
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    tasks = plan.tasks or {}
    if isinstance(tasks, dict) and "tasks" in tasks:
        for t in tasks["tasks"]:
            if t.get("id") == data.task_id:
                t["status"] = "completed"
                if data.value is not None:
                    t["last_value"] = data.value
                if data.notes:
                    t["notes"] = data.notes
    plan.tasks = tasks
    await db.commit()
    return {"success": True, "task_id": data.task_id, "task_status": "completed"}


# ═══════════════════════════════════════════════════════════════
# Health Profile Refresh (triggers AI regeneration)
# ═══════════════════════════════════════════════════════════════

@router.post("/health-profile/refresh")
async def refresh_health_profile(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger AI to regenerate health summary from patient history."""
    from app.tasks.planning import generate_health_profile
    task = generate_health_profile.delay(str(current_user.id))
    return {"task_id": task.id, "message": "Health profile refresh started"}
