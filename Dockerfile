# ============================================
# PaperViz PDF Service v1.0
# 独立 PDF 提取微服务（AGPL-3.0 隔离）
# FastAPI (web) + Celery (worker) 同镜像
# PyMuPDF 进程内运行
# ============================================

FROM python:3.11-slim

WORKDIR /app

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY config.py celery_app.py exceptions.py main.py ./
COPY schemas/ ./schemas/
COPY services/ ./services/
COPY tasks/ ./tasks/

# 创建临时目录
RUN mkdir -p /tmp/pdf_extract/output

# 非 root 用户
RUN useradd -m -u 1001 appuser && \
    chown -R appuser:appuser /app /tmp/pdf_extract
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

# 默认: 同时启动 FastAPI 和 Celery Worker
COPY start.sh .
CMD ["bash", "start.sh"]
