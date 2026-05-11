"""
Independent Track Agents + Orchestrator for Plan B architecture.

Track1Agent: History collection (standard clinical interview questions).
Track2Agent: Search-driven refinement (generates questions AFTER search results).
InterviewOrchestrator: Coordinates tracks, merges results, manages state.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from app.models.interview import (
    InterviewState,
    QuestionTemplate,
    InterviewDecision,
    DifferentialHypothesis,
    PHASE_ORDER,
    _extract_json,
)
from app.services.llm import LLMService

logger = logging.getLogger("orchestrator")


# ---------------------------------------------------------------------------
# Track 1 Agent: History Collection
# ---------------------------------------------------------------------------

TRACK1_SYSTEM_PROMPT = """你是病史采集专家。根据患者主诉和已收集信息，基于中国执业医师标准生成问诊问题。

职责：
- 覆盖未问的临床维度：现病史(起病/症状特点/伴随/演变/诊疗经过)、既往史、个人史(含一般情况)、家族史、用药史
- 特殊人群：儿童(喂养/发育/接种)、女性(月经/婚育)——仅匹配时触发
- 问题口语化，用"您"开头，优先选择题
- 每轮1-2个问题，不重复已问维度
- 已收集的信息对应的维度不要再问

只返回JSON（```json```包裹）。"""

TRACK1_DECISION_SCHEMA = """返回JSON：
{
  "action": "ask",
  "basic_module": [
    {"question_id":"hpi_xxx|pmh_xxx|ps_xxx","question":"口语化问题","type":"choice|text","options":["选项"],"hint":"提示","allow_skip":true,"phase":"临床维度","reason":"为何问"}
  ],
  "differential_diagnoses": [
    {"diagnosis":"疑似疾病","confidence":"high|medium|low","key_features":["特征"],"reason":"理由"}
  ],
  "red_flags": [],
  "covered_dimensions": ["已覆盖维度"],
  "reasoning": "临床推理"
}
"""


# ---------------------------------------------------------------------------
# Track 2 Agent: Search-Driven Refinement
# ---------------------------------------------------------------------------

TRACK2_SYSTEM_PROMPT = """你是搜索增强问诊专家。基于SearXNG+RAG搜索结果，生成靶向进阶问题。

职责：
- 分析搜索结果中的关键临床线索
- 针对鉴别诊断的confirmed/missing特征设计确认问题
- 搜索发现的证据缺口→设计新问题填补
- 问题量1-2个，不重复已问维度和轨道一已覆盖内容

只返回JSON（```json```包裹）。"""

TRACK2_DECISION_SCHEMA = """返回JSON：
{
  "advanced_module": [
    {"question_id":"adv_xxx","question":"基于搜索的靶向问题","type":"choice|text","options":["选项"],"hint":"提示","allow_skip":true,"reason":"搜索发现XX需确认"}
  ]
}
"""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class RoundResult:
    questions: list[QuestionTemplate]
    state: InterviewState
    search_queries: list[str]
    action: str
    reasoning: str


class Track1Agent:

    def __init__(self, llm: LLMService):
        self.llm = llm

    async def generate(
        self,
        state: InterviewState,
        patient_history: str | None = None,
    ) -> tuple[list[QuestionTemplate], list[DifferentialHypothesis], list[str], str]:
        prompt = self._build_prompt(state, patient_history)
        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=TRACK1_SYSTEM_PROMPT,
                max_tokens=2048,
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw = _extract_json(response.content)
            decision = InterviewDecision.model_validate(raw)
            questions = self._to_templates(decision.basic_module, state)
            logger.info(
                "[TRACK1] questions=%d red_flags=%d",
                len(questions),
                len(decision.red_flags or []),
            )
            diffs = [
                DifferentialHypothesis(
                    diagnosis=d.diagnosis,
                    confidence=d.confidence,
                    key_features=d.key_features,
                    reason=d.reason,
                )
                for d in (decision.differential_diagnoses or [])
            ]
            return questions, diffs, decision.red_flags or [], decision.reasoning or ""
        except Exception as e:
            logger.error(f"[TRACK1] FAILED: {e}")
            return [], [], [], ""

    def _build_prompt(self, state: InterviewState, patient_history: str | None) -> str:
        lines = [f"## 患者主诉\n{state.chief_complaint or '未知'}"]
        if patient_history:
            lines.append(f"\n## 既往史\n{patient_history[:500]}")
        if state.collected_info:
            lines.append("\n## 已收集信息(最近)")
            recent = list(state.collected_info.items())
            for k, v in recent[-8:]:
                if not k.startswith("__"):
                    lines.append(f"- {k}: {str(v)[:100]}")
        pending = [p.value for p in PHASE_ORDER if p.value not in state.collected_info]
        lines.append(f"\n## 未覆盖维度\n{', '.join(pending[:8])}")
        lines.append(f"\n## 已问数量\n{len(state.asked_questions)}")
        lines.append("\n" + TRACK1_DECISION_SCHEMA)
        return "\n".join(lines)

    @staticmethod
    def _to_templates(module: list, state: InterviewState) -> list[QuestionTemplate]:
        result = []
        for m in module:
            qid = m.question_id
            if qid in state.asked_questions:
                qid = f"{qid}_{len(state.asked_questions)}"
            result.append(QuestionTemplate(
                question_id=qid,
                question=m.question,
                type=m.type,
                options=m.options if m.type == "choice" else [],
                hint=m.hint,
                allow_skip=m.allow_skip,
                phase=m.phase,
                colloquial_phase=m.phase,
            ))
        return result


class Track2Agent:

    def __init__(self, llm: LLMService):
        self.llm = llm

    async def generate(
        self,
        state: InterviewState,
        search_results: str,
        diffs: list[DifferentialHypothesis],
    ) -> list[QuestionTemplate]:
        if not search_results or len(search_results.strip()) < 20:
            return []
        prompt = self._build_prompt(state, search_results, diffs)
        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=TRACK2_SYSTEM_PROMPT,
                max_tokens=1024,
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw = _extract_json(response.content)
            questions = self._to_templates(raw.get("advanced_module", []), state)
            logger.info("[TRACK2] questions=%d from search", len(questions))
            return questions
        except Exception as e:
            logger.error(f"[TRACK2] FAILED: {e}")
            return []

    def _build_prompt(self, state: InterviewState, search_results: str, diffs: list[DifferentialHypothesis]) -> str:
        lines = [f"## 患者主诉\n{state.chief_complaint}"]
        lines.append(f"\n## 搜索结果\n{search_results[:1500]}")
        if diffs:
            lines.append("\n## 当前鉴别诊断")
            for d in diffs[:5]:
                lines.append(f"- {d.diagnosis} (置信度:{d.confidence}) {d.key_features}")
        if state.collected_info:
            lines.append("\n## 已收集信息键")
            collected_keys = [k for k in state.collected_info if not k.startswith("__")]
            lines.append(", ".join(collected_keys[-8:]))
        lines.append("\n" + TRACK2_DECISION_SCHEMA)
        return "\n".join(lines)

    @staticmethod
    def _to_templates(module: list, state: InterviewState) -> list[QuestionTemplate]:
        result = []
        for m in module:
            qid = m.get("question_id", "adv_001")
            if qid in state.asked_questions:
                qid = f"{qid}_{len(state.asked_questions)}"
            result.append(QuestionTemplate(
                question_id=qid,
                question=m.get("question", ""),
                type=m.get("type", "text"),
                options=m.get("options", []) if m.get("type") == "choice" else [],
                hint=m.get("hint", ""),
                allow_skip=m.get("allow_skip", True),
                phase=m.get("phase", "搜索补充"),
                colloquial_phase=m.get("phase", "搜索补充"),
            ))
        return result


class InterviewOrchestrator:

    def __init__(self, llm: LLMService, search_executor: Any = None):
        self.track1 = Track1Agent(llm)
        self.track2 = Track2Agent(llm)
        self.search = search_executor
        self.logger = logging.getLogger("orchestrator")

    async def decide_next(
        self,
        state: InterviewState,
        patient_history: str | None = None,
        knowledge_context: str = "",
    ) -> tuple[list[QuestionTemplate], InterviewState, list[str], str, str]:
        chief = state.chief_complaint
        self.logger.info(
            "[ORCH] asked=%d pending=%d",
            len(state.asked_questions),
            len([p for p in PHASE_ORDER if p.value not in state.collected_info]),
        )

        # Phase 1: Track1 + Search in parallel
        track1_task = self.track1.generate(state, patient_history)
        search_task = self._run_search(chief, state) if self.search else asyncio.sleep(0, result="")

        track1_questions, diffs, red_flags, reasoning = await track1_task
        search_results = await search_task

        # Process red flags from Track1
        if red_flags:
            state.red_flags_detected.extend(red_flags)
            self.logger.warning("[ORCH] RED_FLAGS from Track1: %s", red_flags)

        # Update differential diagnoses from Track1
        if diffs:
            state.set_differential_diagnoses(diffs)

        # Phase 2: Track2 generates refinement questions from search results
        track2_questions = await self.track2.generate(state, search_results, diffs)

        # Phase 3: Merge and deduplicate
        all_questions = track1_questions + track2_questions
        deduped = self._deduplicate(all_questions, state)

        # Phase 4: Decision logic
        action = "ask"
        if state.red_flags_detected and len(state.asked_questions) >= state.min_questions:
            action = "synthesize"
            state.is_sufficient = True
            self.logger.warning("[ORCH] FORCING SYNTHESIZE due to red_flags after %d questions", len(state.asked_questions))

        if not deduped and action == "ask":
            deduped = [QuestionTemplate(
                question_id=f"cq_{len(state.asked_questions)}",
                question="请继续描述您的症状，有什么新的变化或补充吗？",
                type="text",
                hint="没有变化可以说'没有'",
                allow_skip=True,
                phase="现病史",
                colloquial_phase="症状更新",
            )]
            self.logger.info("[ORCH] No questions generated, using continuity question")

        for q in deduped:
            state.current_question_id = q.question_id

        return deduped, state, [], action, reasoning

    async def _run_search(self, chief_complaint: str, state: InterviewState) -> str:
        try:
            results = await asyncio.wait_for(
                self.search(chief_complaint, state),
                timeout=30.0,
            )
            if isinstance(results, str):
                return results[:2000]
            if isinstance(results, list):
                return "\n".join(
                    f"- {getattr(r, 'title', '')}: {getattr(r, 'snippet', '')[:200]}"
                    for r in results[:5]
                )
            return str(results)[:2000]
        except asyncio.TimeoutError:
            self.logger.warning("[ORCH] Search timed out")
            return ""
        except Exception as e:
            self.logger.error(f"[ORCH] Search failed: {e}")
            return ""

    @staticmethod
    def _deduplicate(questions: list[QuestionTemplate], state: InterviewState) -> list[QuestionTemplate]:
        seen_ids = set(state.asked_questions)
        result = []
        for q in questions:
            if q.question_id not in seen_ids:
                seen_ids.add(q.question_id)
                result.append(q)
            else:
                q.question_id = f"{q.question_id}_v2"
                result.append(q)
        return result[:4]
