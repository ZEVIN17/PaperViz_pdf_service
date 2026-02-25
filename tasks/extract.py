"""
Celery 任务: 使用 PyMuPDF 提取 PDF 文本。

工作流程
--------
1. 从 R2 / URL 下载 PDF
2. 校验文件（MIME 类型、大小 <= 100 MB、页数 <= 500）
3. 使用 PyMuPDF 提取文本
4. 将提取的文本上传到 R2
5. 更新 Supabase -> status = completed

⚠️ 本模块 import PyMuPDF (fitz)，受 AGPL-3.0 约束。

重试策略: 对瞬态错误最多自动重试 2 次。
校验失败立即拒绝（不重试）。
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF — AGPL-3.0
from celery import Task
from celery.exceptions import Reject, SoftTimeLimitExceeded

from celery_app import celery_app
from config import PDF_EXTRACT_MAX_FILE_SIZE, PDF_EXTRACT_MAX_PAGES
from exceptions import (
    ExtractionError,
    FileValidationError,
    StorageError,
)
from services.r2_storage import download_pdf, upload_text
from services.supabase_client import upsert_extract, mark_failed

logger = logging.getLogger("pdf_service.tasks.extract")


# ── 文件校验 ──────────────────────────────────────────

def _validate_pdf(pdf_bytes: bytes) -> int:
    """
    校验下载的 PDF。

    返回页数。
    如果无效则抛出 FileValidationError（不可重试）。
    """
    size_mb = len(pdf_bytes) / (1024 * 1024)
    max_mb = PDF_EXTRACT_MAX_FILE_SIZE / (1024 * 1024)
    if len(pdf_bytes) > PDF_EXTRACT_MAX_FILE_SIZE:
        raise FileValidationError(
            f"文件过大: {size_mb:.1f}MB (上限 {max_mb:.0f}MB)"
        )

    if not pdf_bytes[:5] == b"%PDF-":
        raise FileValidationError("不是有效的 PDF 文件")

    # 使用临时文件而不是内存流，避免大文件导致 OOM
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(pdf_bytes)
        tmp_file_path = tmp_file.name

    try:
        doc = fitz.open(tmp_file_path)
        page_count = len(doc)
        doc.close()
    except Exception as e:
        os.remove(tmp_file_path)
        raise FileValidationError(f"无法读取 PDF: {e}")

    # 删除临时文件
    os.remove(tmp_file_path)

    if page_count == 0:
        raise FileValidationError("PDF 没有页面")
    if page_count > PDF_EXTRACT_MAX_PAGES:
        raise FileValidationError(
            f"页数过多: {page_count} 页 (上限 {PDF_EXTRACT_MAX_PAGES} 页)"
        )

    return page_count


# ── PDF 文本提取 ────────────────────────────────────

def _extract_text_with_pymupdf(pdf_bytes: bytes, paper_id: str) -> tuple[str, int]:
    """
    使用 PyMuPDF 提取 PDF 文本。

    返回: (提取的文本, 页数)
    """
    logger.info(f"[PyMuPDF] Starting extraction for paper {paper_id}")

    # 使用临时文件而不是内存流，避免大文件导致 OOM
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(pdf_bytes)
        tmp_file_path = tmp_file.name

    try:
        doc = fitz.open(tmp_file_path)
        full_text = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            # 提取文本并保留基本格式
            text = page.get_text("text")
            if text.strip():
                full_text.append(f"\n--- Page {page_num + 1} ---\n{text}\n")

        combined_text = "\n".join(full_text)

        # 注意：必须先记录日志再关闭文档，因为关闭后无法获取页数
        page_count = len(doc)
        doc.close()

        logger.info(
            f"[PyMuPDF] Extraction completed for paper {paper_id}, "
            f"{page_count} pages, {len(combined_text)} chars"
        )
        return combined_text, page_count

    except Exception as e:
        logger.error(f"[PyMuPDF] Extraction failed for paper {paper_id}: {e}")
        raise ExtractionError(f"PyMuPDF 提取失败: {e}")
    finally:
        # 确保删除临时文件
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)


# ── Celery 任务 ──────────────────────────────────────

@celery_app.task(
    bind=True,
    name="tasks.extract_pdf",
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
    acks_late=True,
    reject_on_worker_lost=True,
)
def extract_pdf_task(
    self: Task,
    paper_id: str,
    file_url: str,
    mode: str = "text",
) -> dict:
    """
    使用 PyMuPDF 提取 PDF 文本的主流水线。

    Parameters
    ----------
    paper_id : str
        ``papers`` 表中论文的 UUID。
    file_url : str
        指向原始 PDF 的 R2 key 或完整 URL。
    mode : str
        ``"text"``（纯文本）或 ``"markdown"``（保留格式）。

    Returns
    -------
    dict
        提取结果: {paper_id, status, text_length, text_url}
    """
    attempt = self.request.retries + 1
    logger.info(
        f"[{paper_id}] Starting PDF extraction "
        f"(mode={mode}, attempt={attempt}/{self.max_retries + 1})"
    )

    try:
        # ── 步骤 1: 标记下载中 ─────────────────
        upsert_extract(paper_id, {
            "status": "downloading",
            "celery_task_id": self.request.id,
            "extract_mode": mode,
            "retry_count": self.request.retries,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "error_message": None,
        })

        logger.info(f"[{paper_id}] Downloading PDF …")
        pdf_bytes = download_pdf(file_url)
        logger.info(f"[{paper_id}] Downloaded {len(pdf_bytes)} bytes")

        # ── 步骤 2: 校验 ─────────────────────────
        page_count = _validate_pdf(pdf_bytes)
        logger.info(
            f"[{paper_id}] Validation OK — "
            f"{page_count} pages, {len(pdf_bytes) / 1024 / 1024:.1f} MB"
        )

        # ── 步骤 3: 提取文本 ─────────────────────
        upsert_extract(paper_id, {
            "status": "extracting",
            "progress_percent": 50,
            "page_count": page_count,
        })

        logger.info(f"[{paper_id}] Starting PyMuPDF extraction …")
        extracted_text, page_count = _extract_text_with_pymupdf(pdf_bytes, paper_id)
        text_length = len(extracted_text)

        logger.info(
            f"[{paper_id}] Extracted {text_length} chars from {page_count} pages"
        )

        # ── 步骤 4: 上传到 R2 ─────────────────────
        upsert_extract(paper_id, {
            "status": "uploading",
            "progress_percent": 80,
        })

        r2_key = f"papers/{paper_id}/extracted_text.txt"
        text_url = upload_text(extracted_text, r2_key)
        logger.info(f"[{paper_id}] Uploaded text to R2: {r2_key}")

        # ── 步骤 5: 完成 ─────────────────────────
        upsert_extract(paper_id, {
            "status": "completed",
            "progress_percent": 100,
            "page_count": page_count,
            "text_length": text_length,
            "text_url": text_url,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error_message": None,
        })

        logger.info(
            f"[{paper_id}] Extraction completed "
            f"({page_count} pages, {text_length} chars)"
        )
        return {
            "paper_id": paper_id,
            "status": "completed",
            "page_count": page_count,
            "text_length": text_length,
            "text_url": text_url,
        }

    # ── 错误处理 ────────────────────────────────────

    except FileValidationError as e:
        logger.error(f"[{paper_id}] Validation failed: {e}")
        mark_failed(paper_id, str(e))
        raise Reject(str(e), requeue=False)

    except SoftTimeLimitExceeded:
        logger.error(f"[{paper_id}] Task timed out (>5 min)")
        mark_failed(paper_id, "提取超时 (超过 5 分钟)")
        raise

    except (ExtractionError, StorageError) as e:
        logger.error(
            f"[{paper_id}] Retryable error (attempt {attempt}): {e}"
        )
        if self.request.retries >= self.max_retries:
            mark_failed(
                paper_id,
                f"提取失败 (已重试 {self.max_retries} 次): {e}",
            )
            raise
        upsert_extract(paper_id, {
            "retry_count": self.request.retries + 1,
            "error_message": f"正在重试 … ({e})",
        })
        raise self.retry(exc=e)

    except Exception as e:
        logger.error(f"[{paper_id}] Unexpected error: {e}", exc_info=True)
        if self.request.retries >= self.max_retries:
            mark_failed(paper_id, f"未知错误: {e}")
            raise
        raise self.retry(exc=e)
