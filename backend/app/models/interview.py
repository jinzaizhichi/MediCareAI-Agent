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
import logging
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
    PS_GENERAL = "ps_general"

    # Special Populations
    PS_CHILD = "ps_child"
    PS_FEMALE = "ps_female"

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
    InterviewPhase.PS_GENERAL:    {"cat": "个人史", "colloquial": "一般情况"},
    InterviewPhase.PS_CHILD:      {"cat": "个人史", "colloquial": "儿童发育"},
    InterviewPhase.PS_FEMALE:     {"cat": "个人史", "colloquial": "女性健康"},
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
    InterviewPhase.PS_GENERAL,
    InterviewPhase.PS_CHILD,
    InterviewPhase.PS_FEMALE,
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
    min_questions: int = 4           # Minimum before allowing completion
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
            min_questions=data.get("min_questions", 4),
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


class BasicQuestion(BaseModel):
    question_id: str = Field(..., description="标识符如 hpi_onset")
    question: str = Field(..., description="口语化问题")
    type: str = Field(default="text", pattern="^(choice|text)$")
    options: list[str] = Field(default_factory=list)
    hint: str = Field(default="")
    allow_skip: bool = Field(default=True)
    phase: str = Field(default="", description="所属病史维度")
    reason: str = Field(default="")

class DifferentialEntry(BaseModel):
    diagnosis: str = Field(...)
    confidence: str = Field(default="low", pattern="^(high|medium|low)$")
    key_features: list[str] = Field(default_factory=list)
    reason: str = Field(default="")


class InterviewDecision(BaseModel):
    action: str = Field(default="ask", pattern="^(ask|search_only|synthesize)$")
    basic_module: list[BasicQuestion] = Field(default_factory=list, description="基本问诊问题(每轮1-2个)")
    advanced_module: list[BasicQuestion] = Field(default_factory=list, description="精细化问诊问题(按需0-1个)")
    differential_diagnoses: list[DifferentialEntry] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list, description="需要搜索的医学术语")
    primary_diagnosis: str = Field(default="", description="synthesize时的主要诊断")
    differential: list[str] = Field(default_factory=list)
    confidence: str = Field(default="medium")
    evidence: list[str] = Field(default_factory=list)
    needs_more_info: list[str] = Field(default_factory=list, description="缺失信息/建议检查")
    preliminary_hypotheses: list[DifferentialEntry] = Field(default_factory=list)
    reasoning: str = Field(default="")
    red_flags: list[str] = Field(default_factory=list)
    covered_dimensions: list[str] = Field(default_factory=list)


INTERVIEW_SYSTEM_PROMPT = """你是MediCareAI诊疗系统的路由Agent（Route Agent），负责编排多轨并行诊疗流程。

## 你的工作模式：三轨并行 → 整合中心 → 循环决策

### 轨道一：文本主诉 → 基本问诊
患者输入口语化主诉 → 你按照中国执业医师"病史采集"标准设计基本问诊问题：
  1.主诉 2.现病史(起病/症状特点/伴随/演变/诊疗经过) 3.既往史(慢性病/手术/传染病/过敏)
  4.个人史(生活习惯/职业/出行/一般情况-睡眠饮食二便体重精神)
  5.家族史 6.用药史
  7.特殊人群：儿童(喂养/发育/接种)、女性(月经/婚育)——仅当患者特征匹配时触发

### 轨道二：搜索增强 → 精细化问诊
对主诉进行SearXNG+RAG医学知识搜索 → 根据搜索结果设计靶向进阶问题：
  - 确认/排除鉴别诊断的关键特征
  - 量化症状细节
  - 关联性提问
  - 搜索发现的证据缺口 → 设计新问题填补

### 轨道三：多模态报告（未来）
患者上传检查报告 → OCR/视觉解析 → 提取结构化指标 → 并入整合中心

### 整合中心与循环
三条轨道数据汇入你的整合判断：
  1. 生成动态问诊卡片(选择题/文本题，数量不限)
  2. 患者作答 → 答案回到整合中心
  3. 评估信息完整性 → 不完整就继续追问/补充搜索 → 完整就进入诊断

## 每轮输出JSON

**action="ask"** — 需要问诊:
```json
{
  "action": "ask",
  "basic_module": [{"question_id":"hpi_xxx|pmh_xxx|ps_xxx|fh_xxx|med_xxx|ps_child_xxx|ps_female_xxx","question":"口语化问题","type":"choice|text","options":["选项"],"hint":"提示","allow_skip":true,"phase":"临床维度","reason":"为何问"}],
  "advanced_module": [{"question_id":"adv_xxx","question":"基于搜索的靶向问题","type":"choice|text","options":["选项"],"hint":"提示","allow_skip":true,"reason":"搜索发现XX需确认"}],
  "differential_diagnoses": [{"diagnosis":"疑似疾病","confidence":"high|medium|low","key_features":["特征"],"reason":"理由"}],
  "search_queries": ["可选：本轮需搜索的术语"],
  "reasoning": "完整临床推理",
  "red_flags": [],
  "covered_dimensions": ["已覆盖的病史维度"]
}
```

**action="synthesize"** — 可以诊断:
```json
{
  "action": "synthesize",
  "primary_diagnosis": "主要诊断",
  "differential": ["鉴别诊断"],
  "confidence": "high|medium|low",
  "evidence": ["支持证据"],
  "needs_more_info": ["缺失信息","建议做的检查"],
  "reasoning": "诊断推理过程",
  "covered_dimensions": ["已覆盖维度"]
}
```

## 关键规则
- 返回JSON(```json```)，无额外文字
- 问题口语化，用"您"开头，优先选择题
- 胸痛大汗/呼吸困难/意识模糊/剧烈腹痛→red_flags
- 已问ID不重复
- 无问题数上限，像真实医生
- 信息不全也可synthesize，在needs_more_info说明缺什么
- basic_module每轮1-2个，advanced_module每轮0个（临床信息不足时2个、足够时1个，灵活调整）
"""


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

def _build_interview_prompt(
    state: InterviewState,
    patient_history: str | None = None,
    knowledge_context: str = "",
) -> str:
    lines = [f"## 患者主诉\n{state.chief_complaint or '未知'}", ""]
    diffs = state.get_differential_diagnoses()
    if diffs:
        lines.append("## 当前鉴别诊断")
        for d in diffs:
            flag = "✓" if d.confidence == "high" else "?" if d.confidence == "medium" else "×"
            lines.append(f"  {flag} {d.diagnosis} ({d.confidence}) - {d.reason}")
        lines.append("")
    if state.collected_info:
        lines.append("## 已收集信息(最近)")
        recent = list(state.collected_info.items())
        for k, v in recent[-12:]:
            if not k.startswith("__") and v and v not in ("无","没有","不清楚","不记得","跳过","skipped",""):
                raw = state.raw_answers.get(k, "")
                lines.append(f"  {k}: {v}" + (f" ({raw})" if raw and raw != str(v) else ""))
        lines.append("")
    if knowledge_context:
        lines.append(f"## 搜索结果\n{knowledge_context[:1000]}")
        lines.append("")
    if patient_history:
        lines.append(f"## 既往史\n{patient_history}")
        lines.append("")
    pending = [p.value for p in PHASE_ORDER if p.value not in state.collected_info and not p.value.startswith("__")]
    lines.append(f"## 状态\n已问{len(state.asked_questions)}个问题")
    if pending:
        lines.append(f"未覆盖维度: {', '.join(pending[:6])}")
    if state.asked_questions:
        lines.append(f"已问ID: {', '.join(state.asked_questions[-8:])}")
    lines.append("")
    lines.append("请返回action=ask(提问)/search_only(搜索)/synthesize(诊断)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON Extraction Helper
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if "```json" in text:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    elif "```" in text:
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    if not text:
        raise ValueError("empty LLM response after extraction")
    return json.loads(text)


# ---------------------------------------------------------------------------
# Dynamic Interview Engine — Differential-Diagnosis-Driven
# ---------------------------------------------------------------------------

class DynamicInterviewEngine:

    def __init__(self, llm_service: Any, search_executor: Any = None) -> None:
        self.llm = llm_service
        self.search = search_executor
        self.logger = logging.getLogger("interview.engine")

    async def decide_next(
        self,
        state: InterviewState,
        patient_history: str | None = None,
        knowledge_context: str = "",
    ) -> tuple[list[QuestionTemplate], InterviewState, list[str], str, str]:
        """Mesh-architecture clinical decision. Returns (questions, state, search_queries, action, reasoning)."""
        prompt = _build_interview_prompt(state, patient_history, knowledge_context)
        self.logger.info(f"[DECIDE] asked={len(state.asked_questions)} pending_dims={len([p for p in PHASE_ORDER if p.value not in state.collected_info])}")

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=INTERVIEW_SYSTEM_PROMPT,
                max_tokens=8000,
            )
            self.logger.info(f"[DECIDE] LLM response len={len(response.content)} preview={response.content[:100]}")
            raw = _extract_json(response.content)
            decision = InterviewDecision.model_validate(raw)
            action = decision.action
            self.logger.info(f"[DECIDE] action={action} basic_qs={len(decision.basic_module)} advanced_qs={len(decision.advanced_module)} searches={len(decision.search_queries)} diffs={len(decision.differential_diagnoses)}")

            if decision.red_flags:
                state.red_flags_detected.extend(decision.red_flags)
                state.is_sufficient = True
                self.logger.warning(f"[DECIDE] RED_FLAGS: {decision.red_flags}")
                return [], state, [], "synthesize", ""

            if decision.differential_diagnoses:
                diffs = [DifferentialHypothesis(diagnosis=d.diagnosis, confidence=d.confidence, key_features=d.key_features, reason=d.reason) for d in decision.differential_diagnoses]
                state.set_differential_diagnoses(diffs)

            meaningful = [k for k, v in state.collected_info.items() if not k.startswith("__") and v not in ("无","没有","不清楚","不记得","跳过","skipped","")]
            current = len(meaningful)
            state.stagnation_counter = state.stagnation_counter + 1 if current <= state.last_collected_count else 0
            state.last_collected_count = current

            if action == "synthesize":
                state.is_sufficient = True
                self.logger.info(f"[DECIDE] SYNTHESIZE: diagnosis={decision.primary_diagnosis}")
                return [], state, [], "synthesize", decision.reasoning

            questions: list[QuestionTemplate] = []
            for m in decision.basic_module + decision.advanced_module:
                qid = m.question_id
                if qid in state.asked_questions:
                    qid = f"{qid}_{len(state.asked_questions)}"
                questions.append(QuestionTemplate(question_id=qid, question=m.question, type=m.type, options=m.options if m.type=="choice" else [], hint=m.hint, allow_skip=m.allow_skip, phase=m.phase, colloquial_phase=m.phase))
                state.current_question_id = qid

            search_queries = decision.search_queries or []
            if decision.action == "search_only":
                search_queries = search_queries or [state.chief_complaint]
                self.logger.info(f"[DECIDE] SEARCH_ONLY: queries={search_queries}")

            state.fallback_count = 0
            return questions, state, search_queries, action, decision.reasoning

        except Exception as e:
            self.logger.error(f"[DECIDE] LLM FAILED: {e} | raw={response.content[:200] if 'response' in dir() else 'N/A'}", exc_info=True)
            state.fallback_count += 1
            if state.fallback_count >= 2 or len(state.asked_questions) >= 3:
                state.is_sufficient = True
                self.logger.warning(f"[DECIDE] FORCING SYNTHESIZE after {state.fallback_count} failures")
                return [], state, [], "synthesize", ""
            # Lightweight LLM call with minimal prompt — far less likely to time out
            try:
                light_resp = await self.llm.chat(
                    messages=[{
                        "role": "user",
                        "content": f'患者主诉：{state.chief_complaint}\n\n请生成1个口语化的追问，让患者进一步描述症状。返回JSON：{{"question":"...","question_id":"lt_hpi_001","type":"text","phase":"现病史"}}'
                    }],
                    system_prompt="你是问诊助手。只返回JSON。",
                    max_tokens=256,
                )
                data = _extract_json(light_resp.content)
                qid = data.get("question_id", f"lt_{state.fallback_count}")
                question_text = data.get("question")
                qtype = data.get("type", "text")
                phase_label = data.get("phase", "现病史")
                if not question_text:
                    raise ValueError("empty question from lightweight LLM")
            except Exception:
                try:
                    light_resp2 = await self.llm.chat(
                        messages=[{"role": "user", "content": f'关于"{state.chief_complaint}"，请用一句话追问。只返回JSON：{{"q":"问题文本"}}'}],
                        system_prompt="只返回JSON。",
                        max_tokens=128,
                    )
                    data2 = _extract_json(light_resp2.content)
                    question_text = data2.get("q")
                    if not question_text:
                        raise ValueError("empty retry")
                except Exception:
                    question_text = state.chief_complaint
                qid = f"lt_{state.fallback_count}"
                qtype = "text"
                phase_label = "现病史"
            fallback = QuestionTemplate(
                question_id=qid,
                question=question_text,
                type=qtype,
                hint="请自由描述",
                allow_skip=False,
                phase=phase_label,
                colloquial_phase=phase_label,
            )
            state.current_question_id = qid
            self.logger.info(f"[DECIDE] returning lightweight fallback question (fallback_count={state.fallback_count})")
            return [fallback], state, [], "ask", ""

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
                system_prompt="你是医学信息提取助手。从患者回答中提取关键信息。只返回JSON。",
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



