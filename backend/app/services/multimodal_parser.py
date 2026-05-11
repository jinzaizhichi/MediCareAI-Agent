"""
Multimodal medical report parser using Kimi k2.6 native vision capability.

Parses lab report images into structured JSON with LOINC mapping,
abnormal value flagging, and confidence-based manual review gating.
"""

import base64
import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.services.llm import LLMService

logger = logging.getLogger("multimodal.parser")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LabIndicator(BaseModel):
    indicator_name: str = Field(description="Standard Chinese name of the test indicator")
    value: float | str = Field(description="Numeric or textual result value")
    unit: str = Field(default="")
    reference_range: str = Field(default="", description="Normal range, e.g. '3.5-5.5'")
    abnormal: bool = Field(default=False)
    abnormal_direction: Optional[str] = Field(default=None, description="'high' or 'low' or null")
    loinc_code: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class LabReportResult(BaseModel):
    file_id: str = Field(default="")
    indicators: list[LabIndicator] = Field(default_factory=list)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_manual_review: bool = Field(default=False)
    raw_response: str = Field(default="")
    error: str = Field(default="")


# ---------------------------------------------------------------------------
# LOINC code lookup for common Chinese lab tests
# ---------------------------------------------------------------------------

LOINC_MAP: dict[str, str] = {
    "白细胞计数": "6690-2",
    "白细胞": "6690-2",
    "WBC": "6690-2",
    "红细胞计数": "789-8",
    "红细胞": "789-8",
    "RBC": "789-8",
    "血红蛋白": "718-7",
    "Hb": "718-7",
    "HGB": "718-7",
    "红细胞比容": "4544-3",
    "HCT": "4544-3",
    "血小板计数": "777-3",
    "血小板": "777-3",
    "PLT": "777-3",
    "中性粒细胞百分比": "770-8",
    "淋巴细胞百分比": "736-9",
    "单核细胞百分比": "5905-5",
    "嗜酸性粒细胞百分比": "713-8",
    "嗜碱性粒细胞百分比": "706-2",
    "C反应蛋白": "1988-5",
    "CRP": "1988-5",
    "超敏C反应蛋白": "30522-7",
    "hs-CRP": "30522-7",
    "血糖": "2345-7",
    "空腹血糖": "1558-6",
    "GLU": "2345-7",
    "谷丙转氨酶": "1742-6",
    "ALT": "1742-6",
    "谷草转氨酶": "1920-8",
    "AST": "1920-8",
    "总胆红素": "1975-2",
    "TBIL": "1975-2",
    "直接胆红素": "1968-7",
    "DBIL": "1968-7",
    "总蛋白": "2885-2",
    "白蛋白": "1751-7",
    "ALB": "1751-7",
    "肌酐": "2160-0",
    "CREA": "2160-0",
    "Cr": "2160-0",
    "尿素氮": "3094-0",
    "BUN": "3094-0",
    "尿酸": "3084-1",
    "UA": "3084-1",
    "总胆固醇": "2093-3",
    "TC": "2093-3",
    "甘油三酯": "2571-8",
    "TG": "2571-8",
    "高密度脂蛋白": "2085-9",
    "HDL": "2085-9",
    "HDL-C": "2085-9",
    "低密度脂蛋白": "2089-1",
    "LDL": "2089-1",
    "LDL-C": "2089-1",
    "钠": "2951-2",
    "钾": "2823-3",
    "氯": "2075-0",
    "钙": "17861-6",
    "促甲状腺激素": "3016-3",
    "TSH": "3016-3",
    "游离T3": "3051-0",
    "FT3": "3051-0",
    "游离T4": "3024-7",
    "FT4": "3024-7",
    "糖化血红蛋白": "4548-4",
    "HbA1c": "4548-4",
    "尿蛋白": "2888-6",
    "尿糖": "25428-4",
    "尿潜血": "5794-3",
    "尿白细胞": "5821-4",
    "尿红细胞": "13946-3",
    "乙肝表面抗原": "5196-1",
    "HBsAg": "5196-1",
    "乙肝表面抗体": "5195-3",
    "HBsAb": "5195-3",
    "乙肝e抗原": "5193-8",
    "HBeAg": "5193-8",
    "乙肝e抗体": "5192-0",
    "HBeAb": "5192-0",
    "乙肝核心抗体": "5187-0",
    "HBcAb": "5187-0",
    "HIV抗体": "31201-7",
    "梅毒抗体": "24312-0",
    "D-二聚体": "48065-7",
    "凝血酶原时间": "5902-2",
    "PT": "5902-2",
    "活化部分凝血活酶时间": "3183-1",
    "APTT": "3183-1",
    "降钙素原": "33959-8",
    "PCT": "33959-8",
    "肌钙蛋白I": "42757-5",
    "cTnI": "42757-5",
    "肌酸激酶": "2157-6",
    "CK": "2157-6",
    "肌酸激酶同工酶": "13969-1",
    "CK-MB": "13969-1",
    "乳酸脱氢酶": "2532-0",
    "LDH": "2532-0",
    "淀粉酶": "1798-8",
    "AMY": "1798-8",
    "脂肪酶": "3040-3",
    "LPS": "3040-3",
    "癌胚抗原": "2039-6",
    "CEA": "2039-6",
    "甲胎蛋白": "1834-7",
    "AFP": "1834-7",
    "CA125": "10334-1",
    "CA19-9": "24108-3",
    "PSA": "2857-1",
    "前列腺特异性抗原": "2857-1",
    "维生素D": "1989-3",
    "铁蛋白": "2276-4",
    "叶酸": "2284-8",
    "维生素B12": "2132-9",
    "血沉": "4537-7",
    "ESR": "4537-7",
    "二氧化碳结合力": "2028-9",
    "阴离子间隙": "1863-0",
    "pH": "2746-6",
    "氧分压": "2703-7",
    "二氧化碳分压": "2021-4",
    "碳酸氢根": "1963-8",
    "剩余碱": "1925-7",
}

# Common reference ranges for validation (adult, approximate)
DEFAULT_REFERENCE: dict[str, tuple[float, float, str]] = {
    "白细胞计数": (3.5, 9.5, "10^9/L"),
    "红细胞计数": (4.3, 5.8, "10^12/L"),
    "血红蛋白": (130, 175, "g/L"),
    "血小板计数": (125, 350, "10^9/L"),
    "C反应蛋白": (0, 8.0, "mg/L"),
    "血糖": (3.9, 6.1, "mmol/L"),
    "谷丙转氨酶": (0, 40, "U/L"),
    "谷草转氨酶": (0, 40, "U/L"),
    "总胆红素": (3.4, 17.1, "μmol/L"),
    "肌酐": (44, 133, "μmol/L"),
    "尿素氮": (2.9, 8.2, "mmol/L"),
    "尿酸": (208, 428, "μmol/L"),
    "总胆固醇": (2.8, 5.7, "mmol/L"),
    "甘油三酯": (0.56, 1.7, "mmol/L"),
    "高密度脂蛋白": (1.0, 1.55, "mmol/L"),
    "低密度脂蛋白": (0, 3.37, "mmol/L"),
    "钠": (137, 147, "mmol/L"),
    "钾": (3.5, 5.3, "mmol/L"),
    "氯": (99, 110, "mmol/L"),
    "钙": (2.11, 2.52, "mmol/L"),
    "促甲状腺激素": (0.35, 4.94, "mIU/L"),
    "游离T3": (3.5, 6.5, "pmol/L"),
    "游离T4": (11.5, 22.7, "pmol/L"),
    "糖化血红蛋白": (4.0, 6.0, "%"),
}


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------

class LabReportParser:
    """Parse lab report images using Kimi k2.6 native vision capability."""

    CONFIDENCE_THRESHOLD = 0.7

    SYSTEM_PROMPT = (
        "你是医学检验报告分析专家。从化验单图片中提取所有检测指标，返回结构化JSON。"
        "对每个指标提供：指标标准中文名、数值、单位、参考范围、是否异常、异常方向(high/low)、置信度(0-1)。"
        "只返回有效的JSON数组，不要添加额外文字。"
    )

    def __init__(self, llm: LLMService):
        self.llm = llm

    async def parse_image(self, image_data: bytes, file_id: str = "") -> LabReportResult:
        """Parse a lab report image into structured indicators.

        Args:
            image_data: Raw image bytes (JPEG/PNG).
            file_id: Optional identifier for the uploaded file.

        Returns:
            LabReportResult with extracted indicators and confidence assessment.
        """
        base64_image = base64.b64encode(image_data).decode("utf-8")
        mime_type = self._detect_mime(image_data)

        vision_message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "请分析这张化验单/检查报告图片，提取所有检测指标。\n\n"
                        "对每个指标输出JSON对象，包含：\n"
                        "- indicator_name: 指标的标准中文名称\n"
                        "- value: 检测数值（数字或文本）\n"
                        "- unit: 单位\n"
                        "- reference_range: 参考范围（如图上标注了的话）\n"
                        "- abnormal: 是否异常（基于参考范围判断）\n"
                        "- abnormal_direction: \"high\"或\"low\"（异常方向，正常则为null）\n"
                        "- confidence: 你对该指标提取的置信度(0.0-1.0)\n\n"
                        "返回格式：JSON数组，如 [{\"indicator_name\":\"白细胞计数\",\"value\":7.5,...}]"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{base64_image}"},
                },
            ],
        }

        result = LabReportResult(file_id=file_id)

        try:
            response = await self.llm.chat(
                messages=[vision_message],
                system_prompt=self.SYSTEM_PROMPT,
                max_tokens=4096,
            )
            result.raw_response = response.content

            indicators_raw = self._extract_json_array(response.content)
            if not indicators_raw:
                result.error = "未能从图片中解析出检测指标"
                result.requires_manual_review = True
                return result

            indicators = []
            total_confidence = 0.0
            for item in indicators_raw:
                indicator = self._normalize_indicator(item)
                indicators.append(indicator)
                total_confidence += indicator.confidence

            result.indicators = indicators
            if indicators:
                result.overall_confidence = round(total_confidence / len(indicators), 2)

            result.requires_manual_review = (
                result.overall_confidence < self.CONFIDENCE_THRESHOLD
                or not indicators
            )

        except Exception as e:
            logger.error(f"Lab report parsing failed: {e}", exc_info=True)
            result.error = str(e)
            result.requires_manual_review = True

        return result

    def _normalize_indicator(self, raw: dict) -> LabIndicator:
        """Normalize and enrich a raw indicator dict from LLM output."""
        name = str(raw.get("indicator_name", "")).strip()
        value = raw.get("value")
        unit = str(raw.get("unit", "")).strip()
        ref_range = str(raw.get("reference_range", "")).strip()
        abnormal = bool(raw.get("abnormal", False))
        direction = raw.get("abnormal_direction")
        confidence = float(raw.get("confidence", 0.5))

        # Try numeric conversion
        numeric_value = self._try_numeric(value)

        # If abnormal not set, check against known reference range
        if not abnormal and numeric_value is not None and name:
            abnormal, direction = self._check_abnormal(name, numeric_value)

        # Lookup LOINC code
        loinc = self._lookup_loinc(name)

        return LabIndicator(
            indicator_name=name,
            value=numeric_value if numeric_value is not None else value,
            unit=unit,
            reference_range=ref_range,
            abnormal=abnormal,
            abnormal_direction=direction,
            loinc_code=loinc,
            confidence=min(max(confidence, 0.0), 1.0),
        )

    @staticmethod
    def _try_numeric(value) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "").replace(" ", "")
            cleaned = cleaned.lstrip("<>≤≥≈").replace("×10^", "e").replace("＊", "")
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @staticmethod
    def _lookup_loinc(name: str) -> str:
        """Lookup LOINC code by indicator name (exact or fuzzy)."""
        if not name:
            return ""
        # Exact match
        if name in LOINC_MAP:
            return LOINC_MAP[name]
        # Substring match
        for key, code in LOINC_MAP.items():
            if key in name or name in key:
                return code
        return ""

    @staticmethod
    def _check_abnormal(name: str, value: float) -> tuple[bool, Optional[str]]:
        """Check value against known default reference range."""
        ref = DEFAULT_REFERENCE.get(name)
        if ref is None:
            # Try fuzzy match
            for key, r in DEFAULT_REFERENCE.items():
                if key in name or name in key:
                    ref = r
                    break
        if ref is None:
            return False, None

        low, high, _unit = ref
        if value < low:
            return True, "low"
        if value > high:
            return True, "high"
        return False, None

    @staticmethod
    def _detect_mime(data: bytes) -> str:
        """Detect image MIME type from magic bytes."""
        if data[:4] == b"\x89PNG":
            return "image/png"
        if data[:2] == b"\xff\xd8":
            return "image/jpeg"
        if data[:4] == b"GIF8":
            return "image/gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        return "image/jpeg"

    @staticmethod
    def _extract_json_array(text: str) -> list[dict]:
        """Extract JSON array from LLM response text."""
        if not text:
            return []
        text = text.strip()
        # Try direct parse
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass
        # Try extracting from markdown code blocks
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                return json.loads(text[start:end].strip())
            except json.JSONDecodeError:
                pass
        if "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                return json.loads(text[start:end].strip())
            except json.JSONDecodeError:
                pass
        # Try extracting array brackets
        bracket_start = text.find("[")
        bracket_end = text.rfind("]")
        if bracket_start >= 0 and bracket_end > bracket_start:
            try:
                data = json.loads(text[bracket_start:bracket_end + 1])
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass
        return []
