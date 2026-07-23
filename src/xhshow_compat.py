"""xhshow 0.1.x / 0.2.x 签名 API 兼容层。"""
from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any


def _extract_a1(cookie_str: str) -> str:
    """从完整 Cookie 字符串中读取 a1。"""
    for part in cookie_str.split(";"):
        part = part.strip()
        if part.startswith("a1="):
            return part[3:].strip()
    return ""


def _fallback_headers(client: Any, method: str, uri: str, cookie_str: str, payload: dict[str, Any]) -> dict[str, str]:
    """为 xhshow 0.1.x 生成最小可用的签名头。"""
    a1 = _extract_a1(cookie_str)
    if method == "GET":
        x_s = client.sign_xs_get(uri=uri, a1_value=a1, params=payload)
    else:
        x_s = client.sign_xs_post(uri=uri, a1_value=a1, payload=payload)
    key_names = {"a1", "webId", "web_session", "webBuild", "xsecappid"}
    parts = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part and part.split("=", 1)[0].strip() in key_names:
            parts.append(part)
    x_s_common = hashlib.md5("&".join(parts).encode()).hexdigest()[:16]
    return {
        "x-s": x_s,
        "x-t": str(int(time.time() * 1000)),
        "x-b3-traceid": secrets.token_hex(8),
        "x-xray-traceid": secrets.token_hex(16),
        "x-s-common": x_s_common,
    }


def sign_get_headers(client: Any, uri: str, cookie_str: str, params: dict[str, Any]) -> dict[str, str]:
    """获取 GET 签名头，优先使用 xhshow 0.2.x 的完整签名 API。"""
    if hasattr(client, "sign_headers_get"):
        headers = dict(client.sign_headers_get(uri=uri, cookies=cookie_str, params=params))
        return headers
    return _fallback_headers(client, "GET", uri, cookie_str, params)


def sign_post_headers(client: Any, uri: str, cookie_str: str, payload: dict[str, Any]) -> dict[str, str]:
    """获取 POST 签名头，优先使用 xhshow 0.2.x 的完整签名 API。"""
    if hasattr(client, "sign_headers_post"):
        headers = dict(client.sign_headers_post(uri=uri, cookies=cookie_str, payload=payload, x_rap=True))
        return headers
    return _fallback_headers(client, "POST", uri, cookie_str, payload)
