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
from urllib.parse import urlparse

import yaml
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 合法日志级别集合（field_validator 与 load_yaml 共用，避免重复定义）
_ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _clamp(value: float, lo: float, hi: float, field: str) -> float:
    """
    将 value 限制在 [lo, hi] 范围内。
    CFG-1 修复：load_yaml 中直接赋值绕过了 Field(ge=..., le=...) 约束，
    用此函数做范围 clamp，超出范围时输出 WARNING 并修正，不中断启动。
    """
    if value < lo:
        logger.warning(
            "⚠️  config.yaml 中 %s=%r 低于最小值 %s，已修正为 %s",
            field, value, lo, lo,
        )
        return lo
    if value > hi:
        logger.warning(
            "⚠️  config.yaml 中 %s=%r 超出最大值 %s，已修正为 %s",
            field, value, hi, hi,
        )
        return hi
    return value

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
        # CFG-2 修复：video_url 在配置加载阶段做格式校验，
        # 非法 URL（缺少 scheme 或 netloc）立即抛出 ValueError，
        # 避免等到运行时才报错。
        raw_url: Optional[str] = data.get("video_url")
        # CFG-41 修复：video_url 空字符串保护，空字符串视为 None（未配置）
        if raw_url is not None and not raw_url:
            raw_url = None
        if raw_url is not None:
            parsed = urlparse(raw_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(
                    f"SubscriptionConfig: video_url 格式非法（缺少 scheme 或 netloc）：{raw_url!r}"
                )
        self.video_url: Optional[str] = raw_url
        # CFG-38 修复：name 空字符串时 fallback 到 user_id or "unknown"，避免空 name 触发 SC-45 保护
        _raw_name = data.get("name", "")
        self.name: str = _raw_name if _raw_name else (self.user_id or "unknown")
        self.enabled: bool = data.get("enabled", True)
        # CFG-3 修复：user_id 和 video_url 同时为 None 时，订阅配置实际无效，
        # 在加载阶段输出 warning，避免服务空转时难以排查原因。
        if self.user_id is None and self.video_url is None:
            logger.warning(
                "SubscriptionConfig [%s]: user_id 和 video_url 均未配置，此订阅无法正常工作，请检查配置。",
                self.name,
            )

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
    # CFG-16 修复：改用 SecretStr，防止日志/调试输出泄露 Cookie 明文
    xhs_cookie: SecretStr  # 环境变量 XHS_COOKIE

    # ---- 可选 ----
    config_path: str = "/config/config.yaml"
    log_level: str = "INFO"
    http_port: int = Field(default=8080, ge=1, le=65535)

    # ---- 从 YAML 加载的字段（不直接走 env） ----
    interval_hours: float = Field(default=6.0, ge=0.1, le=168.0)  # 0.1h ~ 7天
    download_concurrency: int = Field(default=3, ge=1, le=20)
    download_dir: str = "/data/downloads"
    log_dir: str = "/data/logs"
    subscriptions: List[SubscriptionConfig] = []
    max_batch: int = Field(default=30, ge=1, le=500)  # 每次抓取博主作品的最大条数（对应 fetcher MAX_BATCH）

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
        upper = v.upper()
        if upper not in _ALLOWED_LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL 必须是 {_ALLOWED_LOG_LEVELS} 之一，当前值：{v!r}")
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
            # CFG-45 修复：interval_hours None 值保护，None 时 float() 会抛 TypeError
            _raw_ih = scheduler["interval_hours"]
            if _raw_ih is None:
                logger.warning("config.yaml scheduler.interval_hours 为 null，已忽略，保持当前值：%s", self.interval_hours)
            else:
                self.interval_hours = _clamp(float(_raw_ih), 0.1, 168.0, "interval_hours")

        downloader = data.get("downloader", {})
        if "concurrency" in downloader:
            self.download_concurrency = int(_clamp(int(downloader["concurrency"]), 1, 20, "concurrency"))
        if "download_dir" in downloader:
            # CFG-42 修复：download_dir 空字符串保护，空字符串会绕过路径规范化写入空路径
            _raw_dd = str(downloader["download_dir"]).strip()
            if not _raw_dd:
                logger.warning("config.yaml download_dir 为空字符串，已忽略，保持当前值：%s", self.download_dir)
            else:
                # CFG-10 修复：expanduser + resolve 规范化路径，支持 ~ 开头的路径
                self.download_dir = str(Path(_raw_dd).expanduser().resolve())
        if "max_batch" in downloader:
            self.max_batch = int(_clamp(int(downloader["max_batch"]), 1, 500, "max_batch"))

        logging_cfg = data.get("logging", {})
        if "dir" in logging_cfg:
            # CFG-43 修复：log_dir 空字符串保护，空字符串会绕过路径规范化写入空路径（与 CFG-42 对称）
            _raw_ld = str(logging_cfg["dir"]).strip()
            if not _raw_ld:
                logger.warning("config.yaml logging.dir 为空字符串，已忽略，保持当前值：%s", self.log_dir)
            else:
                # CFG-11 修复：expanduser + resolve 规范化路径，支持 ~ 开头的路径（与 CFG-10 对称）
                self.log_dir = str(Path(_raw_ld).expanduser().resolve())
        # log_level 环境变量优先，YAML 次之；YAML 值需验证合法性
        if "level" in logging_cfg and os.environ.get("LOG_LEVEL") is None:
            # CFG-44 修复：log_level None 值保护，logging_cfg["level"] 为 None 时 .upper() 会抛 AttributeError
            _raw_ll = logging_cfg["level"]
            if _raw_ll is None:
                logger.warning("config.yaml logging.level 为 null，已忽略，保持当前值：%s", self.log_level)
                _raw_ll = ""
            yaml_level = str(_raw_ll).upper()
            if yaml_level in _ALLOWED_LOG_LEVELS:
                self.log_level = yaml_level
            else:
                logger.warning(
                    "⚠️  config.yaml 中 logging.level=%r 非法（允许值：%s），已忽略，保持当前值：%s",
                    logging_cfg["level"],
                    ", ".join(sorted(_ALLOWED_LOG_LEVELS)),
                    self.log_level,
                )

        # CFG-21 修复：解析 server.http_port，使 YAML 配置端口真正生效（环境变量 HTTP_PORT 优先）
        server = data.get("server", {})
        if "http_port" in server and os.environ.get("HTTP_PORT") is None:
            self.http_port = int(_clamp(int(server["http_port"]), 1, 65535, "http_port"))

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
