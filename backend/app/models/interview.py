"""Medical Interview — Mesh-Architecture Clinical Engine.

DESIGN PRINCIPLES:
1. Non-linear, network-structured clinical reasoning
2. Agent simultaneously manages: questioning, knowledge search, differential diagnosis
3. Questioning + searching are interleaved — search can trigger new questions
4. Follows Chinese Medical History Taking (病史采集) standard as reference framework
5. No hardcoded question scripts — LLM drives all decisions via prompt engineering
6. Two integrated modules: 基本问诊 (Basic) → 精细化问诊 (Advanced) 
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum as PyEnum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Interview Phase Definitions (information categories only — NOT sequential)
# ---------------------------------------------------------------------------

class InterviewPhase(str, PyEnum):
    """Clinical information categories. These are NOT a fixed sequence."""

    # Present Illness
    HPI_ONSET = "hpi_onset"
    HPI_QUALITY = "hpi_quality"
    HPI_LOCATION = "hpi_location"
    HPI_SEVERITY = "hpi_severity"
    HPI_TIMING = "hpi_timing"
    HPI_AGGRAVATE = "hpi_aggravate"
    HPI_ASSOCIATED = "hpi_associated"
    HPI_TREATMENT = "hpi_treatment"

    # Past Medical History
    PMH_CHRONIC = "pmh_chronic"
    PMH_SURGERY = "pmh_surgery"
    PMH_INFECTION = "pmh_infection"
    PMH_ALLERGY = "pmh_allergy"

    # Personal History
    PS_LIFESTYLE = "ps_lifestyle"
    PS_OCCUPATION = "ps_occupation"
    PS_TRAVEL = "ps_travel"

    # Family History
    FH_GENETIC = "fh_genetic"
    FH_SIMILAR = "fh_similar"

    # Medication History
    MED_CURRENT = "med_current"
    MED_RECENT = "med_recent"

    # Terminal
    COMPLETE = "complete"


# Phase metadata: medical ID → { category, colloquial_category }
PHASE_META: dict[InterviewPhase, dict[str, str]] = {
    InterviewPhase.HPI_ONSET:     {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_QUALITY:   {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_LOCATION:  {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_SEVERITY:  {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_TIMING:    {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_AGGRAVATE: {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_ASSOCIATED:{"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_TREATMENT: {"cat": "现病史", "colloquial": "就诊情况"},
    InterviewPhase.PMH_CHRONIC:   {"cat": "既往史", "colloquial": "健康状况"},
    InterviewPhase.PMH_SURGERY:   {"cat": "既往史", "colloquial": "健康状况"},
    InterviewPhase.PMH_INFECTION: {"cat": "既往史", "colloquial": "健康状况"},
    InterviewPhase.PMH_ALLERGY:   {"cat": "既往史", "colloquial": "过敏情况"},
    InterviewPhase.PS_LIFESTYLE:  {"cat": "个人史", "colloquial": "生活习惯"},
    InterviewPhase.PS_OCCUPATION: {"cat": "个人史", "colloquial": "工作生活"},
    InterviewPhase.PS_TRAVEL:     {"cat": "个人史", "colloquial": "出行情况"},
    InterviewPhase.FH_GENETIC:    {"cat": "家族史", "colloquial": "家人健康"},
    InterviewPhase.FH_SIMILAR:    {"cat": "家族史", "colloquial": "家人健康"},
    InterviewPhase.MED_CURRENT:   {"cat": "用药史", "colloquial": "用药情况"},
    InterviewPhase.MED_RECENT:    {"cat": "用药史", "colloquial": "用药情况"},
}


# Optional reference order for completeness checking (NOT a strict sequence)
PHASE_ORDER: list[InterviewPhase] = [
    InterviewPhase.HPI_ONSET,
    InterviewPhase.HPI_QUALITY,
    InterviewPhase.HPI_LOCATION,
    InterviewPhase.HPI_SEVERITY,
    InterviewPhase.HPI_TIMING,
    InterviewPhase.HPI_AGGRAVATE,
    InterviewPhase.HPI_ASSOCIATED,
    InterviewPhase.HPI_TREATMENT,
    InterviewPhase.PMH_CHRONIC,
    InterviewPhase.PMH_SURGERY,
    InterviewPhase.PMH_INFECTION,
    InterviewPhase.PMH_ALLERGY,
    InterviewPhase.PS_LIFESTYLE,
    InterviewPhase.PS_OCCUPATION,
    InterviewPhase.PS_TRAVEL,
    InterviewPhase.FH_GENETIC,
    InterviewPhase.FH_SIMILAR,
    InterviewPhase.MED_CURRENT,
    InterviewPhase.MED_RECENT,
]


# ---------------------------------------------------------------------------
# Differential Diagnosis Models
# ---------------------------------------------------------------------------

@dataclass
class DifferentialHypothesis:
    """A single differential diagnosis hypothesis maintained by the Agent."""

    diagnosis: str
    confidence: str = "low"  # high | medium | low
    key_features: list[str] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
    refuting_evidence: list[str] = field(default_factory=list)
    reason: str = ""  # Why this diagnosis is considered

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnosis": self.diagnosis,
            "confidence": self.confidence,
            "key_features": self.key_features,
            "supporting_evidence": self.supporting_evidence,
            "refuting_evidence": self.refuting_evidence,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DifferentialHypothesis":
        return cls(
            diagnosis=data.get("diagnosis", ""),
            confidence=data.get("confidence", "low"),
            key_features=data.get("key_features", []),
            supporting_evidence=data.get("supporting_evidence", []),
            refuting_evidence=data.get("refuting_evidence", []),
            reason=data.get("reason", ""),
        )


@dataclass
class QuestionTemplate:
    """A single interview question."""

    question_id: str
    question: str
    type: str  # "choice" or "text"
    options: list[str] = field(default_factory=list)
    hint: str = ""
    allow_skip: bool = True
    phase: str = ""
    colloquial_phase: str = ""


@dataclass
class InterviewState:
    """Snapshot of an ongoing interview stored in AgentSession.context."""

    chief_complaint: str = ""
    # Structured collected info keyed by phase ID
    collected_info: dict[str, Any] = field(default_factory=dict)
    # Natural language answers keyed by phase ID
    raw_answers: dict[str, str] = field(default_factory=dict)
    asked_questions: list[str] = field(default_factory=list)
    current_question_id: str | None = None
    is_sufficient: bool = False
    min_questions: int = 2           # Minimum before allowing completion
    current_phase_index: int = 0     # Kept for backward compat; not used as sequence constraint
    red_flags_detected: list[str] = field(default_factory=list)
    # Tool calls made during interview
    interview_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # Anti-loop: stagnation detection
    stagnation_counter: int = 0      # Consecutive rounds without new info
    last_collected_count: int = 0    # Info dimension count in last round
    fallback_count: int = 0         # Consecutive fallback uses (LLM failed)
    # User explicitly ended interview
    user_ended: bool = False
    # Interview phase tracking
    phase: str = "interviewing"      # interviewing | diagnosing | followup | completed

    # Internal keys for storing differential diagnosis info in collected_info (DB compatibility)
    _DIFF_KEY = "__differential_diagnoses__"
    _FEATURES_KEY = "__confirmed_features__"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chief_complaint": self.chief_complaint,
            "collected_info": self.collected_info,
            "raw_answers": self.raw_answers,
            "asked_questions": self.asked_questions,
            "current_question_id": self.current_question_id,
            "is_sufficient": self.is_sufficient,
            "min_questions": self.min_questions,
            "current_phase_index": self.current_phase_index,
            "red_flags_detected": self.red_flags_detected,
            "interview_tool_calls": self.interview_tool_calls,
            "stagnation_counter": self.stagnation_counter,
            "last_collected_count": self.last_collected_count,
            "fallback_count": self.fallback_count,
            "user_ended": self.user_ended,
            "phase": self.phase,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterviewState":
        return cls(
            chief_complaint=data.get("chief_complaint", ""),
            collected_info=data.get("collected_info", {}),
            raw_answers=data.get("raw_answers", {}),
            asked_questions=data.get("asked_questions", []),
            current_question_id=data.get("current_question_id"),
            is_sufficient=data.get("is_sufficient", False),
            min_questions=data.get("min_questions", 2),
            current_phase_index=data.get("current_phase_index", 0),
            red_flags_detected=data.get("red_flags_detected", []),
            interview_tool_calls=data.get("interview_tool_calls", []),
            stagnation_counter=data.get("stagnation_counter", 0),
            last_collected_count=data.get("last_collected_count", 0),
            fallback_count=data.get("fallback_count", 0),
            user_ended=data.get("user_ended", False),
            phase=data.get("phase", "interviewing"),
        )

    # ---- Differential diagnosis helpers (store in collected_info for compatibility) ----

    def get_differential_diagnoses(self) -> list[DifferentialHypothesis]:
        raw = self.collected_info.get(self._DIFF_KEY, [])
        if isinstance(raw, list):
            return [DifferentialHypothesis.from_dict(d) for d in raw]
        return []

    def set_differential_diagnoses(self, diffs: list[DifferentialHypothesis]) -> None:
        self.collected_info[self._DIFF_KEY] = [d.to_dict() for d in diffs]

    def get_confirmed_features(self) -> dict[str, Any]:
        return self.collected_info.get(self._FEATURES_KEY, {})

    def set_confirmed_features(self, features: dict[str, Any]) -> None:
        self.collected_info[self._FEATURES_KEY] = features

    def get_summary(self) -> str:
        """Generate a concise medical summary from collected info."""
        lines = [f"主诉: {self.chief_complaint}"]
        for phase_id in PHASE_ORDER:
            if phase_id.value in self.collected_info and not phase_id.value.startswith("__"):
                meta = PHASE_META.get(phase_id, {})
                cat = meta.get("cat", phase_id.value)
                val = self.collected_info[phase_id.value]
                if val and val not in ("无", "没有", "不清楚", "不记得"):
                    lines.append(f"  {cat} [{phase_id.value}]: {val}")
        # Add differential diagnoses summary
        diffs = self.get_differential_diagnoses()
        if diffs:
            lines.append("  鉴别诊断:")
            for d in diffs[:5]:
                flag = "✓" if d.confidence == "high" else "?" if d.confidence == "medium" else "×"
                lines.append(f"    {flag} {d.diagnosis} ({d.confidence})")
        if self.red_flags_detected:
            lines.append(f"  ⚠️ 危险信号: {', '.join(self.red_flags_detected)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM Output Schemas
# ---------------------------------------------------------------------------

class DifferentialDiagnosisEntry(BaseModel):
    """A single differential diagnosis entry in LLM output."""

    diagnosis: str = Field(..., description="疾病名称")
    confidence: str = Field(..., pattern="^(high|medium|low)$", description="当前置信度")
    key_features: list[str] = Field(default_factory=list, description="该诊断的关键鉴别特征")
    confirmed_features: list[str] = Field(default_factory=list, description="已确认的支持特征")
    missing_features: list[str] = Field(default_factory=list, description="尚未确认的关键特征")
    reason: str = Field(default="", description="为什么考虑这个诊断")


class NextQuestionSchema(BaseModel):
    """Schema for the next question generated by LLM."""

    question_id: str = Field(..., description="标准医学标识符，如 hpi_onset, pmh_chronic 等")
    question: str = Field(..., description="呈现给患者的口语化问题文本，通俗易懂")
    type: str = Field(..., pattern="^(choice|text)$", description="问题类型")
    options: list[str] = Field(default_factory=list, description="选择题选项（type=choice 时必填，至少2个）")
    hint: str = Field(default="", description="给患者的友好提示")
    allow_skip: bool = Field(default=True, description="是否允许跳过")
    reason: str = Field(default="", description="为什么问这个问题（内部reasoning）")


class InterviewDecision(BaseModel):
    """LLM output: mesh-architecture clinical decision.

    At each step, the Agent chooses one of three actions:
    - ask: generate a targeted question for the patient
    - search: request medical knowledge search (SeARXNG + RAG)
    - synthesize: sufficient info gathered, proceed to diagnosis
    """

    action: str = Field(default="ask", pattern="^(ask|search|synthesize)$", description="当前行动：ask | search | synthesize")
    differential_diagnoses: list[DifferentialDiagnosisEntry] = Field(
        default_factory=list,
        description="当前鉴别诊断列表，按可能性排序",
    )
    next_question: NextQuestionSchema | None = Field(
        default=None,
        description="下一个问题（action=ask 时必填）",
    )
    search_query: str = Field(
        default="",
        description="医学搜索查询（action=search 时必填），使用标准医学术语",
    )
    search_reason: str = Field(
        default="",
        description="为什么要搜索这个内容（action=search 时必填）",
    )
    reasoning: str = Field(default="", description="完整的临床决策思考过程")
    red_flags: list[str] = Field(default_factory=list, description="检测到的危险信号")
    covered_dimensions: list[str] = Field(
        default_factory=list,
        description="本次已覆盖的病史采集维度（如 现病史-起病情况、现病史-主要症状）",
    )


INTERVIEW_SYSTEM_PROMPT = """你是一位经验丰富的中国全科医生，正在通过网络为患者进行智能问诊。

## 你的核心能力：网状临床思维

你的工作不是一个线性的"问→答→问"循环，而是一个**网状结构的临床决策过程**：
- 你同时进行：问诊、医学知识搜索、鉴别诊断推理
- 问诊过程中可以随时触发搜索，搜索结果可能引导你追问新问题
- 最终将所有线索交织，生成诊断结论

## 病史采集框架（基本问诊模块）

这是中国执业医师资格考试的病史采集标准框架，作为你的参考指南：
1. **主诉** — 患者最主要的症状/体征 + 持续时间
2. **现病史** — 起病情况、主要症状特点（部位/性质/程度/时间）、伴随症状、病情演变、诊疗经过、一般情况
3. **既往史** — 慢性病史、手术外伤史、传染病史、过敏史
4. **个人史** — 烟酒习惯、职业暴露、疫区接触
5. **婚育史/家族史** — 遗传病、类似疾病
6. **用药史** — 当前用药、近期用药

注意：以上是完整框架，不是你每次都要问的问题清单。根据主诉灵活选择最关键的维度。

## 精细化问诊模块

在基本问诊基础上，根据鉴别诊断进行靶向深化：
- 对每个疑似疾病，确认其特异性关键特征
- 排除性提问（"有没有XX？"来排除某个诊断）
- 量化提问（"XX持续多久了？程度如何？"）
- 关联提问（"XX和YY有关系吗？"）

## 网状决策规则

每轮你必须选择三种 action 之一：

1. **action="ask"** — 当你需要从患者获取更多临床信息时
   - 基于当前鉴别诊断的信息缺口设计问题
   - 优先选择题（给2-5个口语化选项）
   - 问题要有诊断价值，不是泛泛的"还有什么补充"

2. **action="search"** — 当你需要查询医学知识来辅助判断时
   - 提供标准医学术语的搜索查询
   - 例如："儿童功能性便秘 鉴别诊断 临床指南"
   - 搜索结果会注入到下一轮的上下文中

3. **action="synthesize"** — 当信息足够进行初步诊断时
   - 仅在已覆盖≥2个现病史维度且已问≥2个问题时允许
   - 鉴别诊断的关键特征大部分已确认

## 输出格式

严格返回JSON（放在```json```代码块中）：

action="ask" 时：
```json
{
  "action": "ask",
  "differential_diagnoses": [{"diagnosis":"疾病","confidence":"high|medium|low","key_features":["特征"],"confirmed_features":["已确认"],"missing_features":["未确认"],"reason":"为什么"}],
  "next_question": {"question_id":"hpi_xxx","question":"口语化问题","type":"choice|text","options":["选项"],"hint":"提示","allow_skip":true,"reason":"为什么问"},
  "reasoning": "完整思考过程",
  "red_flags": [],
  "covered_dimensions": ["现病史-起病情况"]
}
```

action="search" 时：
```json
{
  "action": "search",
  "differential_diagnoses": [...],
  "search_query": "标准医学搜索查询",
  "search_reason": "为什么要搜索这个",
  "reasoning": "完整思考过程",
  "covered_dimensions": ["现病史-主要症状"]
}
```

action="synthesize" 时：
```json
{
  "action": "synthesize",
  "differential_diagnoses": [...],
  "reasoning": "为什么信息已经充足，可以进行诊断",
  "covered_dimensions": ["现病史-起病情况","现病史-主要症状","既往史"]
}
```

## 关键约束
- 必须严格返回JSON，不要有任何额外文本
- 口语化提问，用"您"开头，像真实医生在诊室
- 胸痛+大汗/呼吸困难/意识模糊/剧烈腹痛 → red_flags标记
- 已问过的问题ID不要重复
- reasoning 字段必须包含完整的鉴别诊断推理
- 无固定问题数量限制——你决定何时synthesize
"""


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

def _build_interview_prompt(
    state: InterviewState,
    patient_history: str | None = None,
    knowledge_context: str = "",
    tool_results: list[dict[str, Any]] | None = None,
) -> str:
    lines = []

    lines.append(f"## 患者主诉\n{state.chief_complaint or '未知'}")
    lines.append("")

    diffs = state.get_differential_diagnoses()
    if diffs:
        lines.append("## 当前鉴别诊断")
        for d in diffs:
            flag = "✓" if d.confidence == "high" else "?" if d.confidence == "medium" else "×"
            lines.append(f"  {flag} {d.diagnosis} ({d.confidence})")
            if d.supporting_evidence:
                lines.append(f"    支持证据: {', '.join(d.supporting_evidence)}")
            if d.refuting_evidence:
                lines.append(f"    排除证据: {', '.join(d.refuting_evidence)}")
        lines.append("")

    if state.collected_info:
        lines.append("## 已收集信息")
        for phase_id in PHASE_ORDER:
            if phase_id.value in state.collected_info and not phase_id.value.startswith("__"):
                meta = PHASE_META.get(phase_id, {})
                cat = meta.get("cat", phase_id.value)
                val = state.collected_info[phase_id.value]
                raw = state.raw_answers.get(phase_id.value, "")
                lines.append(f"  [{cat}] {phase_id.value}: {val}")
                if raw and raw != str(val):
                    lines.append(f"    原话: {raw}")
        lines.append("")

    if knowledge_context:
        lines.append("## 医学知识搜索结果（已通过RAG+SearXNG实时获取）")
        lines.append(knowledge_context[:800])
        lines.append("")
    elif tool_results:
        lines.append("## 工具查询结果")
        for tr in tool_results:
            r = tr.get('result', {})
            if isinstance(r, dict):
                lines.append(f"  {tr.get('tool','?')}: {json.dumps(r, ensure_ascii=False)[:300]}")
        lines.append("")

    if patient_history:
        lines.append(f"## 既往病史\n{patient_history}")
        lines.append("")

    lines.append(f"## 统计\n已问 {len(state.asked_questions)} 个问题")
    if state.asked_questions:
        lines.append(f"已问ID: {', '.join(state.asked_questions[-8:])}")
    pending = [p.value for p in PHASE_ORDER if p.value not in state.collected_info and not p.value.startswith("__")]
    if pending:
        lines.append(f"未覆盖维度: {', '.join(pending[:6])}")
    lines.append("")

    if state.red_flags_detected:
        lines.append(f"⚠️ 危险信号: {', '.join(state.red_flags_detected)}")

    lines.append("## 请决定下一步行动 (ask / search / synthesize)")
    if len(state.asked_questions) < state.min_questions:
        lines.append("尚未达到最少问诊数，请继续ask")
    elif state.stagnation_counter >= 3:
        lines.append(f"已连续 {state.stagnation_counter} 轮无新信息，考虑synthesize")
    lines.append("search适用于：需要查指南/药物/论文来辅助判断时")
    lines.append("synthesize适用于：鉴别诊断关键特征已大部分确认")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON Extraction Helper
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any]:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    text = text.strip()
    if "```json" in text:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    elif "```" in text:
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Dynamic Interview Engine — Differential-Diagnosis-Driven
# ---------------------------------------------------------------------------

class DynamicInterviewEngine:

    def __init__(self, llm_service: Any, search_executor: Any = None) -> None:
        self.llm = llm_service
        self.search = search_executor

    async def decide_next(
        self,
        state: InterviewState,
        patient_history: str | None = None,
        knowledge_context: str = "",
        tool_results: list[dict[str, Any]] | None = None,
    ) -> tuple[QuestionTemplate | None, InterviewState, str, str]:
        prompt = _build_interview_prompt(state, patient_history, knowledge_context, tool_results)
        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=INTERVIEW_SYSTEM_PROMPT,
                max_tokens=2000,
            )
            raw = _extract_json(response.content)
            decision = InterviewDecision.model_validate(raw)

            if decision.red_flags:
                state.red_flags_detected.extend(decision.red_flags)
                state.is_sufficient = True
                return None, state, "", ""

            if decision.differential_diagnoses:
                diffs = [DifferentialHypothesis(diagnosis=d.diagnosis, confidence=d.confidence, key_features=d.key_features, supporting_evidence=d.confirmed_features, refuting_evidence=[], reason=d.reason) for d in decision.differential_diagnoses]
                state.set_differential_diagnoses(diffs)

            meaningful = [k for k, v in state.collected_info.items() if not k.startswith("__") and v not in ("无", "没有", "不清楚", "不记得", "跳过", "skipped", "")]
            current = len(meaningful)
            if current <= state.last_collected_count:
                state.stagnation_counter += 1
            else:
                state.stagnation_counter = 0
            state.last_collected_count = current

            if state.stagnation_counter >= 8 and len(state.asked_questions) >= state.min_questions:
                state.is_sufficient = True
                return None, state, "", ""

            if decision.action == "synthesize":
                if len(state.asked_questions) >= state.min_questions:
                    state.is_sufficient = True
                    return None, state, "", ""
                decision.action = "ask"

            if decision.action == "search" and decision.search_query and self.search:
                search_query = decision.search_query
                search_reason = decision.search_reason
                return None, state, search_query, search_reason

            if decision.next_question:
                q = decision.next_question
                if q.question_id in state.asked_questions:
                    q.question_id = f"{q.question_id}_{len(state.asked_questions)}"
                question = QuestionTemplate(question_id=q.question_id, question=q.question, type=q.type, options=q.options if q.type == "choice" else [], hint=q.hint, allow_skip=q.allow_skip, phase=q.question_id, colloquial_phase="问诊")
                state.current_question_id = question.question_id
                state.fallback_count = 0
                return question, state, "", ""

            state.fallback_count += 1
            if state.fallback_count >= 2:
                state.is_sufficient = True
                return None, state, "", ""
            return None, state, "", ""
        except Exception:
            state.fallback_count += 1
            if state.fallback_count >= 2 or len(state.asked_questions) >= 5:
                state.is_sufficient = True
            return None, state, "", ""

    async def process_answer(
        self,
        state: InterviewState,
        question_id: str,
        answer: str,
    ) -> InterviewState:
        """Process a patient's answer and extract structured info + update differential diagnoses.

        Uses LLM to:
        1. Extract structured medical information from natural language
        2. Update the differential diagnosis list based on new information
        """
        state.raw_answers[question_id] = answer
        state.asked_questions.append(question_id)

        if answer.lower() in ("跳过", "skipped", "不清楚", "不记得"):
            state.collected_info[question_id] = answer
            return state

        # Use LLM to extract structured info AND update differential diagnoses
        diffs = state.get_differential_diagnoses()
        diffs_json = json.dumps([d.to_dict() for d in diffs], ensure_ascii=False) if diffs else "[]"

        extract_prompt = f"""患者对问题"{question_id}"的回答是："{answer}"

当前鉴别诊断列表：{diffs_json}

请完成以下任务，返回 JSON：

1. 从患者回答中提取结构化的医学信息
2. 根据新信息，更新每个鉴别诊断的 confirmed_features 和 missing_features
3. 如果有新的鉴别诊断需要加入，或某个诊断可以被排除，请说明

返回格式：
{{
  "extracted": "提取的关键医学信息（简洁准确）",
  "category": "所属的临床维度",
  "differential_updates": [
    {{
      "diagnosis": "疾病名称",
      "action": "confirm|refute|add|remove",
      "feature": "被确认或排除的特征",
      "reason": "为什么"
    }}
  ],
  "new_differential_diagnoses": [
    {{
      "diagnosis": "新诊断名称",
      "confidence": "high|medium|low",
      "key_features": ["特征1", "特征2"],
      "reason": "为什么新考虑这个诊断"
    }}
  ]
}}

如果患者回答"没有""无"等，extracted 填"无"，differential_updates 为空。
如果信息不明确，extracted 填患者原话。"""

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": extract_prompt}],
                system_prompt="你是医学信息提取和鉴别诊断更新助手。从患者回答中提取信息并更新鉴别诊断列表。只返回JSON。",
                max_tokens=1024,
            )
            raw = _extract_json(response.content)
            extracted = raw.get("extracted", answer)
            state.collected_info[question_id] = extracted

            # Update confirmed features
            features = state.get_confirmed_features()
            features[question_id] = extracted
            state.set_confirmed_features(features)

            # Update differential diagnoses based on differential_updates
            diff_updates = raw.get("differential_updates", [])
            new_diagnoses = raw.get("new_differential_diagnoses", [])

            existing_diagnoses = {d.diagnosis: d for d in diffs}

            for update in diff_updates:
                diag_name = update.get("diagnosis", "")
                action = update.get("action", "")
                feature = update.get("feature", "")

                if diag_name not in existing_diagnoses:
                    continue

                d = existing_diagnoses[diag_name]
                if action == "confirm" and feature:
                    if feature not in d.supporting_evidence:
                        d.supporting_evidence.append(feature)
                elif action == "refute" and feature:
                    if feature not in d.refuting_evidence:
                        d.refuting_evidence.append(feature)

            # Add new diagnoses
            for new in new_diagnoses:
                diag_name = new.get("diagnosis", "")
                if diag_name and diag_name not in existing_diagnoses:
                    diffs.append(DifferentialHypothesis(
                        diagnosis=diag_name,
                        confidence=new.get("confidence", "low"),
                        key_features=new.get("key_features", []),
                        supporting_evidence=[],
                        refuting_evidence=[],
                        reason=new.get("reason", ""),
                    ))

            state.set_differential_diagnoses(diffs)

        except Exception:
            # Fallback: store raw answer
            state.collected_info[question_id] = answer
            features = state.get_confirmed_features()
            features[question_id] = answer
            state.set_confirmed_features(features)

        return state

    def _fallback_question(self, state: InterviewState) -> QuestionTemplate | None:
        state.fallback_count += 1
        if state.fallback_count >= 2:
            state.is_sufficient = True
            return None

        summary = state.get_summary()
        return QuestionTemplate(
            question_id="fallback_wrapup",
            question=f"我已经了解了以下情况：\n\n{summary[:200]}\n\n能否再补充一些我刚才没问到的、但您觉得重要的信息？",
            type="text",
            hint="没有的话可以直接说'没有了'",
            allow_skip=True,
            phase="complete",
            colloquial_phase="总结确认",
        )


