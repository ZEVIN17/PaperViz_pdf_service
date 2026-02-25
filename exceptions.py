"""
PDF Service 异常定义。
"""


class PDFServiceError(Exception):
    """基础异常类。"""
    pass


class FileValidationError(PDFServiceError):
    """文件校验失败（不可重试）。"""
    pass


class ExtractionError(PDFServiceError):
    """PDF 提取失败（可重试）。"""
    pass


class StorageError(PDFServiceError):
    """存储相关错误。"""
    pass
