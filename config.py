"""
配置文件：集中所有可通过环境变量覆盖的运行参数。
"""

import logging
import os
from typing import Any, Dict

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# OpenAI 兼容 API 配置（默认对齐硅基流动；换服务商只需改这三个环境变量）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "Qwen/Qwen3-8B")

# HTTP 请求配置
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
HTTP_MAX_RETRIES = int(os.getenv("HTTP_MAX_RETRIES", "3"))
HTTP_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "MultiAgentCustomerService/1.0.0",
}

# 系统配置
SYSTEM_NAME = "多智能体客服系统"
VERSION = "1.0.0"

# 日志配置
LOG_CONFIG: Dict[str, Any] = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
}


def setup_logging() -> None:
    """在入口处调用一次，让 LOG_CONFIG 真正生效。"""
    logging.basicConfig(
        level=LOG_CONFIG["level"],
        format=LOG_CONFIG["format"],
    )
