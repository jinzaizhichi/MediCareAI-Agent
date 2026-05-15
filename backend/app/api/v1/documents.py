"""Document upload and multimodal parsing endpoints.

POST   /api/v1/documents/upload       — Upload a file for parsing
GET    /api/v1/documents/{id}/result  — Poll for parse results
DELETE /api/v1/documents/{id}         — Delete a file and its result

All parsing is handled by LabReportParser (multimodal_parser.py) using
Kimi k2.5/k2.6 vision API for images and /v1/files for text documents.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserContext
from app.db.session import AsyncSessionLocal, get_db
from app.services.document_router import (
    MAX_UPLOAD_SIZE,
    ParseMethod,
    classify_file,
    is_image_format,
    is_text_format,
)
from app.services.llm import get_llm_service
from app.services.multimodal_parser import LabReportParser

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory store for parsing tasks (Phase 1: simple dict)
# In production, replace with Redis or database table.
# ---------------------------------------------------------------------------
_parse_tasks: dict[str, dict[str, Any]] = {}


def _generate_file_id(filename: str, user_id: str) -> str:
    """Generate a short unique file ID."""
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    name_hash = hashlib.sha256(f"{ts}{filename}{user_id}".encode()).hexdigest()[:12]
    return f"doc_{name_hash}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    ctx: CurrentUserContext,
    file: UploadFile = File(..., description="Medical report file (image or document)"),
) -> dict:
    """Upload a medical report file for multimodal parsing.

    Supported formats:
    - Images: jpeg, png, webp, gif (→ Kimi vision API)
    - Documents: pdf, doc, docx, txt, csv, md, ppt, pptx, xls, xlsx (→ Kimi /v1/files)

    Max file size: 10 MB.

    Returns a file_id for polling the parse result via GET /documents/{id}/result.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Validate format
    try:
        parse_method = classify_file(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Read file bytes
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {len(file_bytes)} bytes. Max: {MAX_UPLOAD_SIZE} bytes.",
        )

    file_id = _generate_file_id(file.filename, ctx.user.id.hex if ctx.user else "guest")

    # Store task state
    _parse_tasks[file_id] = {
        "status": "processing",
        "filename": file.filename,
        "parse_method": parse_method.value,
        "created_at": datetime.utcnow().isoformat(),
        "bytes": file_bytes,
        "result": None,
        "error": None,
    }

    # Launch async parse in background
    asyncio.create_task(_run_parse(file_id, file_bytes, file.filename))

    return {
        "file_id": file_id,
        "filename": file.filename,
        "parse_method": parse_method.value,
        "status": "processing",
    }


@router.get("/{file_id}/result")
async def get_parse_result(file_id: str) -> dict:
    """Poll for document parsing result.

    Returns:
        {"status": "processing"} — still parsing
        {"status": "completed", "result": LabReportResult} — done
        {"status": "failed", "error": "..."} — parsing failed
    """
    task = _parse_tasks.get(file_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Document '{file_id}' not found")

    status_val = task["status"]
    response: dict[str, Any] = {"status": status_val, "file_id": file_id}

    if status_val == "completed":
        response["result"] = task["result"]
    elif status_val == "failed":
        response["error"] = task.get("error", "Unknown error")

    return response


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(file_id: str):
    """Delete a document and its parse result."""
    if file_id not in _parse_tasks:
        raise HTTPException(status_code=404, detail=f"Document '{file_id}' not found")
    del _parse_tasks[file_id]


# ---------------------------------------------------------------------------
# Background parsing
# ---------------------------------------------------------------------------


async def _run_parse(file_id: str, file_bytes: bytes, filename: str) -> None:
    """Background task: parse the uploaded file and store the result."""
    task = _parse_tasks.get(file_id)
    if not task:
        return

    try:
        async with AsyncSessionLocal() as db:
            try:
                # Classify and parse
                if is_image_format(filename):
                    result = await _parse_image(db, file_bytes, file_id)
                elif is_text_format(filename):
                    result = await _parse_text_document(db, file_bytes, filename, file_id)
                else:
                    task["status"] = "failed"
                    task["error"] = f"Unsupported format: {filename}"
                    return

                task["status"] = "completed"
                task["result"] = result
            finally:
                await db.close()
    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)


async def _parse_image(db: AsyncSession, image_bytes: bytes, file_id: str) -> dict:
    """Parse an image via Kimi vision API."""
    llm = await get_llm_service(db, model_type="multimodal")
    parser = LabReportParser(llm)
    result = await parser.parse_image(image_bytes, file_id)
    return result.model_dump()


async def _parse_text_document(
    db: AsyncSession, file_bytes: bytes, filename: str, file_id: str
) -> dict:
    """Parse a text document via Kimi /v1/files file-extract + LLM structured extraction."""
    import io

    from openai import AsyncOpenAI

    # Get the multimodal provider config for file upload
    llm = await get_llm_service(db, model_type="multimodal")
    client = await llm._get_client()

    # Determine purpose based on file type
    from pathlib import Path
    ext = Path(filename).suffix.lower()

    # Upload to Kimi /v1/files
    file_obj = await asyncio.wait_for(
        client.files.create(
            file=(filename, io.BytesIO(file_bytes), "application/octet-stream"),
            purpose="file-extract",
        ),
        timeout=30.0,
    )

    try:
        # Extract content
        content_response = await client.files.content(file_id=file_obj.id)
        extracted_text = content_response.text

        # Use structured extraction LLM to parse the medical report
        extract_llm = await get_llm_service(db, model_type="structured_extraction")
        response = await extract_llm.chat(
            messages=[{
                "role": "user",
                "content": (
                    f"从以下医疗报告中提取所有检测指标为JSON数组格式：\n\n{extracted_text}\n\n"
                    "对每个指标输出JSON对象，包含：\n"
                    '- indicator_name: 指标的标准中文名称\n'
                    '- value: 检测数值（数字或文本）\n'
                    '- unit: 单位\n'
                    '- reference_range: 参考范围\n'
                    '- abnormal: 是否异常\n'
                    '- abnormal_direction: "high"或"low"\n'
                    '- confidence: 置信度(0.0-1.0)\n\n'
                    '返回格式：{"indicators": [...], "overall_confidence": 0.95}'
                ),
            }],
            max_tokens=4096,
        )

        # Parse the JSON response
        from app.services.multimodal_parser import LabReportParser, LabReportResult
        parser = LabReportParser(llm)  # reusing llm for normalization only
        indicators_raw = parser._extract_json_array(response.content)
        result = LabReportResult(file_id=file_id, raw_response=extracted_text)

        if indicators_raw:
            indicators = []
            total_conf = 0.0
            for item in indicators_raw:
                ind = parser._normalize_indicator(item)
                indicators.append(ind)
                total_conf += ind.confidence

            result.indicators = indicators
            if indicators:
                result.overall_confidence = round(total_conf / len(indicators), 2)
            result.requires_manual_review = result.overall_confidence < LabReportParser.CONFIDENCE_THRESHOLD
        else:
            result.error = "未能从文档中提取到检测指标"
            result.requires_manual_review = True

        return result.model_dump()

    finally:
        # Clean up file on Kimi servers
        try:
            await client.files.delete(file_id=file_obj.id)
        except Exception:
            pass
