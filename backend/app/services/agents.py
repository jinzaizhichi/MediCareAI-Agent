"""Multi-Agent Medical Collaboration System.

Implements the PROPOSAL.md Agent architecture:
- DiagnosisAgent: symptom analysis with Tool Use + structured output
- PlanningAgent: treatment planning with care plan persistence
- MonitoringAgent: follow-up tracking
- MasterAgent: intent recognition + task routing
- AgentOrchestrator: coordinates the full multi-agent workflow

All agents use the unified LLM service with Tool Use and JSON Schema output.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker
from app.models.agent import AgentSession, AgentSessionStatus, AgentSessionType, AgentTask
from app.models.interview import (
    DynamicInterviewEngine,
    InterviewState,
    QuestionTemplate,
)
from app.services.llm import LLMResponse, LLMService
from app.tools.registry import GLOBAL_REGISTRY


# ---------------------------------------------------------------------------
# Structured Output Schemas
# ---------------------------------------------------------------------------

class DifferentialDiagnosis(BaseModel):
    """Single differential diagnosis entry."""

    diagnosis: str = Field(..., description="Name of the alternative diagnosis")
    icd11_code: str = Field(default="", description="ICD-11 code if known")
    reasoning: str = Field(default="", description="Why this diagnosis is plausible or should be ruled out")


class DiagnosisReport(BaseModel):
    """Structured diagnosis report — PROPOSAL §5.2."""

    primary_diagnosis: str = Field(..., description="Most likely diagnosis based on symptoms and context")
    differential_diagnoses: list[DifferentialDiagnosis] = Field(
        default_factory=list,
        description="List of alternative diagnoses that should be considered and ruled out. "
                    "Always include 2-5 plausible alternatives with reasoning.",
    )
    confidence: str = Field(..., pattern="^(high|medium|low)$", description="Confidence level in the primary diagnosis")
    severity: str = Field(default="unknown", pattern="^(mild|moderate|severe|emergency|unknown)$", description="Severity assessment of the condition")
    key_findings: list[str] = Field(
        default_factory=list,
        description="Key clinical findings that support or refute the diagnosis",
    )
    recommended_tests: list[str] = Field(
        default_factory=list,
        description="Recommended laboratory, imaging, or other diagnostic tests",
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Immediate actions the patient should take (e.g., rest, hydration, seek care)",
    )
    contraindications: list[str] = Field(
        default_factory=list,
        description="Any treatments or medications that should be avoided given the patient's condition",
    )
    follow_up_required: bool = Field(default=False, description="Whether follow-up care is needed")
    follow_up_timeline: str = Field(default="", description="Recommended timeline for follow-up (e.g., '3 days', '1 week')")
    red_flags: list[str] = Field(
        default_factory=list,
        description="Warning signs that require immediate medical attention",
    )
    knowledge_sources: list[str] = Field(
        default_factory=list,
        description="Sources of medical knowledge used (e.g., clinical guidelines, research papers)",
    )
    disclaimer: str = Field(
        default="本报告由 AI 生成，仅供参考，不能替代专业医疗诊断。",
        description="Standard medical disclaimer",
    )


class TreatmentPlan(BaseModel):
    """Structured treatment plan."""

    title: str
    goals: list[str] = Field(default_factory=list)
    medications: list[dict[str, Any]] = Field(default_factory=list)
    non_pharmacological: list[str] = Field(default_factory=list)
    follow_up_schedule: list[dict[str, Any]] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    confidence: str = Field(default="medium", pattern="^(high|medium|low)$")


class MonitoringAssessment(BaseModel):
    """Structured monitoring assessment."""

    current_status: str = Field(..., pattern="^(stable|improving|deteriorating|critical)$")
    trend_analysis: str = ""
    alerts: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    next_follow_up: str = ""


class ResearchResult(BaseModel):
    """Structured research report with external citations."""

    summary: str = Field(..., description="Concise evidence-based summary")
    sources: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str = Field(default="medium", pattern="^(high|medium|low)$")
    search_type: str = Field(..., pattern="^(guidelines|drug|papers|general)$")


# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """Standardized agent output."""

    agent_type: str
    content: str | dict[str, Any]
    confidence: str | None = None
    structured_output: BaseModel | None = None
    tool_calls_used: list[dict[str, Any]] | None = None
    session_id: str | None = None


# ---------------------------------------------------------------------------
# Master Agent — Intent Recognition + Task Routing
# ---------------------------------------------------------------------------

class MasterAgent:
    """The 'medical director' Agent.

    Receives natural language input, classifies intent, and routes
to the appropriate specialized Agent.
    """

    SYSTEM_PROMPT = """You are MasterAgent, the medical director of a multi-agent healthcare system.

ROLE:
- Analyze the user's message and determine their intent.
- Route to the correct specialized agent.
- If the input is ambiguous, ask clarifying questions.

INTENT CATEGORIES:
- "diagnosis": Patient reports symptoms, asks about a condition, or seeks a diagnosis
- "planning": Patient asks about treatment, medication, follow-up, or care plans
- "monitoring": Patient reports updates on an existing condition, asks about recovery
- "consultation": Complex multi-step request that may need diagnosis + planning
- "research": User asks about latest guidelines, drug info, clinical trials, or medical papers
- "general": General medical knowledge question (not personal)
- "escalation": Patient expresses urgency, emergency, or requests a real doctor

OUTPUT FORMAT:
Respond with a JSON object:
{
  "intent": "diagnosis|planning|monitoring|consultation|research|general|escalation",
  "confidence": "high|medium|low",
  "reasoning": "brief explanation of why this intent was chosen",
  "clarifying_question": "null or a question if more info is needed"
}

RULES:
- Never assume emergency unless explicitly stated or clear red flags present.
- If the user says "我咳嗽一周了", intent is "diagnosis".
- If the user says "药吃完了怎么办", intent is "planning".
- If the user says "有没有好转", intent is "monitoring".
- If the user says "帮我安排复查并提醒我", intent is "consultation".
- If the user says "最近有什么新的糖尿病治疗方案吗", intent is "research".
- If the user says "阿司匹林有什么副作用", intent is "research".
"""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider

    async def classify_intent(self, user_input: str) -> dict[str, Any]:
        """Classify user intent and return routing decision."""
        async with async_session_maker() as db:
            llm = LLMService(provider=self.provider, db=db)
            resp = await llm.chat(
                messages=[{"role": "user", "content": user_input}],
                system_prompt=self.SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=512,
            )
            try:
                return json.loads(resp.content)
            except json.JSONDecodeError:
                # Fallback
                return {
                    "intent": "diagnosis",
                    "confidence": "low",
                    "reasoning": "Parse error, defaulting to diagnosis",
                    "clarifying_question": None,
                }


# ---------------------------------------------------------------------------
# Diagnosis Agent — Tool Use + Structured Output
# ---------------------------------------------------------------------------

class DiagnosisAgent:
    """Analyzes symptoms with Tool Use and produces structured diagnosis reports.

    Workflow:
    1. Receive symptoms
    2. Call LLM with tools (query_patient_history, search_medical_knowledge)
    3. LLM decides what info it needs; tools are executed
    4. Collect all context
    5. Generate structured DiagnosisReport via generate_structured()
    """

    SYSTEM_PROMPT = """You are DiagnosisAgent, an expert diagnostic AI.

ROLE:
- Analyze patient symptoms and available context
- Generate a structured diagnosis report based on ALL provided information
- The medical knowledge context has ALREADY been searched and provided to you
- Do NOT search for more knowledge unless explicitly asked

AVAILABLE TOOLS:
- query_patient_history: Retrieve patient's past medical cases (if patient_id provided)
- check_drug_interactions: Check drug safety (if medications mentioned)
- generate_structured_diagnosis: Generate the final structured report

WORKFLOW:
1. Review the patient symptoms AND the provided medical knowledge search results.
2. If patient_id is provided, call query_patient_history to get past cases.
3. Call generate_structured_diagnosis to produce the final structured report.
4. Do NOT give a free-text diagnosis — always use the structured report tool.

CRITICAL:
- The medical knowledge context in the user message comes from RAG + SearXNG real-time search.
- Base your diagnosis on this evidence, not just your parametric knowledge.
- Cite the knowledge sources in your reasoning.

SAFETY:
- Flag emergency conditions immediately
- Never dismiss patient concerns
- Include appropriate disclaimers
"""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider

    async def _generate_search_query(self, symptoms_summary: str, db = None) -> str:
        """Generate an optimized medical search query from patient symptoms.

        Patient colloquial descriptions (e.g. '头痛还发烧') don't work well with
        search engines. This method uses LLM to extract structured medical keywords
        for effective literature search.

        Returns a query string optimized for SearXNG medical search.
        """
        prompt = f"""You are a medical information retrieval specialist.

TASK: Convert the following patient symptom summary into an optimized search query for medical literature search.

PATIENT SUMMARY:
{symptoms_summary}

RULES:
1. Extract the core symptoms and convert to standard medical terminology
2. Include: primary symptoms + key characteristics + duration/context
3. Add "医学" or "medical" or "clinical" or "differential diagnosis" to improve quality
4. Keep it concise (under 100 characters ideally, max 150)
5. Output ONLY the search query, no explanation, no quotes

EXAMPLES:
- Input: "主诉: 头痛 现病史: 额头疼痛 发烧38.5度"
  Output: 额头痛痛 发烧 医学鉴别诊断

- Input: "主诉: 胸闷 气短 现病史: 活动后加重 有高血压史"
  Output: 胸闷 气短 高血压 心血管 医学

- Input: "主诉: 腹痛 现病史: 右下腹剧痛 发烧恶心"
  Output: 右下腹痛 发烧 恶心 急腹症 医学

OUTPUT (search query only):"""

        llm = LLMService(provider=self.provider, db=db)
        response = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100,
        )

        query = response.content.strip() if response and response.content else str(response).strip()
        # Remove quotes if present
        query = query.strip('"\'')
        # Fallback if LLM returns empty or malformed
        if not query or len(query) < 5:
            # Extract chief complaint as fallback
            lines = symptoms_summary.split('\n')
            chief = lines[0].replace("主诉: ", "") if lines else symptoms_summary[:50]
            query = f"{chief} 医学鉴别诊断"

        logger.info(f"[SEARXNG_DEBUG] Generated search query: {query}")
        return query

    async def analyze(
        self,
        symptoms: str,
        patient_id: str | None = None,
        patient_history: str | None = None,
        test_results: str | None = None,
        session_id: str | None = None,
        knowledge_context: str | None = None,
    ) -> AgentResult:
        """Run full diagnostic analysis with Tool Use.

        Args:
            symptoms: Patient-reported symptoms
            patient_id: Optional patient UUID for history lookup
            patient_history: Free-text medical history
            test_results: Lab/imaging results
            session_id: Agent session ID for persistence
            knowledge_context: Pre-searched medical knowledge from RAG + SearXNG

        Returns:
            AgentResult with structured DiagnosisReport
        """
        tool_schemas = GLOBAL_REGISTRY.list_schemas()

        # Build initial message
        user_msg = f"## 患者主诉及问诊信息\n{symptoms}"
        if patient_history:
            user_msg += f"\n\n## 病史\n{patient_history}"
        if test_results:
            user_msg += f"\n\n## 检查结果\n{test_results}"
        if knowledge_context:
            user_msg += (
                f"\n\n## 医学知识库搜索结果（已通过RAG和SearXNG实时搜索获取）\n"
                f"{knowledge_context}\n\n"
                f"请基于以上搜索结果和患者信息生成诊断，"
                f"并在推理中引用这些来源。"
            )
        if patient_id:
            user_msg += f"\n\n患者ID: {patient_id} (可调用 query_patient_history 查询历史病例)"

        messages: list[dict[str, str]] = [{"role": "user", "content": user_msg}]
        all_tool_calls: list[dict[str, Any]] = []

        # Multi-turn tool use loop (max 3 rounds)
        async with async_session_maker() as db:
            llm = LLMService(provider=self.provider, db=db)

            for _round in range(3):
                resp = await llm.chat_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                    system_prompt=self.SYSTEM_PROMPT,
                    temperature=0.2,
                    max_tokens=2048,
                    tool_choice="auto",
                )

                if resp.tool_calls:
                    # Execute tools
                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": resp.content or "",
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["arguments"]),
                                },
                            }
                            for tc in resp.tool_calls
                        ],
                    }
                    if resp.reasoning_content:
                        assistant_msg["reasoning_content"] = resp.reasoning_content
                    messages.append(assistant_msg)

                    for tc in resp.tool_calls:
                        result = await GLOBAL_REGISTRY.execute(
                            tc["name"], tc["arguments"]
                        )
                        all_tool_calls.append({
                            "tool": tc["name"],
                            "arguments": tc["arguments"],
                            "result": result,
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                else:
                    # No more tool calls — we have the final answer
                    break

            # CRITICAL: Always force structured output — never return raw text
            content = resp.content or ""
            structured: DiagnosisReport | None = None

            # Attempt 1: Parse JSON from content
            if content.strip().startswith("{"):
                try:
                    data = json.loads(content)
                    structured = DiagnosisReport.model_validate(data)
                except Exception:
                    pass

            # Attempt 2: Force structured generation via schema-constrained LLM call
            if structured is None:
                try:
                    # Add explicit instruction to generate structured report
                    force_messages = messages + [{
                        "role": "user",
                        "content": (
                            "请根据以上信息，生成结构化诊断报告。"
                            "必须包含：primary_diagnosis, differential_diagnoses (2-5个), confidence, severity, "
                            "key_findings, recommended_tests, recommended_actions, red_flags, knowledge_sources。"
                            "输出必须是有效的JSON格式。"
                        ),
                    }]
                    structured = await llm.generate_structured(
                        messages=force_messages,
                        output_schema=DiagnosisReport,
                        temperature=0.2,
                        max_tokens=2048,
                    )
                except Exception:
                    pass

            # Attempt 3: If still None, create a minimal valid report with error indication
            if structured is None:
                structured = DiagnosisReport(
                    primary_diagnosis="诊断生成异常",
                    differential_diagnoses=[],
                    confidence="low",
                    severity="unknown",
                    key_findings=["系统无法生成完整诊断报告，请重试。"],
                    recommended_tests=["请咨询医生进行专业诊断"],
                    recommended_actions=["请尽快就医"],
                    red_flags=["系统异常，建议人工复核"],
                    knowledge_sources=[],
                )

            # Persist session if requested
            if session_id:
                await self._update_session(
                    session_id=session_id,
                    messages=messages,
                    tool_calls=all_tool_calls,
                    structured=structured.model_dump(),
                )

            return AgentResult(
                agent_type="diagnosis",
                content=structured.model_dump(),
                structured_output=structured,
                tool_calls_used=all_tool_calls,
                session_id=session_id,
            )

    async def _update_session(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        tool_calls: list[dict[str, Any]],
        structured: dict[str, Any] | None,
    ) -> None:
        """Persist session state to database."""
        async with async_session_maker() as db:
            from sqlalchemy import select
            stmt = select(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
            result = await db.execute(stmt)
            session = result.scalar_one_or_none()
            if session:
                session.context = {
                    "messages": messages,
                    "collected_info": {},
                }
                session.tool_calls = tool_calls
                if structured:
                    session.structured_output = structured
                session.updated_at = datetime.now(timezone.utc)
                await db.commit()

    # ------------------------------------------------------------------
    # Interview / Multi-turn questioning  (Clinical Standard Edition)
    # ------------------------------------------------------------------

    async def interview(
        self,
        session_id: str,
        collected_info: dict[str, Any] | None = None,
        chief_complaint: str = "",
        patient_history: str | None = None,
    ) -> tuple[QuestionTemplate | None, InterviewState]:
        """Determine the next interview question using LLM-driven clinical engine.

        NEW: Supports tool calls during interview (patient history lookup,
        knowledge search), structured answer extraction, and red flag detection.

        Returns:
            (next_question, updated_state) — next_question is None if interview is complete.
        """
        # Load existing state from session
        state = InterviewState()
        async with async_session_maker() as db:
            from sqlalchemy import select
            stmt = select(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
            result = await db.execute(stmt)
            session = result.scalar_one_or_none()
            if session and session.context:
                interview_data = session.context.get("interview")
                if interview_data:
                    state = InterviewState.from_dict(interview_data)

        # Set chief complaint on first call
        if chief_complaint and not state.chief_complaint:
            state.chief_complaint = chief_complaint

        # Merge newly provided info (legacy compat)
        if collected_info:
            state.collected_info.update(collected_info)
            for key in collected_info:
                if key not in state.asked_questions:
                    state.asked_questions.append(key)

        # Check red flags — if detected, end interview immediately
        if state.red_flags_detected:
            state.is_sufficient = True
            state.current_question_id = None
            await self._update_interview_state(session_id, state)
            return None, state

        # If already sufficient, skip
        if state.is_sufficient or len(state.asked_questions) >= state.max_questions:
            if len(state.asked_questions) >= state.min_questions:
                state.is_sufficient = True
                state.current_question_id = None
                await self._update_interview_state(session_id, state)
                return None, state

        # Use LLM to decide next question
        llm = LLMService(provider=self.provider)
        engine = DynamicInterviewEngine(llm)

        # Execute any pending suggested tools before asking next question
        tool_results: list[dict[str, Any]] = []
        if state.interview_tool_calls:
            for tc in state.interview_tool_calls:
                result = await GLOBAL_REGISTRY.execute(
                    tc.get("tool", ""), tc.get("params", {})
                )
                tool_results.append({"tool": tc.get("tool"), "result": result})
            state.interview_tool_calls = []  # Clear after execution

        next_q, state, suggested_tools = await engine.decide_next(
            state, patient_history=patient_history, tool_results=tool_results
        )

        # Store suggested tools for next round execution
        if suggested_tools:
            state.interview_tool_calls = [
                {"tool": t, "params": {}} for t in suggested_tools
            ]

        await self._update_interview_state(session_id, state)
        return next_q, state

    async def interview_answer(
        self,
        session_id: str,
        question_id: str,
        answer: str,
        patient_history: str | None = None,
    ) -> tuple[QuestionTemplate | None, InterviewState]:
        """Process a patient's answer and determine the next question.

        This is the core of the conversational interview flow:
        1. Extract structured info from natural language answer
        2. Check for red flags
        3. Decide next question (or end interview)

        Returns:
            (next_question, updated_state) — next_question is None if interview is complete.
        """
        # Load state
        state = InterviewState()
        async with async_session_maker() as db:
            from sqlalchemy import select
            stmt = select(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
            result = await db.execute(stmt)
            session = result.scalar_one_or_none()
            if session and session.context:
                interview_data = session.context.get("interview")
                if interview_data:
                    state = InterviewState.from_dict(interview_data)

        # Process answer: extract structured info from natural language
        llm = LLMService(provider=self.provider)
        engine = DynamicInterviewEngine(llm)
        state = await engine.process_answer(state, question_id, answer)

        # Check red flags immediately
        if state.red_flags_detected:
            state.is_sufficient = True
            state.current_question_id = None
            await self._update_interview_state(session_id, state)
            return None, state

        # Decide next question
        next_q, state, suggested_tools = await engine.decide_next(
            state, patient_history=patient_history
        )

        if suggested_tools:
            state.interview_tool_calls = [
                {"tool": t, "params": {}} for t in suggested_tools
            ]

        await self._update_interview_state(session_id, state)
        return next_q, state

    async def run_full_diagnosis_workflow(
        self,
        session_id: str,
        patient_id: str | None = None,
        patient_history: str | None = None,
    ) -> AgentResult:
        """Run the complete workflow: interview → search knowledge → analyze → planning.

        CRITICAL: Always searches medical knowledge (RAG + SearXNG) BEFORE
        generating diagnosis, so the diagnosis is evidence-based, not just
        from the LLM's internal parametric knowledge.
        """
        # Load interview state
        state = InterviewState()
        async with async_session_maker() as db:
            from sqlalchemy import select
            stmt = select(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
            result = await db.execute(stmt)
            session = result.scalar_one_or_none()
            if session and session.context:
                interview_data = session.context.get("interview")
                if interview_data:
                    state = InterviewState.from_dict(interview_data)

        # Build enriched symptoms from interview
        enriched_symptoms = state.get_summary()

        # STEP 0: Generate optimized medical search query using LLM
        # Patient colloquial descriptions don't work well with search engines.
        # We need structured medical keywords for effective literature search.
        async with async_session_maker() as db:
            search_query = await self._generate_search_query(enriched_symptoms, db=db)
        logger.info(f"[SEARXNG_DEBUG] Generated search query: {search_query}")

        # STEP 1: ALWAYS search medical knowledge before diagnosis
        # This ensures evidence-based diagnosis, not just LLM parametric knowledge
        logger.info(f"[SEARXNG_DEBUG] Starting search_medical_knowledge with query: {search_query[:100]}...")
        
        search_result = await GLOBAL_REGISTRY.execute(
            "search_medical_knowledge",
            {"query": search_query, "top_k": 5},
        )
        logger.info(f"[SEARXNG_DEBUG] Search result type: {type(search_result)}, has answer: {bool(search_result) if search_result else False}")
        
        knowledge_context = ""
        if isinstance(search_result, dict):
            knowledge_context = search_result.get("answer", "")
            logger.info(f"[SEARXNG_DEBUG] Knowledge context length: {len(knowledge_context)}")
        else:
            logger.warning(f"[SEARXNG_DEBUG] Unexpected search result type: {type(search_result)}, value: {str(search_result)[:200]}")

        # STEP 2: Run diagnosis analysis WITH knowledge context
        diag_result = await self.analyze(
            symptoms=enriched_symptoms,
            patient_id=patient_id,
            patient_history=patient_history,
            session_id=session_id,
            knowledge_context=knowledge_context,
        )

        # Attach the search tool call to the result so frontend can see it
        search_tool_call = {
            "tool": "search_medical_knowledge",
            "arguments": {"query": search_query, "top_k": 5},
            "result": search_result if search_result else {},
        }
        if diag_result.tool_calls_used is None:
            diag_result.tool_calls_used = []
        # Insert search at the beginning so it appears first
        diag_result.tool_calls_used.insert(0, search_tool_call)

        return diag_result

    async def _update_interview_state(
        self,
        session_id: str,
        state: InterviewState,
    ) -> None:
        """Persist interview state into AgentSession.context.

        CRITICAL: JSONB fields don't detect sub-key mutations in SQLAlchemy.
        We must re-assign the entire dict to trigger change detection.
        """
        async with async_session_maker() as db:
            from sqlalchemy import select
            stmt = select(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
            result = await db.execute(stmt)
            session = result.scalar_one_or_none()
            if session:
                # Re-assign entire context dict to trigger SQLAlchemy change detection
                session.context = {
                    **(session.context or {}),
                    "interview": state.to_dict(),
                }
                session.updated_at = datetime.now(timezone.utc)
                await db.commit()


# ---------------------------------------------------------------------------
# Planning Agent
# ---------------------------------------------------------------------------

class PlanningAgent:
    """Generates treatment plans with structured output."""

    SYSTEM_PROMPT = """You are PlanningAgent, an expert treatment planning AI.

ROLE:
- Generate evidence-based treatment plans
- Recommend medications with dosing when appropriate
- Suggest lifestyle modifications
- Plan follow-up schedule

OUTPUT: Always use the structured treatment plan format.
"""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider

    async def plan(
        self,
        diagnosis: str | dict[str, Any],
        patient_profile: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        """Generate structured treatment plan."""
        async with async_session_maker() as db:
            llm = LLMService(provider=self.provider, db=db)

            diag_text = json.dumps(diagnosis, ensure_ascii=False) if isinstance(diagnosis, dict) else diagnosis
            user_msg = f"诊断: {diag_text}"
            if patient_profile:
                user_msg += f"\n患者信息: {json.dumps(patient_profile, ensure_ascii=False)}"
            if constraints:
                user_msg += f"\n约束: {', '.join(constraints)}"

            structured = await llm.generate_structured(
                messages=[{"role": "user", "content": user_msg}],
                output_schema=TreatmentPlan,
                system_prompt=self.SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=2048,
            )

            return AgentResult(
                agent_type="planning",
                content=structured.model_dump(),
                structured_output=structured,
                session_id=session_id,
            )


# ---------------------------------------------------------------------------
# Monitoring Agent
# ---------------------------------------------------------------------------

class MonitoringAgent:
    """Tracks patient progress with structured assessment."""

    SYSTEM_PROMPT = """You are MonitoringAgent, a patient follow-up AI.

ROLE:
- Analyze patient-reported outcomes
- Detect deterioration or improvement trends
- Generate alerts when thresholds are crossed

OUTPUT: Always use the structured monitoring assessment format.
"""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider

    async def check(
        self,
        patient_updates: str,
        baseline_status: str | None = None,
        current_plan: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        """Run monitoring check with structured output."""
        async with async_session_maker() as db:
            llm = LLMService(provider=self.provider, db=db)

            user_msg = f"患者最新反馈: {patient_updates}"
            if baseline_status:
                user_msg += f"\n基线状态: {baseline_status}"
            if current_plan:
                user_msg += f"\n当前计划: {current_plan}"

            structured = await llm.generate_structured(
                messages=[{"role": "user", "content": user_msg}],
                output_schema=MonitoringAssessment,
                system_prompt=self.SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=1536,
            )

            return AgentResult(
                agent_type="monitoring",
                content=structured.model_dump(),
                structured_output=structured,
                session_id=session_id,
            )


# ---------------------------------------------------------------------------
# Research Agent — External Search + Synthesis
# ---------------------------------------------------------------------------

class ResearchAgent:
    """Searches external medical knowledge via SearXNG and synthesizes findings.

    Design: search-only, no storage. Results are injected into LLM prompts.
    """

    SYSTEM_PROMPT = """You are ResearchAgent, a medical research assistant.

ROLE:
- Synthesize external search results into clear, evidence-based answers
- Always cite sources using [1], [2], etc.
- Distinguish high-quality sources (guidelines, peer-reviewed papers)
  from lower-quality sources (general websites)
- If sources conflict, note the discrepancy and favor the more authoritative source
- Include a brief disclaimer that external search results are supplementary
"""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider

    async def research(
        self,
        query: str,
        patient_context: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        """Search external sources and synthesize a structured answer.

        Args:
            query: User's research question
            patient_context: Optional patient background for personalization
            session_id: Agent session ID for persistence

        Returns:
            AgentResult with structured ResearchResult
        """
        from app.services.external_search import ExternalSearchAgent

        async with async_session_maker() as db:
            # Build searcher from system config
            searcher = await ExternalSearchAgent.from_config(db)

            # Detect search type by keyword heuristics
            search_type = self._detect_search_type(query)

            # Execute appropriate search
            if search_type == "drug":
                raw_results = await searcher.search_drug_info(query)
            elif search_type == "papers":
                raw_results = await searcher.search_papers(query)
            else:  # guidelines or general
                raw_results = await searcher.search_guidelines(query)

            # Format as LLM context
            context = self._format_results(raw_results, search_type)

            # Generate synthesized answer via LLM
            llm = LLMService(provider=self.provider, db=db)
            user_msg = f"问题: {query}"
            if patient_context:
                user_msg += f"\n患者背景: {patient_context}"
            user_msg += f"\n\n{context}"

            structured = await llm.generate_structured(
                messages=[{"role": "user", "content": user_msg}],
                output_schema=ResearchResult,
                system_prompt=self.SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=2048,
            )

            # Enrich sources from raw_results
            sources = []
            for i, r in enumerate(raw_results[:5], 1):
                sources.append({
                    "index": i,
                    "title": r.title,
                    "url": r.url,
                    "engine": r.source_engine,
                    "trust_score": r.trust_score,
                    "is_trusted": r.is_trusted,
                })
            structured.sources = sources
            structured.search_type = search_type

            return AgentResult(
                agent_type="research",
                content=structured.model_dump(),
                structured_output=structured,
                session_id=session_id,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_search_type(self, query: str) -> str:
        """Classify the query into search type by keyword matching."""
        drug_keywords = [
            "药", "药物", "说明书", "副作用", "不良反应",
            "dosage", "dose", "mg", "tablet", "capsule",
        ]
        paper_keywords = [
            "论文", "研究", "临床试验", "trial", "meta-analysis",
            "RCT", "文献", "随机对照", "系统评价",
        ]
        guideline_keywords = [
            "指南", "guideline", "规范", "共识", "recommendation",
            "treatment", "诊疗", "管理",
        ]

        q = query.lower()
        if any(k in q for k in drug_keywords):
            return "drug"
        if any(k in q for k in paper_keywords):
            return "papers"
        if any(k in q for k in guideline_keywords):
            return "guidelines"
        return "guidelines"  # Default: treat as clinical query

    def _format_results(
        self, results: list[Any], search_type: str
    ) -> str:
        """Format search results as citation-rich context for LLM."""
        lines = [f"【外部搜索】类型: {search_type}  |  共 {len(results)} 条结果"]
        for i, r in enumerate(results[:5], 1):
            trust_marker = "[可信]" if r.is_trusted else "[一般]"
            lines.append(
                f"\n[{i}] {trust_marker} {r.title}\n"
                f"    来源: {r.source_engine}  |  可信度分: {r.trust_score}\n"
                f"    URL: {r.url}\n"
                f"    摘要: {r.snippet[:300]}"
            )
        if not results:
            lines.append("\n（未搜索到相关外部资料）")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent Orchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """Orchestrates multi-agent workflow per PROPOSAL architecture.

    Typical flow:
    1. MasterAgent classifies intent
    2. DiagnosisAgent → analyze with Tool Use
    3. PlanningAgent → generate treatment plan
    4. MonitoringAgent → schedule follow-up
    """

    def __init__(self, provider: str | None = None) -> None:
        self.master = MasterAgent(provider=provider)
        self.diagnosis = DiagnosisAgent(provider=provider)
        self.planning = PlanningAgent(provider=provider)
        self.monitoring = MonitoringAgent(provider=provider)
        self.research = ResearchAgent(provider=provider)

    async def route(
        self,
        user_input: str,
        patient_id: str | None = None,
        patient_history: str | None = None,
    ) -> dict[str, Any]:
        """Route user input to the correct Agent based on intent.

        This is the main entry point for Agent interactions.
        """
        # Step 1: Intent classification
        intent_result = await self.master.classify_intent(user_input)
        intent = intent_result.get("intent", "diagnosis")

        # Create a session for tracking
        session = await self._create_session(
            user_id=uuid.UUID(patient_id) if patient_id else None,
            session_type=AgentSessionType(intent.upper()),
            intent=intent,
        )
        session_id = str(session.id) if session else None

        # Step 2: Route to appropriate Agent
        if intent == "diagnosis":
            result = await self.diagnosis.analyze(
                symptoms=user_input,
                patient_id=patient_id,
                patient_history=patient_history,
                session_id=session_id,
            )
            return {
                "intent": intent_result,
                "agent": "diagnosis",
                "session_id": session_id,
                "result": result.content if isinstance(result.content, dict) else {"raw": result.content},
                "tool_calls_used": result.tool_calls_used,
            }

        elif intent == "planning":
            result = await self.planning.plan(
                diagnosis=user_input,
                session_id=session_id,
            )
            return {
                "intent": intent_result,
                "agent": "planning",
                "session_id": session_id,
                "result": result.content if isinstance(result.content, dict) else {"raw": result.content},
            }

        elif intent == "monitoring":
            result = await self.monitoring.check(
                patient_updates=user_input,
                session_id=session_id,
            )
            return {
                "intent": intent_result,
                "agent": "monitoring",
                "session_id": session_id,
                "result": result.content if isinstance(result.content, dict) else {"raw": result.content},
            }

        elif intent == "research":
            result = await self.research.research(
                query=user_input,
                patient_context=patient_history,
                session_id=session_id,
            )
            return {
                "intent": intent_result,
                "agent": "research",
                "session_id": session_id,
                "result": result.content if isinstance(result.content, dict) else {"raw": result.content},
            }

        elif intent == "escalation":
            await self._escalate_session(session_id, "Patient requested human doctor")
            return {
                "intent": intent_result,
                "agent": "escalation",
                "session_id": session_id,
                "message": "已为您转接人工医生，请稍候。",
            }

        else:
            # General or consultation — run full flow
            diag_result = await self.diagnosis.analyze(
                symptoms=user_input,
                patient_id=patient_id,
                patient_history=patient_history,
                session_id=session_id,
            )
            plan_result = await self.planning.plan(
                diagnosis=diag_result.content if isinstance(diag_result.content, dict) else {"diagnosis": str(diag_result.content)},
                session_id=session_id,
            )
            mon_result = await self.monitoring.check(
                patient_updates=f"初次诊断: {user_input}",
                baseline_status=diag_result.content if isinstance(diag_result.content, str) else None,
                current_plan=plan_result.content if isinstance(plan_result.content, str) else None,
                session_id=session_id,
            )
            return {
                "intent": intent_result,
                "agent": "consultation",
                "session_id": session_id,
                "diagnosis": diag_result.content if isinstance(diag_result.content, dict) else {"raw": diag_result.content},
                "treatment_plan": plan_result.content if isinstance(plan_result.content, dict) else {"raw": plan_result.content},
                "monitoring": mon_result.content if isinstance(mon_result.content, dict) else {"raw": mon_result.content},
                "disclaimer": (
                    "以上内容仅供参考，不能替代专业医疗建议。"
                    "请始终咨询合格的医疗专业人员。"
                ),
            }

    async def _create_session(
        self,
        user_id: uuid.UUID | None,
        session_type: AgentSessionType,
        intent: str | None = None,
    ) -> AgentSession | None:
        """Create a new AgentSession in the database."""
        try:
            async with async_session_maker() as db:
                session = AgentSession(
                    user_id=user_id,
                    session_type=session_type,
                    status=AgentSessionStatus.ACTIVE,
                    intent=intent,
                    context={"messages": [], "collected_info": {}},
                    tool_calls=[],
                )
                db.add(session)
                await db.commit()
                await db.refresh(session)
                return session
        except Exception:
            return None

    async def _escalate_session(self, session_id: str | None, reason: str) -> None:
        """Mark session as escalated to human doctor."""
        if not session_id:
            return
        try:
            async with async_session_maker() as db:
                from sqlalchemy import select
                stmt = select(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
                result = await db.execute(stmt)
                session = result.scalar_one_or_none()
                if session:
                    session.status = AgentSessionStatus.ESCALATED
                    session.escalation_reason = reason
                    session.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            pass
