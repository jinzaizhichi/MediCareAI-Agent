"""Medical Interview (multi-turn questioning) models — Clinical Standard Edition.

LLM-driven dynamic interview engine with standard Chinese clinical intake framework.

DESIGN PRINCIPLES:
1. Backend tracks clinical dimensions using standard medical terminology (HPI, PMH, etc.)
2. Questions presented to patients are colloquial and easy to understand
3. Patient answers are natural language; LLM extracts structured medical info
4. Tool calls (patient history lookup, knowledge search) can happen DURING interview
5. Red flags detected at any phase trigger immediate escalation
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum as PyEnum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Interview Phase Definitions (standard clinical framework)
# ---------------------------------------------------------------------------

class InterviewPhase(str, PyEnum):
    """Standard clinical interview phases, in order."""

    # Phase 1: Chief Complaint & Present Illness (现病史)
    HPI_ONSET = "hpi_onset"           # 起病情况
    HPI_QUALITY = "hpi_quality"       # 症状性质
    HPI_LOCATION = "hpi_location"     # 部位/放射
    HPI_SEVERITY = "hpi_severity"     # 严重程度
    HPI_TIMING = "hpi_timing"         # 时间特点
    HPI_AGGRAVATE = "hpi_aggravate"   # 诱发/缓解因素
    HPI_ASSOCIATED = "hpi_associated" # 伴随症状
    HPI_TREATMENT = "hpi_treatment"   # 诊治经过

    # Phase 2: Past Medical History (既往史)
    PMH_CHRONIC = "pmh_chronic"       # 慢性疾病
    PMH_SURGERY = "pmh_surgery"       # 手术外伤
    PMH_INFECTION = "pmh_infection"   # 传染病
    PMH_ALLERGY = "pmh_allergy"       # 过敏史

    # Phase 3: Personal History (个人史)
    PS_LIFESTYLE = "ps_lifestyle"     # 吸烟饮酒
    PS_OCCUPATION = "ps_occupation"   # 职业暴露
    PS_TRAVEL = "ps_travel"           # 旅居史

    # Phase 4: Family History (家族史)
    FH_GENETIC = "fh_genetic"         # 遗传病
    FH_SIMILAR = "fh_similar"         # 类似疾病

    # Phase 5: Medication History (用药史)
    MED_CURRENT = "med_current"       # 当前用药
    MED_RECENT = "med_recent"         # 近期用药

    # Terminal phase
    COMPLETE = "complete"


# Ordered phases for progressive interview
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


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class QuestionTemplate:
    """A single interview question."""

    question_id: str        # e.g. "hpi_onset" (medical identifier)
    question: str           # Colloquial text shown to patient
    type: str               # "choice" or "text"
    options: list[str] = field(default_factory=list)
    hint: str = ""          # Helpful hint for patient
    allow_skip: bool = True
    phase: str = ""         # Clinical phase for tracking
    colloquial_phase: str = ""  # Friendly phase name


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
    max_questions: int = 12          # Soft upper limit
    min_questions: int = 3           # Minimum before allowing completion
    current_phase_index: int = 0     # Index into PHASE_ORDER
    red_flags_detected: list[str] = field(default_factory=list)
    # Tool calls made during interview
    interview_tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chief_complaint": self.chief_complaint,
            "collected_info": self.collected_info,
            "raw_answers": self.raw_answers,
            "asked_questions": self.asked_questions,
            "current_question_id": self.current_question_id,
            "is_sufficient": self.is_sufficient,
            "max_questions": self.max_questions,
            "min_questions": self.min_questions,
            "current_phase_index": self.current_phase_index,
            "red_flags_detected": self.red_flags_detected,
            "interview_tool_calls": self.interview_tool_calls,
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
            max_questions=data.get("max_questions", 12),
            min_questions=data.get("min_questions", 3),
            current_phase_index=data.get("current_phase_index", 0),
            red_flags_detected=data.get("red_flags_detected", []),
            interview_tool_calls=data.get("interview_tool_calls", []),
        )

    def get_summary(self) -> str:
        """Generate a concise medical summary from collected info."""
        lines = [f"主诉: {self.chief_complaint}"]
        for phase_id in PHASE_ORDER:
            if phase_id.value in self.collected_info:
                meta = PHASE_META.get(phase_id, {})
                cat = meta.get("cat", phase_id.value)
                val = self.collected_info[phase_id.value]
                if val and val not in ("无", "没有", "不清楚", "不记得"):
                    lines.append(f"  {cat} [{phase_id.value}]: {val}")
        if self.red_flags_detected:
            lines.append(f"  ⚠️ 危险信号: {', '.join(self.red_flags_detected)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM Output Schemas
# ---------------------------------------------------------------------------

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
    """LLM output: whether we have enough info and what to ask next."""

    sufficient: bool = Field(..., description="是否已收集足够信息进行初步诊断")
    next_question: NextQuestionSchema | None = Field(default=None, description="下一个问题（sufficient=false 时必填）")
    reasoning: str = Field(default="", description="问诊决策的简要说明")
    red_flags: list[str] = Field(default_factory=list, description="检测到的危险信号，如有则应立即建议就医")
    suggested_tools: list[str] = Field(default_factory=list, description="建议调用的工具，如 query_patient_history, search_medical_knowledge")


# ---------------------------------------------------------------------------
# System Prompt for Clinical Interview
# ---------------------------------------------------------------------------

INTERVIEW_SYSTEM_PROMPT = """你是一位经验丰富的全科医生，正在通过对话为患者进行智能问诊。

## 核心原则
1. **针对性提问**：每个问题都必须直接针对患者主诉中的具体症状，不能笼统地问"还有什么"。要像真实医生一样追问关键细节。
2. **口语化表达**：呈现给患者的问题必须通俗易懂，像日常对话一样自然
3. **动态编排**：根据主诉中的症状组合，自己判断当前最需要确认什么信息来鉴别诊断
4. **危险信号优先**：如果患者回答中暗示急危重症，立即终止问诊并建议紧急就医

## 问诊策略（你必须遵循的思考过程）

每次生成问题前，请先分析：
1. 患者主诉中包含哪些症状？
2. 这些症状组合可能指向哪些疾病？
3. 为了鉴别这些疾病，我现在最需要确认什么关键信息？
4. 设计一个直接获取这个信息的问题

### 示例（你必须学习这种提问方式）

**例1：主诉"头疼还发烧"**
- 分析：头疼+发烧常见于流感、上呼吸道感染、脑膜炎等
- 鉴别关键：体温高低、头疼性质、有无脑膜刺激征
- 第一个问题："您量过体温吗？最高大概多少度？"（获取发热程度）
- 第二个问题："头疼是胀痛、刺痛还是一跳一跳地疼？"（鉴别血管性/神经性）
- 第三个问题："脖子转动时疼不疼？有没有恶心呕吐？"（排除脑膜炎）

**例2：主诉"肚子疼，拉稀三天了"**
- 分析：腹痛+腹泻常见于肠胃炎、食物中毒等
- 鉴别关键：大便性状、腹痛位置、有无发热
- 第一个问题："大便是什么样的？稀水样还是像鼻涕一样有黏液？"（鉴别感染类型）
- 第二个问题："肚子疼主要是哪个位置？上腹部还是肚脐周围？"（定位病变）

**例3：主诉"胸闷气短，爬楼特别明显"**
- 分析：活动后胸闷气短可能指向心功能不全、贫血、肺部疾病
- 鉴别关键：发作诱因、缓解方式、伴随症状
- 第一个问题："休息一会儿能缓解吗？还是一直闷？"（鉴别心源性/肺源性）

## 问诊框架（参考，不要机械套用）

### 现病史（围绕主诉深入追问）
- 起病：什么时候开始的？突然还是逐渐？
- 性质：具体是什么感觉？（如胀痛/刺痛/搏动痛/绞痛）
- 部位：哪里不舒服？会不会传到其他部位？
- 程度：影响日常生活吗？1-10分有多难受？
- 时间规律：持续存在还是时好时坏？白天重还是晚上重？
- 诱因：什么情况下加重或减轻？
- 伴随症状：还有其他不舒服吗？
- 诊疗经过：之前看过医生吗？做过什么检查？吃过什么药？

### 既往史/个人史/家族史/用药史（在现病史问清楚后再简短询问）

## 输出格式
请严格返回 JSON，不要有任何额外文本。格式如下：
```json
{
  "sufficient": false,
  "next_question": {
    "question_id": "标准医学标识符",
    "question": "口语化、通俗易懂的问题文本（患者能看懂的）",
    "type": "choice 或 text",
    "options": ["选项1", "选项2"],
    "hint": "给患者的友好提示",
    "allow_skip": true,
    "reason": "内部reasoning：为什么问这个问题"
  },
  "reasoning": "问诊决策说明",
  "red_flags": [],
  "suggested_tools": []
}
```

## 绝对禁止
- ❌ "关于您的症状情况，还有什么需要补充的吗？" —— 这种笼统问题没有任何信息量
- ❌ "还有什么不舒服吗？" —— 太宽泛，患者不知道回答什么
- ❌ 连续问两个不相关的问题 —— 每次只问一个最关键的问题
- ❌ 使用"现病史""既往史"等医学术语面向患者提问

## 规则
- sufficient=true 时，next_question 必须为 null
- type="choice" 时，options 必须至少有 2 个选项，选项也要口语化
- type="text" 时，options 应为空数组 []
- 问题必须口语化、自然，用"您"开头，像医生在诊室里问话
- 如果患者提到胸痛+大汗、呼吸困难、意识模糊、剧烈腹痛等，red_flags 要标记
- suggested_tools 可在需要查病史或搜资料时填写："query_patient_history" 或 "search_medical_knowledge"
- 已问过的问题（见已收集信息中的 key）不要再重复问
- 优先问现病史细节，现病史问清楚后再简短问既往史/用药史

## 关键规则（必须严格遵守）
- sufficient=true 时，next_question 必须为 null
- **sufficient=false 时，next_question 必须不为 null，必须提供一个具体的下一个问题**
- 如果当前不满足 sufficient=true 的条件（覆盖 <5 个现病史维度 或 问 <5 个问题），你必须设置 sufficient=false 并提供一个 next_question
- 绝不要在不满足条件时返回 sufficient=true 和 next_question=null
"""


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

def _build_interview_prompt(
    state: InterviewState,
    patient_history: str | None = None,
    tool_results: list[dict[str, Any]] | None = None,
) -> str:
    """Build the user prompt for LLM interview decision."""
    lines = []

    # 【主诉分析】——这是最关键的部分，引导 LLM 针对性问诊
    lines.append(f"## 患者主诉\n{state.chief_complaint or '未知'}")
    lines.append("")

    # 根据主诉内容给出问诊策略提示
    chief = state.chief_complaint or ""
    if chief:
        lines.append("## 问诊策略提示")
        lines.append("请先分析主诉中的关键症状，然后设计最有针对性的问题。")
        lines.append("不要笼统地问‘还有什么补充的’，要像真实医生一样追问具体细节。")
        lines.append("")

    # Show collected info in a structured way
    if state.collected_info:
        lines.append("## 已收集的问诊信息")
        for phase_id in PHASE_ORDER:
            if phase_id.value in state.collected_info:
                meta = PHASE_META.get(phase_id, {})
                cat = meta.get("cat", phase_id.value)
                val = state.collected_info[phase_id.value]
                raw = state.raw_answers.get(phase_id.value, "")
                lines.append(f"  [{cat}] {phase_id.value}: {val}")
                if raw and raw != str(val):
                    lines.append(f"    患者原话: {raw}")
        lines.append("")

    # Show tool results if any
    if tool_results:
        lines.append("## 工具查询结果")
        for tr in tool_results:
            lines.append(f"  工具: {tr.get('tool', 'unknown')}")
            result = tr.get('result', {})
            if isinstance(result, dict):
                lines.append(f"  结果: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
            else:
                lines.append(f"  结果: {str(result)[:500]}")
        lines.append("")

    # Show patient history context if available
    if patient_history:
        lines.append(f"## 患者既往病史\n{patient_history}\n")

    lines.append(f"已问 {len(state.asked_questions)} 个问题，最少 {state.min_questions} 个，最多 {state.max_questions} 个。")
    if state.asked_questions:
        lines.append(f"已问问题 ID: {', '.join(state.asked_questions)}")
    lines.append("")

    # Determine which phases are still pending
    pending = [p.value for p in PHASE_ORDER if p.value not in state.collected_info]
    if pending:
        lines.append(f"尚未覆盖的维度: {', '.join(pending[:5])}")
    else:
        lines.append("已覆盖全部问诊维度。")
    lines.append("")

    # Red flags guidance
    if state.red_flags_detected:
        lines.append(f"⚠️ 已检测到的危险信号: {', '.join(state.red_flags_detected)}")
        lines.append("如果新信息中有更多危险信号，请在 red_flags 中标注。")
    else:
        lines.append("目前未检测到明显危险信号。")
    lines.append("")

    # Decision prompt
    if len(state.asked_questions) < state.min_questions:
        lines.append("尚未达到最少问诊数量，请继续提问。")
        lines.append("提示：根据主诉中的关键症状，问出能帮助鉴别诊断的具体问题。")
    elif len(state.asked_questions) >= state.max_questions:
        lines.append("已达到最大问诊数量上限，请判定信息是否足够进行初步诊断。")
    else:
        # Critical: enforce minimum clinical coverage before allowing sufficient=true
        hpi_phases = [p.value for p in PHASE_ORDER[:8]]  # HPI phases
        hpi_covered = sum(1 for p in hpi_phases if p in state.collected_info)
        lines.append(f"已覆盖的现病史维度: {hpi_covered}/8 (起病、性质、部位、程度、时间、诱因、伴随症状、诊疗经过)")
        if hpi_covered < 5:
            lines.append("现病史信息还不足，请继续追问具体细节。不要判定为 sufficient。")
            lines.append("目标：至少覆盖5个现病史维度后，才能考虑结束问诊。")
        else:
            lines.append("现病史维度已较充分。如果还有未覆盖的关键维度，可以继续追问；否则可以判定 sufficient。")
        lines.append("")
        lines.append("规则：sufficient=true 仅在以下情况允许：")
        lines.append("  - 已覆盖 ≥5 个现病史维度，且已问 ≥5 个问题；或")
        lines.append("  - 已达到 max_questions 上限。")

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
# Dynamic Interview Engine
# ---------------------------------------------------------------------------

class DynamicInterviewEngine:
    """Uses LLM to decide what to ask next based on patient context.

    The engine follows a clinical framework but presents questions colloquially.
    It can also suggest tool calls during the interview (e.g. look up patient
    history, search for differential diagnoses).
    """

    def __init__(self, llm_service: Any) -> None:
        self.llm = llm_service

    async def decide_next(
        self,
        state: InterviewState,
        patient_history: str | None = None,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> tuple[QuestionTemplate | None, InterviewState, list[str]]:
        """Ask LLM to decide the next question or if we have enough info.

        Returns:
            (next_question, updated_state, suggested_tools) —
            next_question is None if sufficient or red flags detected.
            suggested_tools is a list of tool names to call before next question.
        """
        prompt = _build_interview_prompt(state, patient_history, tool_results)

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=INTERVIEW_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=1200,
            )

            raw = _extract_json(response.content)
            decision = InterviewDecision.model_validate(raw)

            # Handle red flags immediately
            if decision.red_flags:
                state.red_flags_detected.extend(decision.red_flags)
                state.is_sufficient = True
                state.current_question_id = None
                return None, state, []

            # Check if sufficient — enforce minimum clinical coverage
            if decision.sufficient or len(state.asked_questions) >= state.max_questions:
                hpi_phases = [p.value for p in PHASE_ORDER[:8]]
                hpi_covered = sum(1 for p in hpi_phases if p in state.collected_info)
                # Require at least 5 HPI dimensions AND at least 5 questions
                if hpi_covered >= 5 and len(state.asked_questions) >= 5:
                    state.is_sufficient = True
                    state.current_question_id = None
                    return None, state, []
                elif len(state.asked_questions) >= state.max_questions:
                    # Hard limit reached
                    state.is_sufficient = True
                    state.current_question_id = None
                    return None, state, []
                else:
                    # Override LLM's premature sufficient judgment
                    decision.sufficient = False

            if decision.next_question is None:
                # LLM says not sufficient but gave no question — fallback
                # CRITICAL: Only end interview if max_questions reached or hpi_covered >= 5
                hpi_phases = [p.value for p in PHASE_ORDER[:8]]
                hpi_covered = sum(1 for p in hpi_phases if p in state.collected_info)
                if len(state.asked_questions) >= state.max_questions or (hpi_covered >= 5 and len(state.asked_questions) >= 5):
                    state.is_sufficient = True
                    state.current_question_id = None
                    return None, state, []
                # Generate a targeted fallback question
                return self._fallback_question(state), state, []

            q = decision.next_question
            # Validate: don't repeat asked questions
            if q.question_id in state.asked_questions:
                q.question_id = f"{q.question_id}_{len(state.asked_questions)}"

            # Update phase tracking
            phase = InterviewPhase(q.question_id) if q.question_id in [p.value for p in PHASE_ORDER] else None
            if phase:
                # Advance phase index to at least this phase
                idx = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else state.current_phase_index
                state.current_phase_index = max(state.current_phase_index, idx)

            meta = PHASE_META.get(phase, {}) if phase else {}

            question = QuestionTemplate(
                question_id=q.question_id,
                question=q.question,
                type=q.type,
                options=q.options if q.type == "choice" else [],
                hint=q.hint,
                allow_skip=q.allow_skip,
                phase=q.question_id,
                colloquial_phase=meta.get("colloquial", ""),
            )

            state.current_question_id = question.question_id
            return question, state, decision.suggested_tools or []

        except Exception as exc:
            # LLM failed — fallback
            # CRITICAL: Don't end interview just because LLM failed
            # Only end if max_questions reached or sufficient HPI coverage
            hpi_phases = [p.value for p in PHASE_ORDER[:8]]
            hpi_covered = sum(1 for p in hpi_phases if p in state.collected_info)
            if len(state.asked_questions) >= state.max_questions or (hpi_covered >= 5 and len(state.asked_questions) >= 5):
                state.is_sufficient = True
                state.current_question_id = None
                return None, state, []

            return self._fallback_question(state), state, []

    def _fallback_question(self, state: InterviewState) -> QuestionTemplate:
        """Generate a targeted fallback question based on chief complaint when LLM fails."""
        chief = state.chief_complaint or ""

        # Try to infer the most relevant question from chief complaint keywords
        chief_lower = chief.lower()

        # Fever-related
        if any(k in chief_lower for k in ("发烧", "发热", "热", "高烧", "低烧", "退烧")):
            # Check if we already have temperature info (by question_id or collected key)
            temp_already_asked = any(
                q in state.asked_questions or q in state.collected_info
                for q in ("hpi_severity", "体温", "温度")
            )
            if not temp_already_asked:
                return QuestionTemplate(
                    question_id="hpi_severity",
                    question="您量过体温吗？最高大概多少度？",
                    type="text",
                    hint="比如 38.5°C 之类的具体数值",
                    allow_skip=True,
                    phase="hpi_severity",
                    colloquial_phase="症状情况",
                )
            # If temp asked, check headache character for fever+headache combo
            if any(k in chief_lower for k in ("头疼", "头痛", "头晕")):
                headache_already_asked = any(
                    q in state.asked_questions or q in state.collected_info
                    for q in ("hpi_character", "头痛性质", "疼痛性质")
                )
                if not headache_already_asked:
                    return QuestionTemplate(
                        question_id="hpi_character",
                        question="头疼是怎么个疼法？胀痛、刺痛、还是一跳一跳地疼？",
                        type="choice",
                        options=["胀痛或压痛", "刺痛或针扎痛", "一跳一跳的搏动痛", "绞痛或紧箍痛", "说不清楚"],
                        hint="这有助于判断原因",
                        allow_skip=True,
                        phase="hpi_character",
                        colloquial_phase="症状情况",
                    )

        # Headache-specific (without fever)
        elif any(k in chief_lower for k in ("头疼", "头痛", "头晕")):
            location_already_asked = any(
                q in state.asked_questions or q in state.collected_info
                for q in ("hpi_location", "部位", "头疼部位")
            )
            if not location_already_asked:
                return QuestionTemplate(
                    question_id="hpi_location",
                    question="头疼主要在哪个位置？前额、后脑勺、两侧还是整个头？",
                    type="text",
                    hint="请描述具体位置",
                    allow_skip=True,
                    phase="hpi_location",
                    colloquial_phase="症状情况",
                )

        # Abdominal pain / diarrhea
        elif any(k in chief_lower for k in ("肚子疼", "腹痛", "肚疼", "拉肠子", "腹泻", "拉稀", "腹泻")):
            stool_already_asked = any(
                q in state.asked_questions or q in state.collected_info
                for q in ("hpi_character", "大便性状", "大便")
            )
            if not stool_already_asked:
                return QuestionTemplate(
                    question_id="hpi_character",
                    question="大便是什么样的？稀水样、有黏液、还是像豆腚渣？",
                    type="text",
                    hint="这能帮助判断是哪种感染",
                    allow_skip=True,
                    phase="hpi_character",
                    colloquial_phase="症状情况",
                )

        # Cough / respiratory
        elif any(k in chief_lower for k in ("咳嗽", "咳", "胸闷", "气短", "呼吸", "咳痰")):
            sputum_already_asked = any(
                q in state.asked_questions or q in state.collected_info
                for q in ("hpi_character", "嗟嚏性质", "嗟嗽", "痰")
            )
            if not sputum_already_asked:
                return QuestionTemplate(
                    question_id="hpi_character",
                    question="咳嗽有痰吗？是白色的痰还是黄色的？",
                    type="choice",
                    options=["没有痰，干咳", "白色痰", "黄色或绿色痰", "带血丝的痰", "说不清楚"],
                    hint="痰的颜色能提供很多信息",
                    allow_skip=True,
                    phase="hpi_character",
                    colloquial_phase="症状情况",
                )

        # Chest pain / cardiac
        elif any(k in chief_lower for k in ("胸痛", "胸闷", "心绞痛", "心慌", "心疼")):
            chest_pain_already_asked = any(
                q in state.asked_questions or q in state.collected_info
                for q in ("hpi_character", "胸痛性质", "胸痛")
            )
            if not chest_pain_already_asked:
                return QuestionTemplate(
                    question_id="hpi_character",
                    question="胸痛是怎么疼的？压迫感、针刺感、还是烧灼感？",
                    type="choice",
                    options=["压着疼或窄着疼", "针扎样刺痛", "烧灼感", "一阵一阵的绞痛", "说不清楚"],
                    hint="性质很重要",
                    allow_skip=True,
                    phase="hpi_character",
                    colloquial_phase="症状情况",
                )

        # Default: ask about onset if nothing else fits
        if "起病时间" not in state.asked_questions and "hpi_onset" not in state.asked_questions:
            return QuestionTemplate(
                question_id="hpi_onset",
                question="这个不舒服是什么时候开始的？突然出现还是慢慢加重的？",
                type="text",
                hint="请告诉我大约什么时候开始的",
                allow_skip=True,
                phase="hpi_onset",
                colloquial_phase="症状情况",
            )

        # If we've asked about onset but nothing else, ask severity
        if "严重程度" not in state.asked_questions and "hpi_severity" not in state.asked_questions:
            return QuestionTemplate(
                question_id="hpi_severity",
                question="现在这种不舒服影响您正常活动吗？比如上班、吃饭、睡觉？",
                type="text",
                hint="请描述对您日常生活的影响",
                allow_skip=True,
                phase="hpi_severity",
                colloquial_phase="症状情况",
            )

        # Find first unasked standard phase
        for phase in PHASE_ORDER[state.current_phase_index:]:
            if phase.value not in state.collected_info:
                meta = PHASE_META.get(phase, {})
                return QuestionTemplate(
                    question_id=phase.value,
                    question=f"关于您的{meta.get('colloquial', '情况')}，您能简单说说吗？",
                    type="text",
                    hint="可以简单描述，也可以跳过",
                    allow_skip=True,
                    phase=phase.value,
                    colloquial_phase=meta.get("colloquial", ""),
                )

        # Everything covered
        return QuestionTemplate(
            question_id=f"fallback_{len(state.asked_questions)}",
            question="还有其他您觉得医生需要知道的情况吗？",
            type="text",
            hint="任何您觉得和这次不适有关的情况都可以说",
            allow_skip=True,
            phase="complete",
            colloquial_phase="补充",
        )

    async def process_answer(
        self,
        state: InterviewState,
        question_id: str,
        answer: str,
    ) -> InterviewState:
        """Process a patient's answer and extract structured info.

        Uses LLM to extract structured medical information from natural language.
        """
        state.raw_answers[question_id] = answer
        state.asked_questions.append(question_id)

        if answer.lower() in ("跳过", "skipped", "不清楚", "不记得"):
            state.collected_info[question_id] = answer
            return state

        # Use LLM to extract structured info
        extract_prompt = f"""患者对问题"{question_id}"的回答是："{answer}"

请从中提取结构化的医学信息。返回 JSON：
{{
  "extracted": "提取的关键医学信息（简洁准确）",
  "category": "所属的临床维度"
}}

如果患者回答"没有""无"等，extracted 填"无"。
如果信息不明确，extracted 填患者原话。"""

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": extract_prompt}],
                system_prompt="你是医学信息提取助手。从患者自然语言回答中提取结构化医学信息。只返回JSON。",
                temperature=0.1,
                max_tokens=256,
            )
            raw = _extract_json(response.content)
            extracted = raw.get("extracted", answer)
            state.collected_info[question_id] = extracted
        except Exception:
            # Fallback: store raw answer
            state.collected_info[question_id] = answer

        return state
