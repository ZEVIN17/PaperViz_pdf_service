"""
Celery 应用配置。

该模块同时被 FastAPI Web 进程（提交任务）和 Celery Worker 进程（执行任务）引入。

启动 Worker:
    celery -A celery_app worker --loglevel=info --concurrency=4 -Q pdf_extract_queue
"""

from celery import Celery
from config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery_app = Celery(
    "pdf_service",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["tasks.extract"],
)

# 队列配置
celery_app.conf.update(
    task_routes={
        'tasks.extract_pdf': {
            'queue': 'pdf_extract_queue',
        },
    },
    task_default_queue='pdf_extract_queue',
    task_default_exchange='pdf_extract',
    task_default_routing_key='pdf_extract',

    # Pool: solo 避免 daemon workers；PyMuPDF 解析是 CPU 密集型
    worker_pool="solo",

    # 序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 时区
    timezone="UTC",
    enable_utc=True,

    # 可靠性
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,

    # 超时（秒）
    task_soft_time_limit=300,   # 5 分钟软超时
    task_time_limit=360,       # 6 分钟硬超时

    # Broker
    broker_connection_retry_on_startup=True,

    # 结果过期时间
    result_expires=3600,        # 1 小时
)
