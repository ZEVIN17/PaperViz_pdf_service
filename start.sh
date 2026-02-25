#!/bin/bash
# ============================================
# PaperViz PDF Service 启动脚本
# 同时启动 FastAPI 和 Celery Worker
# ============================================

set -e

echo "[PDF Service] Starting FastAPI and Celery Worker..."

# 启动 Celery Worker（后台运行）
celery -A celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    -Q pdf_extract_queue &

# 等待一下让 Celery Worker 启动
sleep 3

# 启动 FastAPI（前台运行）
uvicorn main:app --host 0.0.0.0 --port 8000
