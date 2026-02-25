"""
PDF 提取 API 的 Pydantic 模型。
"""

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class ExtractRequest(BaseModel):
    """POST /extract 的请求体"""
    paper_id: str
    file_url: str
    mode: Literal["text", "markdown"] = "text"

    @field_validator("paper_id")
    @classmethod
    def validate_paper_id(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("paper_id must be a valid UUID")
        return v


class ExtractResponse(BaseModel):
    """POST /extract 的响应"""
    success: bool
    celery_task_id: Optional[str] = None
    paper_id: str
    message: str


class ExtractStatusResponse(BaseModel):
    """GET /extract/status/{paper_id} 的响应"""
    paper_id: str
    status: str
    progress_percent: int = 0
    page_count: int = 0
    text_length: int = 0
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class CancelResponse(BaseModel):
    """POST /extract/cancel/{paper_id} 的响应"""
    success: bool
    message: str
