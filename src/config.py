"""
M1 - 配置加载模块
使用 pydantic-settings 加载 YAML + 环境变量

Python 版本要求：>= 3.12（XHS-Downloader 要求）
"""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Python 版本检查（XHS-Downloader 要求 >= 3.12）
if sys.version_info < (3, 12):
    print(
        f"\n[FATAL] Python >= 3.12 is required (XHS-Downloader dependency).\n"
        f"Current version: {sys.version}\n",
        file=sys.stderr,
    )
    sys.exit(1)


class SubscriptionConfig:
    """单个订阅配置（从 YAML 解析，不走 pydantic-settings）"""

    def __init__(self, data: dict):
        self.user_id: Optional[str] = data.get("user_id")
        self.video_url: Optional[str] = data.get("video_url")
        self.name: str = data.get("name", self.user_id or "unknown")
        self.enabled: bool = data.get("enabled", True)

    def __repr__(self) -> str:
        return f"<Subscription name={self.name} user_id={self.user_id} enabled={self.enabled}>"


class AppConfig(BaseSettings):
    """
    应用主配置。
    优先级：环境变量 > YAML 文件 > 默认值
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 必填 ----
    xhs_cookie: str  # 环境变量 XHS_COOKIE

    # ---- 可选 ----
    config_path: str = "/config/config.yaml"
    log_level: str = "INFO"
    http_port: int = 8080

    # ---- 从 YAML 加载的字段（不直接走 env） ----
    interval_hours: float = 6.0
    download_concurrency: int = 3
    download_dir: str = "/data/downloads"
    log_dir: str = "/data/logs"
    subscriptions: List[SubscriptionConfig] = []
    max_batch: int = 30  # 每次抓取博主作品的最大条数（对应 fetcher MAX_BATCH）

    @field_validator("xhs_cookie", mode="before")
    @classmethod
    def validate_cookie(cls, v: str) -> str:
        if not v or not v.strip():
            _fatal(
                "环境变量 XHS_COOKIE 未设置或为空，程序无法启动。\n"
                "请在 docker-compose.yml 或运行环境中设置：\n"
                "  XHS_COOKIE=<从浏览器开发者工具复制的 Cookie 字符串>"
            )
        return v.strip()

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL 必须是 {allowed} 之一，当前值：{v!r}")
        return upper

    @model_validator(mode="after")
    def load_yaml(self) -> "AppConfig":
        """读取 YAML 文件，将 YAML 中的字段合并到配置（环境变量优先）"""
        path = Path(self.config_path)
        if not path.exists():
            logger.warning("配置文件不存在：%s，使用默认值", path)
            return self

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.error("读取配置文件失败：%s，错误：%s", path, exc)
            return self

        # 仅在环境变量未显式设置时，从 YAML 覆盖
        scheduler = data.get("scheduler", {})
        if "interval_hours" in scheduler:
            self.interval_hours = float(scheduler["interval_hours"])

        downloader = data.get("downloader", {})
        if "concurrency" in downloader:
            self.download_concurrency = int(downloader["concurrency"])
        if "download_dir" in downloader:
            self.download_dir = downloader["download_dir"]
        if "max_batch" in downloader:
            self.max_batch = int(downloader["max_batch"])

        logging_cfg = data.get("logging", {})
        if "dir" in logging_cfg:
            self.log_dir = logging_cfg["dir"]
        # log_level 环境变量优先，YAML 次之
        if "level" in logging_cfg and os.environ.get("LOG_LEVEL") is None:
            self.log_level = logging_cfg["level"].upper()

        # 解析订阅列表（保留全部订阅，包括 enabled=False 的，供 UI 展示）
        subs_raw = data.get("subscriptions", [])
        self.subscriptions = [SubscriptionConfig(s) for s in subs_raw]

        # 空订阅检查：全部 disabled 或列表为空时输出 WARNING，避免服务静默运行无任何订阅
        enabled_count = sum(1 for s in self.subscriptions if s.enabled)
        if not self.subscriptions:
            logger.warning("⚠️  配置文件中未定义任何订阅，服务将空转。请在 config.yaml 中添加 subscriptions。")
        elif enabled_count == 0:
            logger.warning(
                "⚠️  所有 %d 个订阅均已 disabled，服务将空转。"
                "请在 config.yaml 中将至少一个订阅的 enabled 设为 true。",
                len(self.subscriptions),
            )
        else:
            logger.debug("订阅加载完成：共 %d 个，启用 %d 个", len(self.subscriptions), enabled_count)

        return self


def _fatal(msg: str) -> None:
    """打印错误信息并退出"""
    print(f"\n[FATAL] {msg}\n", file=sys.stderr)
    sys.exit(1)


_config_instance: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """全局单例，懒加载"""
    global _config_instance
    if _config_instance is None:
        try:
            _config_instance = AppConfig()
        except Exception as exc:
            # pydantic ValidationError 中包含 XHS_COOKIE 缺失信息
            _fatal(f"配置加载失败：{exc}")
    return _config_instance


def setup_logging(config: AppConfig) -> None:
    """初始化日志"""
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "xhs-subscriber.log"
    level = getattr(logging, config.log_level, logging.INFO)

    fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]

    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)
    logger.info("日志初始化完成，级别：%s，文件：%s", config.log_level, log_file)
