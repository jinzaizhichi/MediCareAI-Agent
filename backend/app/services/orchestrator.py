"""
Independent Track Agents + Orchestrator for Plan B architecture.

Track1Agent: History collection (standard clinical interview questions).
Track2Agent: Search-driven refinement (generates questions AFTER search results).
InterviewOrchestrator: Coordinates tracks, merges results, manages state.
"""

import asyncio
import json
import logging
from typing import Any

from app.models.interview import (
    InterviewState,
    QuestionTemplate,
    InterviewDecision,
    DifferentialHypothesis,
    PHASE_ORDER,
    _extract_json,
    _fingerprint,
    _extract_phase_key,
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
- 问题口语化，用"您"开头。一律使用 choice 或 multi_choice，选项后附加 "以上都没有" 供患者否定（如慢性病史、过敏史等筛查题）
- 每轮1-2个问题

只返回JSON（```json```包裹）。"""

TRACK1_DECISION_SCHEMA = """返回JSON（示例，请生成真实临床选项）：
{
  "action": "ask",
  "basic_module": [
    {"question_id":"hpi_quality","question":"您颈肩部的疼痛是什么样的感觉？","type":"multi_choice","options":["酸痛","刺痛","胀痛","麻木","僵硬"],"hint":"可多选","allow_skip":true,"phase":"现病史-症状特点","reason":"明确疼痛性质"},
    {"question_id":"hpi_severity","question":"疼痛程度如何？","type":"choice","options":["轻微，不影响活动","中等，转头受限","剧烈，完全无法活动"],"hint":"","allow_skip":false,"phase":"现病史-严重程度","reason":"评估严重程度"}
  ],
  "differential_diagnoses": [{"diagnosis":"颈肩筋膜炎","confidence":"medium","key_features":["晨起加重","活动后缓解"],"reason":"与主诉匹配"}],
  "red_flags": [],
  "covered_dimensions": ["hpi_quality"],
  "reasoning": "基于症状特点推断"
}
重要：multi_choice 的 options 必须是该问题的具体答案选项（≥2个），不允许使用占位符。red_flags 是字符串数组（如["频繁呕吐无法进食"]），不是对象数组。"""


# ---------------------------------------------------------------------------
# Track 2 Agent: Search-Driven Refinement
# ---------------------------------------------------------------------------

TRACK2_SYSTEM_PROMPT = """你是搜索增强问诊专家。基于SearXNG+RAG搜索结果，生成靶向进阶问题。

职责：
- 分析搜索结果中的关键临床线索
- 针对鉴别诊断的confirmed/missing特征设计确认问题
- 搜索发现的证据缺口→设计新问题填补
- 问题量1-2个
- choice 和 multi_choice 类型必须包含至少2个具体选项，筛查类问题附加 "以上都没有"
- 禁止返回空 options 数组

只返回JSON（```json```包裹）。"""

TRACK2_DECISION_SCHEMA = """返回JSON（示例，请生成真实临床选项）：
{
  "advanced_module": [
    {"question_id":"adv_dehydration","question":"有无以下脱水表现？","type":"multi_choice","options":["哭时无泪","尿量减少","眼窝凹陷","口唇干燥","精神萎靡","以上都没有"],"hint":"可多选","allow_skip":true,"reason":"评估脱水程度"},
    {"question_id":"adv_diet","question":"最近饮食有无变化？","type":"choice","options":["正常进食","食量减少","拒食","仅喝水"],"hint":"","allow_skip":true,"reason":"判断进食情况"}
  ]
}
重要：choice 类型必须提供 options（≥2个具体选项），禁止空数组。multi_choice 的 options 最后一项应为 "以上都没有"。"""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


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
            )
            raw = _extract_json(response.content)
            if not raw or not isinstance(raw, dict):
                logger.error("[TRACK1] invalid JSON: %s", response.content[:300])
                return [], [], [], ""
            try:
                decision = InterviewDecision.model_validate(raw)
            except Exception as ve:
                logger.error("[TRACK1] validation: %s\nraw=%s", ve, json.dumps(raw, ensure_ascii=False)[:500])
                return [], [], [], ""
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

        # Show Q&A history for context
        if state.collected_info:
            lines.append("\n## 已收集信息")
            for k, v in list(state.collected_info.items())[-12:]:
                if not k.startswith("__") and v:
                    lines.append(f"- {k}: {str(v)[:120]}")

        pending = [p.value for p in PHASE_ORDER if p.value not in state.collected_info]
        lines.append(f"\n## 还未问的维度\n{', '.join(pending[:8])}")

        lines.append("\n## 指令\n只生成basic_module，每轮1-2个问题。优先覆盖\"还未问的维度\"。")
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
                options=m.options if m.type in ("choice", "multi_choice") else [],
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
            lines.append("\n## 已收集信息")
            for k, v in list(state.collected_info.items())[-8:]:
                if not k.startswith("__") and v:
                    lines.append(f"- {k}: {str(v)[:100]}")
        lines.append("\n## 指令\n只生成advanced_module，0-2个问题。把搜索结果中发现的证据缺口转化为新问题。")
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
                options=m.get("options") if isinstance(m.get("options"), list) else [],
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
        self.logger.info("[DEBUG-DIAG] decide_next: phase=%s regeneration=%d", state.phase, state.regeneration_count or 0)
        if state.phase == "completed":
            if (state.regeneration_count or 0) >= 1:
                self.logger.info("[DEBUG-DIAG] decide_next: regeneration exhausted → action=completed")
                return [], state, [], "completed", ""
            state.phase = "interviewing"
            state.regeneration_count += 1
            self.logger.info("[DEBUG-DIAG] phase=completed, allowing 1 regeneration (#%d)", state.regeneration_count)
            regeneration = True
        else:
            regeneration = False
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

        # Mark Track1 covered dimensions so Track2 sees them
        for q in track1_questions:
            if q.phase and q.phase not in state.collected_info:
                state.collected_info[q.phase] = "asked_by_track1"

        # Process red flags from Track1
        if red_flags:
            for rf in red_flags:
                if rf not in state.red_flags_detected:
                    state.red_flags_detected.append(rf)
            self.logger.warning("[ORCH] RED_FLAGS from Track1: %s", red_flags)

        # Update differential diagnoses from Track1
        if diffs:
            state.set_differential_diagnoses(diffs)

        # Phase 2: Track2 generates with Track1 dimensions visible
        track2_questions = await self.track2.generate(state, search_results, diffs)

        for k in list(state.collected_info.keys()):
            if state.collected_info[k] == "asked_by_track1":
                del state.collected_info[k]

        all_questions = track1_questions + track2_questions
        deduped = self._deduplicate(all_questions, state)

        filtered_out: set[str] = set()
        for q in deduped:
            # Force text-type questions to become multi_choice via LLM option generation
            if q.type == "text":
                opts = await self._complete_options(q)
                if opts and len(opts) >= 2:
                    q.options = opts
                    q.type = "multi_choice"
                else:
                    self.logger.warning("[ORCH] filtering text question — LLM could not generate options: %s", q.question_id)
                    filtered_out.add(q.question_id)
                    continue

            if q.type in ("multi_choice", "choice") and (not q.options or len(q.options) < 2):
                opts = await self._complete_options(q)
                if opts:
                    q.options = opts
                    q.type = "multi_choice"
                elif q.type == "choice" and not q.options:
                    self.logger.warning("[ORCH] filtering choice question with empty options: %s", q.question_id)
                    filtered_out.add(q.question_id)
                    continue
                elif q.type == "choice" and len(q.options) < 2:
                    self.logger.warning("[ORCH] filtering choice question with insufficient options (%d): %s", len(q.options), q.question_id)
                    filtered_out.add(q.question_id)
                    continue
                elif q.type == "multi_choice" and len(q.options) < 2:
                    self.logger.warning("[ORCH] filtering multi_choice question with insufficient options (%d): %s", len(q.options), q.question_id)
                    filtered_out.add(q.question_id)
                    continue
            if q.type == "multi_choice" and q.options and "以上都没有" not in q.options:
                q.options = list(q.options) + ["以上都没有"]
        if filtered_out:
            deduped = [q for q in deduped if q.question_id not in filtered_out]

        # Safety net: strip empty/whitespace-only options
        for q in deduped:
            if q.type in ("choice", "multi_choice") and q.options:
                cleaned = [o for o in q.options if o and str(o).strip()]
                if cleaned != q.options:
                    q.options = cleaned
            if q.type in ("choice", "multi_choice") and len(q.options) < 2:
                self.logger.warning("[ORCH] filtering %s question with insufficient options after cleaning: %s", q.type, q.question_id)
                filtered_out.add(q.question_id)
        if filtered_out:
            deduped = [q for q in deduped if q.question_id not in filtered_out]

        # Phase 4: LLM-driven synthesis decision
        deduped = await self._semantic_dedup(deduped, state)

        if regeneration:
            action = "synthesize"
            state.is_sufficient = True
            state.phase = "completed"
            deduped = []
            self.logger.info("[ORCH] FORCING SYNTHESIZE for regeneration")
            return deduped, state, [], action, reasoning

        if not deduped:
            pending_unanswered = set(state.question_texts.keys()) - set(state.asked_questions)
            if pending_unanswered:
                self.logger.info("[DEBUG-DIAG] deferred synthesize — %d unanswered cards remain", len(pending_unanswered))
                action = "ask"
                return [], state, [], action, reasoning

            # Natural endpoint: dedup says all new questions are duplicates.
            # No more to ask → interview is complete → synthesize.
            # Guard: check if new lab reports arrived since last round. If so,
            # ask one more round so Track1/Track2 can incorporate the new data.
            try:
                from app.api.v1.agents import _session_lab_bridge
                f_sid = state._frontend_sid
                bridge_reports = _session_lab_bridge.get(f_sid, [])
                if len(bridge_reports) > len(state.lab_reports):
                    self.logger.info("[DEBUG-DIAG] defer synthesize — %d new lab reports arrived (state=%d, bridge=%d)",
                                   len(bridge_reports) - len(state.lab_reports),
                                   len(state.lab_reports), len(bridge_reports))
                    state.lab_reports = bridge_reports
                    action = "ask"
                    if all_questions:
                        return all_questions[:2], state, [], action, reasoning
                    return [], state, [], action, reasoning
            except Exception:
                pass

            state.is_sufficient = True
            state.phase = "completed"
            state.regeneration_count = 1
            action = "synthesize"
            self.logger.info("[DEBUG-DIAG] natural endpoint — dedup empty + no pending → synthesize")
            return [], state, [], action, reasoning

        action = "ask"

        for q in deduped:
            fp = _fingerprint(q.question)
            if fp not in state.asked_question_fingerprints:
                state.asked_question_fingerprints.append(fp)
            pk = _extract_phase_key(q.question_id)
            state.question_phase_keys[q.question_id] = pk
            state.question_texts[q.question_id] = q.question

        for q in deduped:
            if q.question_id not in state.asked_questions:
                state.asked_questions.append(q.question_id)
            state.current_question_id = q.question_id
        state.pending_question_ids = [q.question_id for q in deduped]

        return deduped, state, [], action, reasoning

    async def _complete_options(self, q: QuestionTemplate) -> list[str]:
        try:
            r = await self.track1.llm.chat(
                messages=[{"role": "user", "content": f'问题：{q.question}\n针对此问题，列出3-6个具体选项。如果患者可能\"都没有\"，最后加一个\"以上都没有\"选项。只返回JSON数组'}],
                system_prompt="你是临床选项生成助手。只返回JSON数组。", max_tokens=256)
            data = _extract_json(r.content)
            if isinstance(data, list):
                return [str(x) for x in data if x][:6]
            if isinstance(data, dict):
                opts = data.get("options") or data.get("choices") or []
                if isinstance(opts, list):
                    return [str(x) for x in opts if x][:6]
        except Exception:
            pass
        return []

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
            if isinstance(results, dict):
                data = results.get("result", results)
                if isinstance(data, dict):
                    lines = []
                    answer = data.get("answer", "") or ""
                    if answer:
                        lines.append(answer[:1500])
                    sources = data.get("sources", []) or []
                    ext = data.get("external_sources", []) or []
                    all_src = (sources if isinstance(sources, list) else []) + (ext if isinstance(ext, list) else [])
                    for s in all_src[:3]:
                        if isinstance(s, dict):
                            t = s.get("title", "") or ""
                            lines.append(f"- {t}")
                    return "\n".join(lines)[:2000] if lines else ""
                return str(data)[:2000]
            return str(results)[:2000] if results else ""
        except asyncio.TimeoutError:
            self.logger.warning("[ORCH] Search timed out")
            return ""
        except Exception as e:
            self.logger.error(f"[ORCH] Search failed: {e}")
            return ""

    async def _semantic_dedup(
        self, candidates: list[QuestionTemplate], state: InterviewState
    ) -> list[QuestionTemplate]:
        if not candidates or not state.question_texts:
            return candidates
        asked_list = [
            state.question_texts[qid]
            for qid in state.asked_questions[-15:]
            if qid in state.question_texts
        ]
        if not asked_list:
            return candidates
        candidate_texts = [q.question for q in candidates]
        prompt = (
            "判断每个候选问题是否与下面任何一个已问过的问题语义重复"
            "（问的是同一件事，只是换了一种说法）。\n\n"
            f"已问过的问题：\n"
            + "\n".join(f"{i+1}. {t}" for i, t in enumerate(asked_list))
            + f"\n\n候选问题：\n"
            + "\n".join(f"{j+1}. {t}" for j, t in enumerate(candidate_texts))
            + "\n\n返回JSON: {\"keep\": [索引], \"drop\": [索引], \"reasons\": {\"索引\": \"为什么重复或为什么保留\"}}"
            + "\n索引从1开始。keep 是应该保留的全新问题索引，drop 是语义重复应丢弃的索引。"
        )
        try:
            response = await self.track1.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="你是医疗AI去重助手。只返回JSON，不做其他输出。",
                max_tokens=256,
            )
            data = _extract_json(response.content)
            if not isinstance(data, dict):
                return candidates
            drop_indices = {
                int(i) - 1
                for i in (data.get("drop") or [])
                if isinstance(i, (int, float))
            }
            result = [
                q for idx, q in enumerate(candidates) if idx not in drop_indices
            ]
            if len(result) < len(candidates):
                self.logger.info(
                    "[ORCH] semantic_dedup filtered %d/%d questions",
                    len(candidates) - len(result),
                    len(candidates),
                )
            return result
        except Exception as e:
            self.logger.warning("[ORCH] semantic_dedup failed, passing all: %s", e)
            return candidates

    async def _is_diagnosis_active(self) -> bool:
        """Check if a diagnosis is in progress (Redis lock exists)."""
        try:
            from app.db.redis_client import get_redis
            redis_client = get_redis()
            return await redis_client.exists(f"diag_lock:{id(self)}") > 0
        except Exception:
            return False

    @staticmethod
    def _deduplicate(questions: list[QuestionTemplate], state: InterviewState) -> list[QuestionTemplate]:
        seen_phase_keys: set[str] = set(state.question_phase_keys.values())
        result = []
        for q in questions:
            pk = _extract_phase_key(q.question_id)
            if pk in seen_phase_keys:
                continue
            seen_phase_keys.add(pk)
            result.append(q)
        return result[:2]
