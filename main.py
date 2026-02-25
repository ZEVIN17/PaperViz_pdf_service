"""
PaperViz PDF Service v1.0（独立PDF提取微服务）
====================================================
独立于主 python_service 的 PDF 提取微服务。
所有依赖 PyMuPDF（AGPL-3.0）的代码集中在本服务中。

FastAPI Web 层接收提取请求、校验参数、分发 Celery 异步任务，
并提供状态查询/取消接口。

实际 PDF 文本提取由 PyMuPDF (fitz) 在 Celery Worker 进程内执行。

启动:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import logging
import os
from functools import wraps

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from celery_app import celery_app
from config import INTERNAL_API_KEY
from schemas.extract import (
    CancelResponse,
    ExtractRequest,
    ExtractResponse,
    ExtractStatusResponse,
)
from services.supabase_client import (
    get_extract,
    mark_cancelled,
    upsert_extract,
)
from tasks.extract import extract_pdf_task

# ── 日志 ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pdf_service.main")

# ── 限流 ──────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── 内部 API 鉴权 ─────────────────────────────────────
def verify_internal_token(request: Request) -> bool:
    """
    验证内部 API 密钥。
    
    检查请求头 X-Internal-Token 是否与服务端配置的 INTERNAL_API_KEY 匹配。
    如果未配置 INTERNAL_API_KEY，则跳过验证（仅用于开发环境）。
    """
    if not INTERNAL_API_KEY:
        # 未配置密钥，跳过验证（仅开发环境使用）
        logger.warning("INTERNAL_API_KEY 未配置，已跳过鉴权验证")
        return True
    
    auth_header = request.headers.get("X-Internal-Token")
    if not auth_header:
        return False
    
    return auth_header == INTERNAL_API_KEY


async def require_internal_auth(request: Request, response: Response):
    """内部 API 认证依赖项，用于 FastAPI 路由保护。"""
    if not verify_internal_token(request):
        logger.warning(f"内部 API 鉴权失败: 缺少或无效的 X-Internal-Token 头")
        raise HTTPException(
            status_code=401,
            detail="缺少有效的内部认证凭证"
        )

# ── FastAPI 应用 ─────────────────────────────────────
app = FastAPI(
    title="PaperViz PDF Service",
    version="1.0.0",
    description="独立 PDF 提取微服务 — PyMuPDF 文本提取（AGPL-3.0 隔离）",
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "请求过于频繁，请稍后再试。"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 健康检查 ──────────────────────────────────────────

@app.get("/health")
async def health():
    """服务健康状态 + 依赖检查。"""
    # 检查 PyMuPDF 是否可导入
    pymupdf_ok = False
    pymupdf_version = "unknown"
    try:
        import fitz
        pymupdf_version = fitz.__doc__.strip() if fitz.__doc__ else "unknown"
        pymupdf_ok = True
    except ImportError:
        pass

    # 检查 Celery Worker 状态
    celery_ok = False
    try:
        inspector = celery_app.control.inspect(timeout=3)
        workers = inspector.ping()
        celery_ok = bool(workers)
    except Exception:
        pass

    overall = "ok" if (pymupdf_ok and celery_ok) else "degraded"
    return {
        "status": overall,
        "service": "paperviz-pdf",
        "version": "1.0.0",
        "pymupdf": {
            "version": pymupdf_version,
            "available": pymupdf_ok,
            "mode": "in-process (Python API)",
        },
        "celery": {"healthy": celery_ok},
    }


# ── POST /extract ───────────────────────────────────

@app.post("/extract", response_model=ExtractResponse)
@limiter.limit("10/minute")
async def start_extraction(req: ExtractRequest, request: Request, response: Response):
    """提交新提取任务（或返回已有进度）。"""
    # 内部 API 鉴权
    await require_internal_auth(request, response)
    
    logger.info(
        f"POST /extract — paper_id={req.paper_id}, mode={req.mode}"
    )

    # 检查是否有已有提取记录
    existing = get_extract(req.paper_id)
    if existing:
        # 检查模式是否一致
        existing_mode = existing.get("extract_mode")
        if existing_mode == req.mode:
            status = existing.get("status", "")
            if status == "completed":
                return ExtractResponse(
                    success=True,
                    paper_id=req.paper_id,
                    message="提取已完成",
                )
            if status in ("queued", "downloading", "extracting", "uploading",
                          "pending"):
                return ExtractResponse(
                    success=True,
                    celery_task_id=existing.get("celery_task_id"),
                    paper_id=req.paper_id,
                    message=f"提取进行中 (状态: {status})",
                )

    # 创建初始数据库记录
    upsert_extract(req.paper_id, {
        "status": "queued",
        "extract_mode": req.mode,
        "error_message": None,
        "progress_percent": 0,
    })

    # 分发 Celery 任务
    task = extract_pdf_task.apply_async(
        kwargs={
            "paper_id": req.paper_id,
            "file_url": req.file_url,
            "mode": req.mode,
        },
    )

    upsert_extract(req.paper_id, {"celery_task_id": task.id})

    logger.info(f"[{req.paper_id}] Celery task dispatched → {task.id}")
    return ExtractResponse(
        success=True,
        celery_task_id=task.id,
        paper_id=req.paper_id,
        message="提取任务已提交",
    )


# ── GET /extract/status/{paper_id} ─────────────────

@app.get(
    "/extract/status/{paper_id}",
    response_model=ExtractStatusResponse,
)
async def get_extract_status(paper_id: str, request: Request, response: Response):
    """查询当前提取状态和进度。"""
    # 内部 API 鉴权
    await require_internal_auth(request, response)
    
    record = get_extract(paper_id)
    if not record:
        return ExtractStatusResponse(
            paper_id=paper_id, status="not_found"
        )

    return ExtractStatusResponse(
        paper_id=paper_id,
        status=record.get("status", "unknown"),
        progress_percent=record.get("progress_percent", 0),
        page_count=record.get("page_count", 0),
        text_length=record.get("text_length", 0),
        error_message=record.get("error_message"),
        celery_task_id=record.get("celery_task_id"),
        started_at=record.get("started_at"),
        completed_at=record.get("completed_at"),
    )


# ── POST /extract/cancel/{paper_id} ────────────────

@app.post(
    "/extract/cancel/{paper_id}",
    response_model=CancelResponse,
)
async def cancel_extraction(paper_id: str, request: Request, response: Response):
    """取消进行中的提取任务。"""
    # 内部 API 鉴权
    await require_internal_auth(request, response)
    
    record = get_extract(paper_id)
    if not record:
        raise HTTPException(status_code=404, detail="提取记录不存在")

    status = record.get("status", "")
    if status in ("completed", "failed", "cancelled"):
        return CancelResponse(
            success=False,
            message=f"无法取消: 当前状态为 {status}",
        )

    # 撤销 Celery 任务
    celery_task_id = record.get("celery_task_id")
    if celery_task_id:
        celery_app.control.revoke(celery_task_id, terminate=True)
        logger.info(f"[{paper_id}] Celery task {celery_task_id} revoked")

    mark_cancelled(paper_id)
    return CancelResponse(success=True, message="提取任务已取消")


# ── 入口点 ───────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"PDF Service v1.0 starting on :{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
