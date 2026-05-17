"""Multi-Agent Medical Collaboration endpoints.

New design per PROPOSAL.md:
- /route      → MasterAgent intent classification + auto-routing
- /diagnose   → DiagnosisAgent with Tool Use + structured output
- /plan       → PlanningAgent with structured treatment plan
- /monitor    → MonitoringAgent with structured assessment
- /consult    → Full multi-agent consultation
- /sessions   → Agent session management
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, CurrentUserContext, CurrentUserContextLenient, UserContext, require_role
from app.db.session import async_session_maker, get_db
from app.models.agent import AgentSession, AgentSessionStatus, AgentSessionType
from app.models.user import User, UserRole
from app.services.agents import AgentOrchestrator, DiagnosisAgent, MonitoringAgent, PlanningAgent
from app.services.llm import LLMService
from app.services.rag import RAGService
from app.tools.registry import GLOBAL_REGISTRY

router = APIRouter()

# In-memory bridge: frontend session_id (string) → lab report data
# Frontend generates local IDs (non-UUID), lab reports are posted before
# the backend creates the real DB session. This bridge ensures lab data
# reaches the diagnosis even when session IDs differ.
_session_lab_bridge: dict[str, list[dict[str, Any]]] = {}


def _inject_lab_context(messages: list[dict[str, str]], lab_reports: list[dict[str, Any]]) -> None:
    """Format lab reports and insert into the message list as a system prompt."""
    lab_text = "**已上传的检查报告解析结果：**\n"
    for r in lab_reports:
        indicators = r.get("indicators", [])
        if indicators:
            lab_text += f"\n报告 (置信度: {int(r.get('overall_confidence', 0) * 100)}%):\n"
            for ind in indicators[:30]:
                abn = " [异常]" if ind.get("abnormal") else ""
                lab_text += f"  - {ind.get('indicator_name', '?')}: {ind.get('value', '?')} {ind.get('unit', '')}{abn}\n"
    messages.insert(0, {"role": "system", "content": lab_text})


async def _build_conversation_context(
    db: AsyncSession,
    query_sid: str,
    messages: list[dict[str, str]],
    intent: str,
    user_id: str | None = None,
) -> None:
    """Inject full session context for post-diagnosis conversation (P0-2).

    When session phase is 'completed' and intent is not 'diagnosis',
    loads the diagnosis report, interview history, lab reports, and
    historical cases (for registered users) into the system prompt.
    """
    import uuid as _uuid

    try:
        session = await db.get(AgentSession, _uuid.UUID(query_sid))
    except (ValueError, Exception):
        return

    if not session or not session.context:
        return

    interview_data = session.context.get("interview")
    if not interview_data:
        return

    phase = interview_data.get("phase", "")
    if phase != "completed":
        return

    context_parts = [
        "## Patient Session Context\n"
        "The following is the complete consultation history and diagnosis for this patient. "
        "Base your response on this context.\n"
    ]

    # 1. Diagnosis Report
    if session.structured_output:
        report = session.structured_output
        context_parts.append("### Previous Diagnosis Report")
        context_parts.append(f"**Primary Diagnosis**: {report.get('primary_diagnosis', 'Unknown')}")
        context_parts.append(f"**Severity**: {report.get('severity', 'Unknown')}")
        context_parts.append(f"**Confidence**: {report.get('confidence', 'Unknown')}")
        if report.get('differential_diagnoses'):
            context_parts.append("**Differential Diagnoses**:")
            for d in report['differential_diagnoses'][:5]:
                if isinstance(d, dict):
                    context_parts.append(f"  - {d.get('diagnosis', '')}")
        if report.get('key_findings'):
            context_parts.append(f"**Key Findings**: {'; '.join(str(f) for f in report['key_findings'][:5])}")
        if report.get('recommended_actions'):
            context_parts.append(f"**Recommended Actions**: {'; '.join(str(a) for a in report['recommended_actions'][:5])}")
        if report.get('red_flags'):
            context_parts.append(f"**Red Flags**: {'; '.join(str(r) for r in report['red_flags'])}")
        context_parts.append("")

    # 2. Interview Q&A Summary
    collected = interview_data.get("collected_info", {})
    if collected:
        context_parts.append("### Collected Clinical Information")
        for k, v in collected.items():
            if not k.startswith("__") and v:
                v_str = str(v)[:200]
                context_parts.append(f"- **{k}**: {v_str}")
        context_parts.append("")

    # 3. Lab Reports
    lab_reports = session.context.get("lab_reports", [])
    if lab_reports:
        context_parts.append("### Lab / Examination Reports")
        for i, r in enumerate(lab_reports):
            indicators = r.get("indicators", [])
            if indicators:
                context_parts.append(f"**Report {i + 1}** (confidence: {int(r.get('overall_confidence', 0) * 100)}%):")
                for ind in indicators[:10]:
                    abn = " [ABNORMAL]" if ind.get("abnormal") else ""
                    context_parts.append(
                        f"  - {ind.get('indicator_name', '?')}: "
                        f"{ind.get('value', '?')} {ind.get('unit', '')}{abn}"
                    )
        context_parts.append("")

    # 4. Historical Cases (registered users only)
    if user_id:
        try:
            from app.tools.medical import QueryPatientHistoryTool
            history_tool = QueryPatientHistoryTool()
            history_result = await history_tool.execute(
                patient_id=user_id, limit=5, include_documents=False
            )
            cases = history_result.get("cases", [])
            if cases:
                context_parts.append("### Patient Historical Cases")
                for case in cases[:5]:
                    cc = case.get("chief_complaint") or case.get("title", "Unknown")
                    context_parts.append(f"- [{case.get('status', '?')}] {cc}")
                    dd = case.get("diagnosis_doctor") or case.get("ai_diagnosis_summary", "")
                    if dd:
                        context_parts.append(f"  Diagnosis: {dd[:150]}")
                context_parts.append("")

            # Load Health Profile
            try:
                from sqlalchemy import select as _select
                from app.models.agent import PatientHealthProfile
                stmt = _select(PatientHealthProfile).where(
                    PatientHealthProfile.patient_id == _uuid.UUID(user_id)
                )
                result = await db.execute(stmt)
                profile = result.scalar_one_or_none()
                if profile:
                    context_parts.append("### Patient Health Profile")
                    if profile.health_summary:
                        context_parts.append(f"**Overview**: {profile.health_summary[:300]}")
                    if profile.disease_patterns and isinstance(profile.disease_patterns, dict):
                        rc = profile.disease_patterns.get("recurrent_conditions", [])
                        if rc:
                            context_parts.append(f"**Common Issues**: {', '.join(str(c) for c in rc[:5])}")
                    if profile.medication_history and isinstance(profile.medication_history, dict):
                        cur = profile.medication_history.get("current", [])
                        if cur:
                            context_parts.append(f"**Current Medications**: {', '.join(str(m) for m in cur[:5])}")
                        ar = profile.medication_history.get("adverse_reactions", [])
                        if ar:
                            context_parts.append(f"**Adverse Reactions**: {', '.join(str(a) for a in ar[:5])}")
                    if profile.risk_factors and isinstance(profile.risk_factors, dict):
                        risks = [f"{k}: {v}" for k, v in profile.risk_factors.items() if v]
                        if risks:
                            context_parts.append(f"**Risk Factors**: {'; '.join(risks[:5])}")
                    context_parts.append("")
            except Exception:
                pass
        except Exception:
            pass

    context_text = "\n".join(context_parts)
    context_text += "\n---\nBased on the above context and the user's new message, provide a professional, coherent response."

    messages.insert(0, {"role": "system", "content": context_text})


# ---------------------------------------------------------------------------
# Helper: DiagnosisReport → Markdown
# ---------------------------------------------------------------------------

def _diagnosis_report_to_markdown(report: dict[str, Any]) -> str:
    """Convert DiagnosisReport dict to Markdown for frontend rendering."""
    lines: list[str] = []
    _unknown = "\u672a\u77e5"
    _pending = "\u5f85\u5b9a"

    lines.append("### \ud83c\udfe5 \u521d\u6b65\u8bca\u65ad")
    lines.append("**" + report.get("primary_diagnosis", _unknown) + "**")
    lines.append("")

    if report.get("differential_diagnoses"):
        lines.append("### \ud83d\udd0d \u9274\u522b\u8bca\u65ad")
        for d in report["differential_diagnoses"]:
            if isinstance(d, dict):
                diag_name = d.get("diagnosis", "")
                reasoning = d.get("reasoning", "")
                lines.append(f"- **{diag_name}**: {reasoning}")
            else:
                lines.append("- " + str(d))
        lines.append("")

    severity = report.get("severity", _unknown)
    severity_emoji = {"mild": "\ud83d\udfe2", "moderate": "\ud83d\udfe1", "severe": "\ud83d\udd34", "emergency": "\u26d4"}.get(severity, "")
    lines.append("**\u4e25\u91cd\u7a0b\u5ea6**: " + severity_emoji + " " + severity)
    lines.append("**\u7f6e\u4fe1\u5ea6**: " + report.get("confidence", _unknown))
    lines.append("")

    if report.get("key_findings"):
        lines.append("### \ud83d\udccb \u5173\u952e\u53d1\u73b0")
        for f in report["key_findings"]:
            lines.append("- " + str(f))
        lines.append("")

    if report.get("recommended_tests"):
        lines.append("### \ud83e\uddea \u63a8\u8350\u68c0\u67e5")
        for t in report["recommended_tests"]:
            lines.append("- " + str(t))
        lines.append("")

    if report.get("recommended_actions"):
        lines.append("### \ud83d\udc8a \u5efa\u8bae\u63aa\u65bd")
        for a in report["recommended_actions"]:
            lines.append("- " + str(a))
        lines.append("")

    if report.get("contraindications"):
        lines.append("### \u26a0\ufe0f \u7981\u5fcc\u4e8b\u9879")
        for c in report["contraindications"]:
            lines.append("- " + str(c))
        lines.append("")

    if report.get("red_flags"):
        lines.append("### \ud83d\udea8 \u5371\u9669\u4fe1\u53f7\uff08\u9700\u7acb\u5373\u5c31\u533b\uff09")
        for r in report["red_flags"]:
            lines.append("- " + str(r))
        lines.append("")

    if report.get("follow_up_required"):
        lines.append("### \ud83d\udcc5 \u968f\u8bbf")
        lines.append("\u9700\u8981\u968f\u8bbf\uff0c\u65f6\u95f4: " + report.get("follow_up_timeline", _pending))
        lines.append("")

    if report.get("knowledge_sources"):
        lines.append("### \ud83d\udcda \u77e5\u8bc6\u6765\u6e90")
        for s in report["knowledge_sources"]:
            lines.append("- " + str(s))
        lines.append("")

    disclaimer = report.get("disclaimer")
    if disclaimer:
        lines.append("> " + str(disclaimer))

    return "\n".join(lines)


def _chunk_text(text: str, chunk_size: int = 80) -> list[str]:
    """Split text into chunks for SSE streaming simulation."""
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RouteRequest(BaseModel):
    """Natural language input for MasterAgent routing."""

    message: str = Field(..., min_length=1, max_length=2000, description="Patient message")
    patient_id: str | None = Field(None, description="Patient UUID if authenticated")
    patient_history: str | None = Field(None, max_length=5000)
    provider: str | None = None


class DiagnosisRequest(BaseModel):
    """Symptom analysis request with Tool Use."""

    symptoms: str = Field(..., min_length=5, max_length=2000)
    patient_id: str | None = Field(None, description="Patient UUID for history lookup")
    patient_history: str | None = Field(None, max_length=5000)
    test_results: str | None = Field(None, max_length=5000)
    provider: str | None = None


class PlanningRequest(BaseModel):
    """Treatment planning request."""

    diagnosis: str = Field(..., min_length=5, max_length=2000)
    patient_profile: dict[str, Any] | None = None
    constraints: list[str] | None = None
    provider: str | None = None


class MonitoringRequest(BaseModel):
    """Monitoring check request."""

    patient_updates: str = Field(..., min_length=5, max_length=3000)
    baseline_status: str | None = None
    current_plan: str | None = None
    provider: str | None = None


class ConsultationRequest(BaseModel):
    """Full multi-agent consultation request."""

    symptoms: str = Field(..., min_length=5, max_length=2000)
    patient_id: str | None = Field(None)
    patient_history: str | None = Field(None, max_length=5000)
    patient_profile: dict[str, Any] | None = None
    provider: str | None = None


class SessionListResponse(BaseModel):
    """Agent session list item."""

    id: str
    session_type: str
    status: str
    intent: str | None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/route", status_code=status.HTTP_200_OK)
async def route_request(
    req: RouteRequest,
    ctx: CurrentUserContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """MasterAgent: classify intent and route to the appropriate Agent."""
    orchestrator = AgentOrchestrator(provider=req.provider)
    patient_id = req.patient_id or (str(ctx.user.id) if ctx.user else None)
    return await orchestrator.route(
        user_input=req.message,
        patient_id=patient_id,
        patient_history=req.patient_history,
    )


@router.post("/diagnose", status_code=status.HTTP_200_OK)
async def diagnose(
    req: DiagnosisRequest,
    ctx: CurrentUserContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """DiagnosisAgent: structured diagnosis with Tool Use."""
    agent = DiagnosisAgent(provider=req.provider)
    result = await agent.analyze(
        symptoms=req.symptoms,
        patient_id=req.patient_id or (str(ctx.user.id) if ctx.user else None),
        patient_history=req.patient_history,
        test_results=req.test_results,
    )
    return {
        "agent": "diagnosis",
        "structured": result.structured_output.model_dump() if result.structured_output else None,
        "content": result.content,
        "tool_calls_used": result.tool_calls_used,
        "session_id": result.session_id,
    }


@router.post("/plan", status_code=status.HTTP_200_OK)
async def plan_treatment(
    req: PlanningRequest,
    ctx: CurrentUserContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """PlanningAgent: structured treatment plan."""
    agent = PlanningAgent(provider=req.provider)
    result = await agent.plan(
        diagnosis=req.diagnosis,
        patient_profile=req.patient_profile,
        constraints=req.constraints,
    )
    return {
        "agent": "planning",
        "structured": result.structured_output.model_dump() if result.structured_output else None,
        "content": result.content,
    }


@router.post("/monitor", status_code=status.HTTP_200_OK)
async def monitor(
    req: MonitoringRequest,
    ctx: CurrentUserContext,
) -> dict[str, Any]:
    """MonitoringAgent: structured monitoring assessment."""
    agent = MonitoringAgent(provider=req.provider)
    result = await agent.check(
        patient_updates=req.patient_updates,
        baseline_status=req.baseline_status,
        current_plan=req.current_plan,
    )
    return {
        "agent": "monitoring",
        "structured": result.structured_output.model_dump() if result.structured_output else None,
        "content": result.content,
    }


@router.post("/consult", status_code=status.HTTP_200_OK)
async def full_consultation(
    req: ConsultationRequest,
    ctx: CurrentUserContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Full multi-agent consultation (diagnosis + plan + monitoring)."""
    orchestrator = AgentOrchestrator(provider=req.provider)
    patient_id = req.patient_id or (str(ctx.user.id) if ctx.user else None)
    return await orchestrator.route(
        user_input=req.symptoms,
        patient_id=patient_id,
        patient_history=req.patient_history,
    )


@router.get("/sessions", response_model=list[SessionListResponse])
async def list_sessions(
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(UserRole.ADMIN, UserRole.DOCTOR)),
) -> list[SessionListResponse]:
    """List Agent sessions (admin/doctor only).

    Query params:
    - status: active, completed, escalated, failed
    - type: diagnosis, planning, monitoring, consultation
    """
    stmt = select(AgentSession).order_by(AgentSession.created_at.desc())

    if status_filter:
        stmt = stmt.where(AgentSession.status == AgentSessionStatus(status_filter))
    if type_filter:
        from app.models.agent import AgentSessionType
        stmt = stmt.where(AgentSession.session_type == AgentSessionType(type_filter.upper()))

    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return [
        SessionListResponse(
            id=str(s.id),
            session_type=s.session_type.value,
            status=s.status.value,
            intent=s.intent,
            created_at=s.created_at.isoformat() if s.created_at else "",
            updated_at=s.updated_at.isoformat() if s.updated_at else "",
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(UserRole.ADMIN, UserRole.DOCTOR)),
) -> dict[str, Any]:
    """Get full Agent session details."""
    import uuid as uuid_module

    stmt = select(AgentSession).where(AgentSession.id == uuid_module.UUID(session_id))
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "id": str(session.id),
        "session_type": session.session_type.value,
        "status": session.status.value,
        "intent": session.intent,
        "context": session.context,
        "tool_calls": session.tool_calls,
        "structured_output": session.structured_output,
        "escalation_reason": session.escalation_reason,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


# ---------------------------------------------------------------------------
# Streaming SSE endpoints (backend-ready, frontend to integrate later)
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/lab-reports")
async def store_lab_reports(
    session_id: str,
    reports: list[dict[str, Any]] = Body(default_factory=list),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Store parsed lab report data for a session (creates session if needed)."""
    import uuid as _uuid
    try:
        sid = _uuid.UUID(session_id)
        _s = await db.get(AgentSession, sid)
    except ValueError:
        _s = None
    if not _s:
        _s = AgentSession(
            id=_uuid.uuid4(),
            session_type=AgentSessionType.DIAGNOSIS,
            status=AgentSessionStatus.ACTIVE,
            intent="diagnosis",
            context={},
        )
        db.add(_s)
        await db.commit()
        await db.refresh(_s)
    ctx = dict(_s.context or {})
    existing = ctx.get("lab_reports", [])
    existing.extend(reports)
    ctx["lab_reports"] = existing
    _s.context = ctx
    await db.commit()
    # Accumulate in bridge (append, don't overwrite)
    prev = _session_lab_bridge.get(session_id, [])
    prev.extend(reports)
    _session_lab_bridge[session_id] = prev
    # Update interview session with ALL accumulated reports from bridge
    await _update_interview_session_lab_data(db, session_id, prev)
    import logging as _log
    _l = _log.getLogger("debug.t3")
    _l.info("[DEBUG-T3] store_lab_reports: session_id=%s db_id=%s reports=%d total_indicators=%d",
            session_id, str(_s.id), len(existing),
            sum(len(r.get('indicators', [])) for r in existing))
    return {"status": "stored", "session_id": str(_s.id), "count": len(existing)}


async def _update_interview_session_lab_data(
    db: AsyncSession, frontend_sid: str, lab_reports: list[dict[str, Any]]
) -> None:
    """Find the interview session with matching _frontend_sid and update its lab data."""
    import uuid as _uuid
    import logging as _log
    _l = _log.getLogger("debug.t3")
    try:
        from sqlalchemy import select as _select
        stmt = (
            _select(AgentSession)
            .where(AgentSession.session_type == AgentSessionType.DIAGNOSIS)
            .where(AgentSession.status == AgentSessionStatus.ACTIVE)
            .order_by(AgentSession.created_at.desc())
            .limit(5)
        )
        result = await db.execute(stmt)
        sessions = result.scalars().all()
        for s in sessions:
            ctx = s.context or {}
            if ctx.get("_frontend_sid") == frontend_sid:
                ctx["lab_reports"] = lab_reports
                s.context = ctx
                await db.commit()
                _l.info("[DEBUG-T3] store_lab_reports: updated interview session %s with %d reports",
                        str(s.id), len(lab_reports))
                return
        _l.info("[DEBUG-T3] store_lab_reports: no matching interview session found for _frontend_sid=%s",
                frontend_sid)
    except Exception as e:
        _l.warning("[DEBUG-T3] store_lab_reports: failed to update interview session: %s", e)


@router.get("/route/stream")
async def route_stream(
    message: str,
    request: Request,
    ctx: CurrentUserContextLenient,
    db: AsyncSession = Depends(get_db),
    patient_id: str | None = None,
    patient_history: str | None = None,
    provider: str | None = None,
) -> StreamingResponse:
    """MasterAgent intent classification + streaming multi-agent response via SSE.

    Frontend connects via:
        const es = new EventSource(`/api/v1/agents/route/stream?message=...`)

    SSE Events:
        intent          →  MasterAgent 意图分类结果
        agent_switch    →  切换到专科 Agent
        thinking        →  Agent 分析思考过程
        tool_call       →  调用工具
        tool_result     →  工具返回结果
        text            →  流式文本片段
        structured      →  结构化诊断报告
        complete        →  流结束
        error           →  错误
    """
    # Auto-create guest session only when no Bearer token was attempted.
    # Registered users with expired Bearer tokens should get 401 so their
    # frontend can trigger a token refresh — NOT silently downgrade to guest.
    has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")
    if not has_bearer and ctx.user is None and not ctx.is_guest:
        from app.models.user import GuestSession
        from app.core.security import create_guest_token
        import uuid as _uuid
        session_token = _uuid.uuid4().hex
        guest = GuestSession(
            session_token=session_token,
            fingerprint="sse-auto",
            max_messages=999,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db.add(guest)
        await db.commit()
        await db.refresh(guest)
        token = create_guest_token(str(guest.id), "sse-auto", platform="web")
        ctx = UserContext(user=None, platform="web", is_guest=True, guest_id=str(guest.id))
        # Send the new token to the client via SSE so frontend can update localStorage
        # (this is a best-effort — EventSource fires onopen first, then we yield)

    # Registered user with expired Bearer token: return 401 so frontend refreshes
    if has_bearer and ctx.user is None and not ctx.is_guest:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please refresh.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def event_generator():
        # Emit new guest token if one was auto-created
        if ctx.is_guest and ctx.guest_id:
            yield f"event: guest_token\ndata: {json.dumps({'guest_token': getattr(ctx, '_new_token', None) or ''})}\n\n"

        master = AgentOrchestrator(provider=provider)
        actual_patient_id = patient_id or (str(ctx.user.id) if ctx.user else None)

        yield f"event: thinking\ndata: {json.dumps({'step': 'master', 'message': '🧠 MasterAgent 正在分析您的需求...'})}\n\n"

        intent_result = await master.master.classify_intent(message)
        intent = intent_result.get("intent", "diagnosis")
        confidence = intent_result.get("confidence", "medium")
        reasoning = intent_result.get("reasoning", "")

        yield f"event: intent\ndata: {json.dumps(intent_result)}\n\n"
        yield f"event: thinking\ndata: {json.dumps({'step': 'master_done', 'message': f'✅ 意图识别完成: {intent} (置信度: {confidence})', 'detail': reasoning})}\n\n"

        # ─── Step 2: Agent 切换 ───
        agent_name_map = {
            "diagnosis": "DiagnosisAgent 诊断专家",
            "planning": "PlanningAgent 治疗规划",
            "monitoring": "MonitoringAgent 随访监测",
            "research": "ResearchAgent 医学研究",
            "consultation": "Consultation 综合诊疗",
            "general": "General 通用医疗",
        }
        # Escalation is now handled within the diagnosis pipeline — not a separate route
        if intent == "escalation":
            intent = "diagnosis"
        agent_display = agent_name_map.get(intent, agent_name_map["general"])

        yield f"event: agent_switch\ndata: {json.dumps({'agent': intent, 'agent_display': agent_display, 'message': f'🔄 正在切换到 {agent_display}...'})}\n\n"

        # ─── Step 3: 专科 Agent 处理 + 流式输出 ───
        async with async_session_maker() as db_stream:
            llm = LLMService(provider=provider, platform=ctx.platform, db=db_stream)

            # 根据意图构建专属 system prompt
            system_prompts = {
                "diagnosis": """You are DiagnosisAgent, an expert diagnostic AI physician.

ROLE:
- Analyze patient symptoms thoroughly
- Consider differential diagnoses
- Ask clarifying questions when needed
- Flag emergency conditions immediately

OUTPUT FORMAT:
Use Markdown formatting:
- **bold** for important medical terms
- bullet lists for findings/suggestions
- numbered lists for step-by-step advice
- ### headers for sections

Always include:
1. Possible causes analysis
2. Key questions to narrow down
3. Self-care recommendations
4. Red flags requiring immediate medical attention
5. Disclaimer

SAFETY: Never dismiss patient concerns. Flag emergencies.""",

                "planning": """You are PlanningAgent, an expert treatment planning AI.

ROLE:
- Generate evidence-based treatment plans
- Recommend medications with dosing when appropriate
- Suggest lifestyle modifications
- Plan follow-up schedule

OUTPUT FORMAT:
Use Markdown formatting with clear sections.""",

                "monitoring": """You are MonitoringAgent, a patient follow-up AI.

ROLE:
- Analyze patient-reported outcomes
- Detect deterioration or improvement trends
- Generate alerts when thresholds are crossed

OUTPUT FORMAT:
Use Markdown formatting.""",

                "research": """You are ResearchAgent, a medical research assistant.

ROLE:
- Synthesize medical knowledge into clear answers
- Cite sources when possible
- Distinguish evidence levels

OUTPUT FORMAT:
Use Markdown formatting.""",

                "general": """You are MediCareAI-Agent, a helpful medical AI assistant.

ROLE:
- Provide accurate, evidence-based medical information
- Be clear and compassionate
- Always include appropriate disclaimers

OUTPUT FORMAT:
Use Markdown formatting for readability.""",
            }

            system_prompt = system_prompts.get(intent, system_prompts["general"])

            # 添加患者上下文
            messages: list[dict[str, str]] = [{"role": "user", "content": message}]
            if patient_history:
                messages.insert(0, {"role": "system", "content": f"Patient history context: {patient_history}"})

            # 加载已上传的化验单解析结果到上下文
            session_id: str | None = None
            query_sid = request.query_params.get("session_id")
            if query_sid:
                import logging as _logmod
                _log = _logmod.getLogger("debug.t3")
                _log.info("[DEBUG-T3] route_stream: query_sid=%s", query_sid)
                # Try DB lookup first (real UUID sessions)
                try:
                    _qs = await db.get(AgentSession, uuid.UUID(query_sid))
                    if _qs and _qs.context:
                        lab_reports = _qs.context.get("lab_reports", [])
                        if lab_reports:
                            _log.info("[DEBUG-T3] route_stream: DB lookup found %d reports", len(lab_reports))
                            _inject_lab_context(messages, lab_reports)
                        else:
                            _log.info("[DEBUG-T3] route_stream: DB session exists but no lab_reports in context")
                except (ValueError, Exception):
                    _log.info("[DEBUG-T3] route_stream: DB lookup failed (non-UUID or missing)")
                # Fallback: check in-memory bridge for frontend-generated session IDs
                if not any("已上传的检查报告" in m.get("content", "") for m in messages):
                    lab_reports = _session_lab_bridge.get(query_sid, [])
                    if lab_reports:
                        _log.info("[DEBUG-T3] route_stream: bridge found %d reports for key=%s", len(lab_reports), query_sid)
                        _inject_lab_context(messages, lab_reports)
                    else:
                        _log.warning("[DEBUG-T3] route_stream: bridge EMPTY for key=%s, bridge_keys=%s", query_sid, list(_session_lab_bridge.keys()))

            # P0-2: Inject full session context for post-diagnosis conversation
            if query_sid and intent != "diagnosis":
                try:
                    s = await db.get(AgentSession, uuid.UUID(query_sid))
                    if s and s.context:
                        interview_data = s.context.get("interview", {})
                        if interview_data.get("phase") == "completed":
                            await _build_conversation_context(
                                db, query_sid, messages, intent,
                                user_id=actual_patient_id
                            )
                except (ValueError, Exception):
                    pass

            # 真实工具调用 + 流式输出
            if intent == "diagnosis":
                # ─── Interview phase: collect info before diagnosis ───
                # Create a session to persist interview state (if not already loaded)
                if not session_id:
                    try:
                        new_session = await master._create_session(
                            user_id=uuid.UUID(actual_patient_id) if actual_patient_id else None,
                            session_type=AgentSessionType.DIAGNOSIS,
                            intent="diagnosis",
                        )
                        if new_session:
                            session_id = str(new_session.id)
                            # Carry over lab reports from bridge into the new session context
                            if query_sid:
                                # Store frontend session ID so interview_answer can find bridge data
                                _nctx = dict(new_session.context or {})
                                _nctx["_frontend_sid"] = query_sid
                                bridge_reports = _session_lab_bridge.get(query_sid, [])
                                if bridge_reports:
                                    _nctx["lab_reports"] = bridge_reports
                                    import logging as _log2
                                    _log2.getLogger("debug.t3").info("[DEBUG-T3] route_stream: copied %d bridge reports to new session %s", len(bridge_reports), session_id)
                                new_session.context = _nctx
                                async with async_session_maker() as _bdb:
                                    _bs = await _bdb.get(AgentSession, uuid.UUID(session_id))
                                    if _bs:
                                        _bs.context = _nctx
                                        await _bdb.commit()
                    except Exception:
                        pass

                diag_agent = DiagnosisAgent(provider=provider)

                if session_id:
                    try:
                        questions, state, searches, action, reasoning = await diag_agent.interview(
                            session_id=session_id,
                            chief_complaint=message,
                            patient_history=patient_history,
                        )
                        if searches:
                            yield f"event: thinking\ndata: {json.dumps({'step': 'search', 'message': '🔍 后台搜索中，请先作答...'})}\n\n"
                        if questions:
                            yield f"event: interview_progress\ndata: {json.dumps({'asked_count': len(state.asked_questions), 'phase': '问诊中'})}\n\n"
                            q_list = []
                            for nq in questions:
                                q_list.append({
                                    "question_id": nq.question_id, "question": nq.question, "type": nq.type,
                                    "options": nq.options, "hint": nq.hint, "allow_skip": nq.allow_skip,
                                    "phase": nq.phase, "colloquial_phase": nq.colloquial_phase,
                                })
                            yield f"event: question\ndata: {json.dumps({'questions': q_list})}\n\n"
                            yield f"event: complete\ndata: {json.dumps({'status': 'waiting_for_answer', 'session_id': session_id})}\n\n"
                            return
                        elif state.red_flags_detected:
                            yield f"event: red_flags\ndata: {json.dumps({'red_flags': state.red_flags_detected, 'message': '检测到危险信号，建议立即就医'})}\n\n"
                            # Do NOT return — proceed to diagnosis with red flags included

                        # Redis lock first — prevent concurrent diagnoses
                        from app.db.redis_client import get_redis
                        redis_client = get_redis()
                        lock_key = f"diag_lock:{session_id}"
                        locked = await redis_client.set(lock_key, "1", nx=True, ex=300)
                        if not locked:
                            yield f"event: complete\ndata: {json.dumps({'status': 'already_diagnosed', 'session_id': session_id})}\n\n"
                            return

                        yield f"event: thinking\ndata: {json.dumps({'step': 'diagnosis', 'message': '🧠 问诊信息充足，正在综合分析并搜索医学知识...'})}\n\n"

                        workflow_result = await diag_agent.run_full_diagnosis_workflow(
                            session_id=session_id,
                            patient_id=actual_patient_id,
                            patient_history=patient_history,
                        )
                        if workflow_result.tool_calls_used:
                            for tc in workflow_result.tool_calls_used:
                                tname = tc.get('tool', '?')
                                yield f"event: tool_call\ndata: {json.dumps({'tool': tname, 'params': tc.get('arguments', {}), 'message': '🔍 正在执行 ' + tname + '...'})}\n\n"
                                await asyncio.sleep(0.2)
                                yield f"event: tool_result\ndata: {json.dumps({'tool': tname, 'result': tc.get('result', {}), 'message': '✅ ' + tname + ' 执行完成'})}\n\n"
                        if workflow_result.structured_output:
                            yield f"event: structured\ndata: {json.dumps(workflow_result.structured_output.model_dump())}\n\n"
                            report_md = _diagnosis_report_to_markdown(workflow_result.structured_output.model_dump())
                            for chunk in _chunk_text(report_md, chunk_size=80):
                                yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"

                            # Plan C: Auto-create MedicalCase for registered users
                            if actual_patient_id and session_id:
                                try:
                                    from app.models.medical_case import MedicalCase as MC, CaseStatus as CS
                                    from sqlalchemy import select as _sel
                                    existing = await db.execute(
                                        _sel(MC).where(MC.source_session_id == uuid.UUID(session_id))
                                    )
                                    if not existing.scalar_one_or_none():
                                        report = workflow_result.structured_output.model_dump()
                                        chief = interview_data.get("chief_complaint", message) if 'interview_data' in dir() else message
                                        mc = MC(
                                            patient_id=uuid.UUID(actual_patient_id),
                                            source_session_id=uuid.UUID(session_id),
                                            title=f"AI Diagnosis: {report.get('primary_diagnosis', 'Unknown')[:50]}",
                                            chief_complaint=chief,
                                            ai_diagnosis_summary=report.get('primary_diagnosis', '')[:500],
                                            severity=report.get('severity', 'unknown'),
                                            is_emergency=(report.get('severity') == 'emergency'),
                                            status=CS.PENDING_REVIEW,
                                        )
                                        db.add(mc)
                                        await db.commit()
                                except Exception:
                                    pass
                        else:
                            content = workflow_result.content if isinstance(workflow_result.content, str) else ''
                            for chunk in _chunk_text(content, chunk_size=80):
                                yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                        yield f"event: complete\ndata: {json.dumps({'message': '✅ 响应完成', 'session_id': session_id})}\n\n"
                        return
                    except Exception:
                        # Interview failed — fall through to direct diagnosis
                        pass

                _msg_start = "🧠 DiagnosisAgent 正在启动真实诊断分析..."
                yield f"event: thinking\ndata: {json.dumps({'step': 'diagnosis', 'message': _msg_start})}\n\n"

                try:
                    result = await diag_agent.analyze(
                        symptoms=message,
                        patient_id=actual_patient_id,
                        patient_history=patient_history,
                        session_id=session_id,
                    )

                    # 流式展示真实工具调用记录
                    if result.tool_calls_used:
                        for tc in result.tool_calls_used:
                            tool_name = tc.get("tool", "unknown")
                            args = tc.get("arguments", {})
                            _tc_msg = "\ud83d\udd0d \u6b63\u5728\u6267\u884c " + tool_name + "..."
                            yield f"event: tool_call\ndata: {json.dumps({'tool': tool_name, 'params': args, 'message': _tc_msg})}\n\n"
                            await asyncio.sleep(0.2)
                            result_data = tc.get("result", {})
                            _tr_msg = "\u2705 " + tool_name + " \u6267\u884c\u5b8c\u6210"
                            yield f"event: tool_result\ndata: {json.dumps({'tool': tool_name, 'result': result_data, 'message': _tr_msg})}\n\n"

                    _msg_analyze = "\ud83e\udde0 DiagnosisAgent \u6b63\u5728\u7efc\u5408\u5206\u6790\u5e76\u751f\u6210\u7ed3\u6784\u5316\u62a5\u544a..."
                    yield f"event: thinking\ndata: {json.dumps({'step': 'diagnosis', 'message': _msg_analyze})}\n\n"

                    # 输出结构化报告
                    if result.structured_output:
                        structured_data = result.structured_output.model_dump()
                        yield f"event: structured\ndata: {json.dumps(structured_data)}\n\n"

                        report_md = _diagnosis_report_to_markdown(structured_data)
                        for chunk in _chunk_text(report_md, chunk_size=80):
                            yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                    else:
                        content = result.content if isinstance(result.content, str) else json.dumps(result.content, ensure_ascii=False)
                        for chunk in _chunk_text(content, chunk_size=80):
                            yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                except Exception as e:
                    _err_msg = "\u8bca\u65ad\u5206\u6790\u5931\u8d25: " + str(e)
                    yield f"event: error\ndata: {json.dumps({'error': _err_msg})}\n\n"
                    return

            else:
                # 其他意图走通用 LLM 流
                try:
                    async for chunk in llm.chat_stream(
                        messages=messages,
                        system_prompt=system_prompt,
                        max_tokens=2048,
                    ):
                        yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                except Exception as e:
                    yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                    return

        yield f"event: complete\ndata: {json.dumps({'message': '✅ 响应完成'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.api_route("/route/stream/continue", methods=["GET", "POST"])
async def route_stream_continue(
    request: Request,
    ctx: CurrentUserContextLenient,
    session_id: str = Query(...),
    question_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Continue an interrupted interview/diagnosis stream after user answers.

    Gets answer from X-Answer header (base64) to avoid URL length + HTTP/2 issues."""
    _answer = ""
    x_answer = request.headers.get("X-Answer") or request.headers.get("x-answer")
    if x_answer:
        try:
            import base64
            _answer = base64.b64decode(x_answer).decode("utf-8")
        except Exception:
            _answer = ""
    if not _answer and request.method == "POST":
        try:
            body = await request.json()
            _answer = body.get("answer") or ""
        except Exception:
            _answer = ""
    if not _answer:
        _answer = request.query_params.get("answer") or "无"

    async def event_generator():
        # Look up the session
        stmt = select(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            yield f"event: error\ndata: {json.dumps({'error': 'Session not found'})}\n\n"
            return

        # If diagnosis is already in progress, skip — avoid snapshot race
        try:
            from app.db.redis_client import get_redis
            _r = get_redis()
            if await _r.exists(f"diag_lock:{session_id}"):
                yield f"event: complete\ndata: {json.dumps({'status': 'diagnosis_in_progress', 'session_id': session_id})}\n\n"
                return
        except Exception:
            pass

        diag_agent = DiagnosisAgent(provider=None)

        yield f"event: thinking\ndata: {json.dumps({'step': 'processing', 'message': '🧠 正在分析您的回答...'})}\n\n"

        try:
            import logging as _lmod2
            questions, state, searches, action, reasoning = await diag_agent.interview_answer(
                session_id=session_id,
                question_id=question_id,
                answer=_answer,
            )
            _lmod2.getLogger("debug.continue").info("[DEBUG-CONT] action=%s questions=%d is_sufficient=%s phase=%s red_flags=%d",
                       action, len(questions), state.is_sufficient, state.phase, len(state.red_flags_detected))
        except Exception as e:
            import logging as _lmod
            _lmod.getLogger("debug.continue").error("[DEBUG-CONT] interview_answer failed: %s", e)
            yield f"event: error\ndata: {json.dumps({'error': f'Interview error: {e}'})}\n\n"
            return

        # Interview already completed (phase=completed, regeneration exhausted)
        if action == "completed":
            yield f"event: complete\ndata: {json.dumps({'status': 'already_diagnosed', 'session_id': session_id})}\n\n"
            return

        if searches:
            yield f"event: thinking\ndata: {json.dumps({'step': 'search', 'message': '🔍 后台搜索中...'})}\n\n"

        if questions:
            yield f"event: interview_progress\ndata: {json.dumps({'asked_count': len(state.asked_questions)})}\n\n"
            q_list = [{"question_id": nq.question_id, "question": nq.question, "type": nq.type, "options": nq.options, "hint": nq.hint, "allow_skip": nq.allow_skip, "phase": nq.phase, "colloquial_phase": nq.colloquial_phase} for nq in questions]
            yield f"event: question\ndata: {json.dumps({'questions': q_list})}\n\n"
            yield f"event: complete\ndata: {json.dumps({'status': 'waiting_for_answer', 'session_id': session_id})}\n\n"
            return

        # Check for red flags
        if state.red_flags_detected:
            yield f"event: red_flags\ndata: {json.dumps({'red_flags': state.red_flags_detected, 'message': '检测到危险信号，建议立即就医'})}\n\n"

        if not state.is_sufficient:
            import logging as _lmod3
            _lmod3.getLogger("debug.continue").warning("[DEBUG-CONT] EMPTY CARDS — is_sufficient=False, no questions to show (DEADLOCK)")
            yield f"event: complete\ndata: {json.dumps({'status': 'waiting_for_answer', 'session_id': session_id})}\n\n"
            await asyncio.sleep(0.1)
            return

        # Interview complete — proceed to diagnosis using structured summary
        _msg_start = "🧠 问诊完成，正在整理问诊信息..."
        yield f"event: thinking\ndata: {json.dumps({'step': 'diagnosis', 'message': _msg_start})}\n\n"

        # Redis lock to prevent concurrent diagnoses
        try:
            from app.db.redis_client import get_redis
            redis_client = get_redis()
            lock_key = f"diag_lock:{session_id}"
            locked = await redis_client.set(lock_key, "1", nx=True, ex=60)
            if not locked:
                yield f"event: complete\ndata: {json.dumps({'status': 'already_diagnosed', 'session_id': session_id})}\n\n"
                return
        except Exception as e:
            import logging
            logging.getLogger("agents").error("Failed to acquire Redis lock: %s", e)

        try:
            yield f"event: tool_call\ndata: {json.dumps({'tool': 'search_medical_knowledge', 'params': {'query': '基于问诊摘要的医学搜索'}, 'message': '🔍 正在搜索医学知识库和最新文献...'})}\n\n"
            
            result = await diag_agent.run_full_diagnosis_workflow(
                session_id=session_id,
                patient_id=str(session.user_id) if session.user_id else None,
            )

            if result.tool_calls_used:
                for tc in result.tool_calls_used:
                    tool_name = tc.get("tool", "unknown")
                    args = tc.get("arguments", {})
                    _tc_msg = f"🔍 正在执行 {tool_name}..."
                    yield f"event: tool_call\ndata: {json.dumps({'tool': tool_name, 'params': args, 'message': _tc_msg})}\n\n"
                    await asyncio.sleep(0.2)
                    result_data = tc.get("result", {})
                    _tr_msg = f"✅ {tool_name} 执行完成"
                    yield f"event: tool_result\ndata: {json.dumps({'tool': tool_name, 'result': result_data, 'message': _tr_msg})}\n\n"

            _msg_analyze = "🧠 正在综合分析并生成诊断报告..."
            yield f"event: thinking\ndata: {json.dumps({'step': 'diagnosis', 'message': _msg_analyze})}\n\n"

            if result.structured_output:
                structured_data = result.structured_output.model_dump()
                yield f"event: structured\ndata: {json.dumps(structured_data)}\n\n"

                report_md = _diagnosis_report_to_markdown(structured_data)
                for chunk in _chunk_text(report_md, chunk_size=80):
                    yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
            else:
                content = result.content if isinstance(result.content, str) else json.dumps(result.content, ensure_ascii=False)
                for chunk in _chunk_text(content, chunk_size=80):
                    yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            import traceback, logging as _logmod
            _log = _logmod.getLogger("agents")
            _log.error("CONTINUE_DIAG_ERROR: %s\n%s", e, traceback.format_exc())
            _err_msg = f"诊断分析失败: {e}"
            yield f"event: error\ndata: {json.dumps({'error': _err_msg})}\n\n"

        yield f"event: complete\ndata: {json.dumps({'message': '✅ 响应完成'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
