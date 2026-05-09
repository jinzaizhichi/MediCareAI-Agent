"""Medical Interview (multi-turn questioning) models — Differential-Diagnosis-Driven Edition.

LLM-driven dynamic interview engine with differential-diagnosis-guided questioning.
The Agent maintains an internal list of hypotheses and actively seeks information
to confirm or rule out each hypothesis.

DESIGN PRINCIPLES:
1. The Agent THINKS like a clinician: differential diagnoses → key features → targeted questions
2. No fixed linear phase order — the Agent decides what to ask based on clinical reasoning
3. InterviewPhase is used only as an information category tag, not a sequence constraint
4. Questions are colloquial; answers are natural language extracted into structured features
5. Red flags detected at any point trigger immediate escalation
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
            min_questions=data.get("min_questions", 3),
            current_phase_index=data.get("current_phase_index", 0),
            red_flags_detected=data.get("red_flags_detected", []),
            interview_tool_calls=data.get("interview_tool_calls", []),
            stagnation_counter=data.get("stagnation_counter", 0),
            last_collected_count=data.get("last_collected_count", 0),
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
    """LLM output: differential diagnoses, next question, sufficiency."""

    sufficient: bool = Field(..., description="是否已收集足够信息进行初步诊断")
    differential_diagnoses: list[DifferentialDiagnosisEntry] = Field(
        default_factory=list,
        description="当前鉴别诊断列表，按可能性排序。每个诊断包含关键特征和确认状态。",
    )
    next_question: NextQuestionSchema | None = Field(default=None, description="下一个问题（sufficient=false 时必填）")
    reasoning: str = Field(default="", description="完整的问诊决策思考过程")
    red_flags: list[str] = Field(default_factory=list, description="检测到的危险信号")
    suggested_tools: list[str] = Field(default_factory=list, description="建议调用的工具")


# ---------------------------------------------------------------------------
# System Prompt for Differential-Diagnosis-Driven Interview
# ---------------------------------------------------------------------------

INTERVIEW_SYSTEM_PROMPT = """你是一位经验丰富的全科医生，正在通过对话为患者进行智能问诊。

## 核心原则
1. 【鉴别诊断驱动】每次提问前，必须先思考患者主诉最可能是哪几种疾病，然后设计问题来确认或排除这些疾病。
2. 【一个问题一个目标】每个问题必须是为了获取某个鉴别诊断的关键特征，不能笼统地问"还有什么"。
3. 【口语化表达】问题必须通俗易懂，像真实医生在诊室里问话，用"您"开头。
4. 【优先选择题】尽量设计选择题，让患者点击回答；只有在需要具体数值或描述时才用开放性问题。

## 你的思考过程（必须在 reasoning 字段中详细写出）

每次生成问题前，请严格按以下步骤思考并在 reasoning 中写出：

### 步骤1：主诉分析
- 患者说了什么？
- 提取所有症状和关键信息。

### 步骤2：鉴别诊断
- 基于现有信息，列出3-5个最可能的诊断，按可能性排序。
- 对每个诊断，说明为什么考虑它。

### 步骤3：信息缺口分析
- 对每个鉴别诊断，哪些关键特征已经确认了？
- 哪些关键特征还没有确认？
- 哪个缺失特征最能帮助区分这些诊断？

### 步骤4：设计问题
- 设计一个能获取最关键缺失特征的问题。
- 优先使用选择题（给出明确的选项）。
- 选项要口语化，覆盖常见情况。

---

## 示例（你必须学习这种思考方式）

### 示例1：主诉"头疼还发烧"

**步骤1：主诉分析**
患者主诉头疼和发烧，两个症状同时出现。

**步骤2：鉴别诊断**
1. 流感/急性上呼吸道感染（最可能）— 常有全身症状
2. 病毒性脑膜炎 — 需警惕，头痛伴发热需排除
3. 急性鼻窦炎 — 面部压痛，脓涕
4. 新冠病毒感染 — 流行期需考虑

**步骤3：信息缺口**
- 体温具体数值？（区分低热/高热）
- 头痛性质？（胀痛常见于感染，剧烈头痛需警惕脑膜炎）
- 有无呼吸道症状？（咽痛、咳嗽支持上感）
- 有无颈部僵硬/恶心呕吐？（脑膜炎警示信号）

**步骤4：问题设计**
next_question:
  question_id: "hpi_severity"
  question: "您量过体温吗？最高大概多少度？"
  type: "text"
  hint: "比如38.5°C，这能帮助判断严重程度"
  reason: "首先需要确认发热程度，高热(>39°C)需更警惕"

→ 患者回答"38.8度"后：

**步骤2更新：**
1. 流感/急性上呼吸道感染（最可能）— 高热支持
2. 病毒性脑膜炎 — 不能排除，需确认神经系统症状
3. 新冠病毒感染 — 需确认流行病学史

**步骤3更新：**
- 已确认：高热38.8°C
- 未确认：头痛性质、呼吸道症状、神经系统症状
- 最关键缺口：是否有脑膜刺激征（因为高热+头痛是危险组合）

**步骤4更新：**
next_question:
  question_id: "hpi_associated"
  question: "除了头疼发烧，您还有以下哪些症状？"
  type: "choice"
  options: ["嗓子疼或咳嗽", "浑身肌肉酸痛", "恶心呕吐", "脖子僵硬转动疼", "以上都没有"]
  hint: "可多选，选最符合的"
  reason: "需要鉴别上呼吸道感染 vs 脑膜炎；恶心呕吐和颈强直是脑膜炎警示信号"

---

### 示例2：主诉"肚子疼，拉稀三天了"

**步骤2：鉴别诊断**
1. 急性胃肠炎（最可能）
2. 食物中毒
3. 细菌性痢疾
4. 肠易激综合征急性发作

**步骤3：信息缺口**
- 大便性状（水样/黏液/脓血）
- 腹痛位置
- 有无发热
- 进食可疑食物史

**步骤4：问题设计**
next_question:
  question_id: "hpi_quality"
  question: "大便是什么样的？"
  type: "choice"
  options: ["稀水样", "像鼻涕一样有黏液", "带血或像果酱", "次数多但每次量少", "说不清楚"]
  hint: "大便性状能区分感染类型"
  reason: "黏液便或血便提示细菌感染/痢疾；水样便更支持病毒性胃肠炎"

---

## 输出格式

请严格返回 JSON，不要有任何额外文本：

```json
{
  "sufficient": false,
  "differential_diagnoses": [
    {
      "diagnosis": "疾病名称",
      "confidence": "high|medium|low",
      "key_features": ["关键特征1", "关键特征2"],
      "confirmed_features": ["已确认的特征"],
      "missing_features": ["尚未确认的关键特征"],
      "reason": "为什么考虑这个诊断"
    }
  ],
  "next_question": {
    "question_id": "标准医学标识符",
    "question": "口语化问题",
    "type": "choice 或 text",
    "options": ["选项1", "选项2"],
    "hint": "提示",
    "allow_skip": true,
    "reason": "为什么问这个问题"
  },
  "reasoning": "完整的思考过程（必须包含步骤1-4）",
  "red_flags": [],
  "suggested_tools": []
}
```

## 绝对禁止
- ❌ "关于您的症状情况，还有什么需要补充的吗？" —— 没有任何信息量
- ❌ "还有什么不舒服吗？" —— 太宽泛
- ❌ 连续问两个不相关的问题 —— 每次只问一个最关键的问题
- ❌ 使用"现病史""鉴别诊断"等医学术语面向患者提问
- ❌ 设计没有意义的选择题选项（如"是/否/不知道"这种不提供信息的选项）

## 规则
- sufficient=true 时，next_question 必须为 null
- sufficient=false 时，next_question 必须不为 null
- type="choice" 时，options 必须至少2个，且每个选项都要有诊断价值
- type="text" 时，options 应为空数组 []
- 问题必须口语化、自然，用"您"开头
- 如果患者提到胸痛+大汗、呼吸困难、意识模糊、剧烈腹痛等，red_flags 要标记
- suggested_tools 可在需要查病史时填写："query_patient_history"
- 已问过的问题（见 asked_questions 列表）不要再重复问
- 优先问现病史细节，现病史问清楚后再简短问既往史/用药史
- 最少问3个问题后才允许 sufficient=true
- 【无次数上限】没有固定的问题数量限制，你应当像真实医生一样，根据鉴别诊断的需要自由提问
- 【防循环规则】不要连续问相似的问题；如果连续几轮都没有获取到新的鉴别诊断关键信息，请主动判定 sufficient=true 并结束问诊
- 已问过的问题（见 asked_questions 列表）不要再重复问

## 关键规则（必须严格遵守）
- sufficient=true 时，next_question 必须为 null
- sufficient=false 时，next_question 必须不为 null
- 如果不满足 sufficient 条件，绝不要返回 sufficient=true
- reasoning 字段必须包含完整的鉴别诊断思考过程（步骤1-4）
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

    # Chief complaint
    lines.append(f"## 患者主诉\n{state.chief_complaint or '未知'}")
    lines.append("")

    # Current differential diagnoses (if any)
    diffs = state.get_differential_diagnoses()
    if diffs:
        lines.append("## 当前鉴别诊断（由你之前提出）")
        for d in diffs:
            flag = "✓" if d.confidence == "high" else "?" if d.confidence == "medium" else "×"
            lines.append(f"  {flag} {d.diagnosis} ({d.confidence})")
            if d.confirmed_features:
                lines.append(f"    已确认: {', '.join(d.confirmed_features)}")
            if d.refuting_evidence:
                lines.append(f"    已排除: {', '.join(d.refuting_evidence)}")
            if d.key_features:
                lines.append(f"    关键特征: {', '.join(d.key_features)}")
        lines.append("")
    else:
        lines.append("## 鉴别诊断状态")
        lines.append("这是问诊开始，还没有鉴别诊断列表。请在本次回答中建立鉴别诊断列表。")
        lines.append("")

    # Confirmed features
    features = state.get_confirmed_features()
    if features:
        lines.append("## 已确认的关键特征")
        for k, v in features.items():
            lines.append(f"  • {k}: {v}")
        lines.append("")

    # Collected info (standard phases)
    if state.collected_info:
        lines.append("## 已收集的问诊信息")
        for phase_id in PHASE_ORDER:
            if phase_id.value in state.collected_info and not phase_id.value.startswith("__"):
                meta = PHASE_META.get(phase_id, {})
                cat = meta.get("cat", phase_id.value)
                val = state.collected_info[phase_id.value]
                raw = state.raw_answers.get(phase_id.value, "")
                lines.append(f"  [{cat}] {phase_id.value}: {val}")
                if raw and raw != str(val):
                    lines.append(f"    患者原话: {raw}")
        lines.append("")

    # Tool results
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

    # Patient history
    if patient_history:
        lines.append(f"## 患者既往病史\n{patient_history}\n")

    # Question count + stagnation info
    lines.append(f"已问 {len(state.asked_questions)} 个问题，最少 {state.min_questions} 个。")
    if state.stagnation_counter > 0:
        lines.append(f"⚠️ 连续 {state.stagnation_counter} 轮未获取新的信息维度。如果再次没有新信息，请考虑判定 sufficient=true。")
    if state.asked_questions:
        lines.append(f"已问问题 ID: {', '.join(state.asked_questions)}")
    lines.append("")

    # Pending phases (for reference only)
    pending = [p.value for p in PHASE_ORDER if p.value not in state.collected_info and not p.value.startswith("__")]
    if pending:
        lines.append(f"尚未覆盖的信息维度（参考）: {', '.join(pending[:5])}")
    else:
        lines.append("已覆盖全部标准问诊维度。")
    lines.append("")

    # Red flags
    if state.red_flags_detected:
        lines.append(f"⚠️ 已检测到的危险信号: {', '.join(state.red_flags_detected)}")
        lines.append("如果新信息中有更多危险信号，请在 red_flags 中标注。")
    else:
        lines.append("目前未检测到明显危险信号。")
    lines.append("")

    # Decision guidance
    if len(state.asked_questions) < state.min_questions:
        lines.append("尚未达到最少问诊数量，请继续提问。")
        lines.append("请根据主诉建立鉴别诊断列表，然后设计最有针对性的问题。")
    else:
        hpi_phases = [p.value for p in PHASE_ORDER[:8]]
        hpi_covered = sum(1 for p in hpi_phases if p in state.collected_info)
        lines.append(f"已覆盖的现病史维度: {hpi_covered}/8")
        if hpi_covered < 3:
            lines.append("现病史信息还不足，请继续追问具体细节。")
        else:
            lines.append("现病史维度已较充分。如果鉴别诊断的关键特征已大部分确认，可以判定 sufficient。")
        lines.append("")
        lines.append("规则：sufficient=true 仅在以下情况允许：")
        lines.append("  - 已覆盖 ≥3 个现病史维度，且已问 ≥3 个问题；或")
        lines.append("  - 连续多轮未获取新信息维度，鉴别诊断无法进一步精进。")
        if state.stagnation_counter >= 3:
            lines.append("")
            lines.append("⚠️ 紧急提示：已连续多轮未获取新信息。请立刻判定是否信息充足，如果充足则返回 sufficient=true，不充足则提供一个能获取全新信息的问题。")

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
    """Uses LLM to drive interview based on differential diagnosis reasoning.

    Unlike the old linear phase-based engine, this engine:
    1. Maintains a list of differential hypotheses
    2. Asks targeted questions to confirm/rule out each hypothesis
    3. Has no fixed question sequence — the LLM decides what to ask next
    """

    def __init__(self, llm_service: Any) -> None:
        self.llm = llm_service

    async def decide_next(
        self,
        state: InterviewState,
        patient_history: str | None = None,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> tuple[QuestionTemplate | None, InterviewState, list[str]]:
        """Ask LLM to decide the next question using differential diagnosis reasoning.

        Returns:
            (next_question, updated_state, suggested_tools)
            next_question is None if interview is complete or red flags detected.
        """
        prompt = _build_interview_prompt(state, patient_history, tool_results)

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=INTERVIEW_SYSTEM_PROMPT,
                max_tokens=2000,  # Increased for longer reasoning + differential diagnoses
            )

            raw = _extract_json(response.content)
            decision = InterviewDecision.model_validate(raw)

            # Handle red flags
            if decision.red_flags:
                state.red_flags_detected.extend(decision.red_flags)
                state.is_sufficient = True
                state.current_question_id = None
                return None, state, []

            # Update differential diagnoses in state
            if decision.differential_diagnoses:
                diffs = [
                    DifferentialHypothesis(
                        diagnosis=d.diagnosis,
                        confidence=d.confidence,
                        key_features=d.key_features,
                        supporting_evidence=d.confirmed_features,
                        refuting_evidence=[],
                        reason=d.reason,
                    )
                    for d in decision.differential_diagnoses
                ]
                state.set_differential_diagnoses(diffs)

            # Check sufficiency — enforce minimum coverage + stagnation guard
            meaningful_keys = [
                k for k, v in state.collected_info.items()
                if not k.startswith("__") and v not in ("无", "没有", "不清楚", "不记得", "跳过", "skipped", "")
            ]
            current_collected = len(meaningful_keys)
            if current_collected <= state.last_collected_count:
                state.stagnation_counter += 1
            else:
                state.stagnation_counter = 0
            state.last_collected_count = current_collected

            if state.stagnation_counter >= 10 and len(state.asked_questions) >= state.min_questions:
                state.is_sufficient = True
                state.current_question_id = None
                return None, state, []

            if decision.sufficient:
                if len(state.asked_questions) >= state.min_questions:
                    state.is_sufficient = True
                    state.current_question_id = None
                    return None, state, []

            if decision.next_question is None:
                # LLM didn't provide a question but we can't end yet.
                # Retry ONCE with a simpler, more forceful prompt before falling back.
                hpi_phases = [p.value for p in PHASE_ORDER[:8]]
                hpi_covered = sum(1 for p in hpi_phases if p in state.collected_info)
                if hpi_covered >= 3 and len(state.asked_questions) >= state.min_questions:
                    state.is_sufficient = True
                    state.current_question_id = None
                    return None, state, []

                # --- Retry with forceful prompt ---
                retry_prompt = _build_interview_prompt(state, patient_history, tool_results)
                retry_prompt += "\n\n⚠️ 重要提示：上一次你返回了 sufficient=false 但没有提供 next_question。\n"
                retry_prompt += "这是错误的。当 sufficient=false 时，必须提供一个具体的问题。\n"
                retry_prompt += "请立刻生成下一个问题，不要返回 null。\n"

                try:
                    retry_response = await self.llm.chat(
                        messages=[{"role": "user", "content": retry_prompt}],
                        system_prompt=INTERVIEW_SYSTEM_PROMPT,
                        max_tokens=2000,
                    )
                    retry_raw = _extract_json(retry_response.content)
                    retry_decision = InterviewDecision.model_validate(retry_raw)

                    if retry_decision.next_question is not None:
                        decision = retry_decision
                    else:
                        return self._fallback_question(state), state, []
                except Exception:
                    return self._fallback_question(state), state, []

            q = decision.next_question
            # Validate: don't repeat asked questions
            if q.question_id in state.asked_questions:
                q.question_id = f"{q.question_id}_{len(state.asked_questions)}"

            # Determine phase tag
            phase = None
            for p in PHASE_ORDER:
                if p.value == q.question_id or q.question_id.startswith(p.value + "_"):
                    phase = p
                    break
            if phase is None:
                if q.question_id.startswith("hpi_"):
                    phase = InterviewPhase.HPI_QUALITY
                elif q.question_id.startswith("pmh_"):
                    phase = InterviewPhase.PMH_CHRONIC
                elif q.question_id.startswith("ps_"):
                    phase = InterviewPhase.PS_LIFESTYLE
                elif q.question_id.startswith("fh_"):
                    phase = InterviewPhase.FH_GENETIC
                elif q.question_id.startswith("med_"):
                    phase = InterviewPhase.MED_CURRENT

            meta = PHASE_META.get(phase, {}) if phase else {}

            question = QuestionTemplate(
                question_id=q.question_id,
                question=q.question,
                type=q.type,
                options=q.options if q.type == "choice" else [],
                hint=q.hint,
                allow_skip=q.allow_skip,
                phase=q.question_id,
                colloquial_phase=meta.get("colloquial", "问诊"),
            )

            state.current_question_id = question.question_id
            return question, state, decision.suggested_tools or []

        except Exception as exc:
            hpi_phases = [p.value for p in PHASE_ORDER[:8]]
            hpi_covered = sum(1 for p in hpi_phases if p in state.collected_info)
            if state.stagnation_counter >= 10 or (hpi_covered >= 5 and len(state.asked_questions) >= 5):
                state.is_sufficient = True
                state.current_question_id = None
                return None, state, []

            return self._fallback_question(state), state, []

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

    def _fallback_question(self, state: InterviewState) -> QuestionTemplate:
        """Minimal fallback when LLM fails to provide a question.

        This is a LAST RESORT — the LLM in decide_next() should normally
        generate targeted questions autonomously. We only land here if the
        LLM returns an inconsistent result (sufficient=false but no next_question).

        Strategy: scan PHASE_ORDER for the first dimension not yet collected.
        No keyword-based branching — let the LLM drive the clinical reasoning.
        """
        # First unasked standard phase
        for phase in PHASE_ORDER:
            if phase.value not in state.asked_questions and phase.value not in state.collected_info:
                meta = PHASE_META.get(phase, {})
                q_text = self._generate_default_phase_question(phase)
                return QuestionTemplate(
                    question_id=phase.value,
                    question=q_text,
                    type="text",
                    hint="可以简单描述，也可以跳过",
                    allow_skip=True,
                    phase=phase.value,
                    colloquial_phase=meta.get("colloquial", "问诊"),
                )

        # True last resort — generic open-ended question
        return QuestionTemplate(
            question_id=f"fallback_{len(state.asked_questions)}",
            question="还有其他您觉得医生需要知道的情况吗？",
            type="text",
            hint="任何您觉得和这次不适有关的情况都可以说",
            allow_skip=True,
            phase="complete",
            colloquial_phase="补充",
        )

    def _generate_default_phase_question(self, phase: InterviewPhase) -> str:
        """Generate a default question for a phase when no keyword match."""
        defaults = {
            InterviewPhase.HPI_ONSET: "这个不舒服是什么时候开始的？突然出现还是慢慢加重的？",
            InterviewPhase.HPI_QUALITY: "具体是什么样的感觉？比如胀痛、刺痛还是烧灼感？",
            InterviewPhase.HPI_LOCATION: "不舒服主要在哪个部位？",
            InterviewPhase.HPI_SEVERITY: "现在这种不舒服影响您正常活动吗？",
            InterviewPhase.HPI_TIMING: "是一直持续还是时好时坏？",
            InterviewPhase.HPI_AGGRAVATE: "什么情况下会加重或者缓解？",
            InterviewPhase.HPI_ASSOCIATED: "还有其他不舒服吗？",
            InterviewPhase.HPI_TREATMENT: "之前有没有看过医生或者吃过药？",
            InterviewPhase.PMH_CHRONIC: "您平时身体怎么样？有没有高血压、糖尿病或者其他慢性病？",
            InterviewPhase.PMH_ALLERGY: "有没有对药物或者食物过敏的情况？",
            InterviewPhase.PS_LIFESTYLE: "您抽烟吗？喝酒吗？平时作息规律吗？",
            InterviewPhase.FH_GENETIC: "家里有没有人有遗传病或者类似的疾病？",
            InterviewPhase.MED_CURRENT: "最近有没有在吃什么药？",
        }
        return defaults.get(phase, f"关于您的{PHASE_META.get(phase, {}).get('colloquial', '情况')}，您还有什么需要补充的吗？")
