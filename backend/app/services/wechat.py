from __future__ import annotations

import logging
import threading

import httpx

from app.config import get_settings


logger = logging.getLogger("uvicorn.error")
_wechat_client: httpx.AsyncClient | None = None
_wechat_client_lock = threading.Lock()

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatLoginError(RuntimeError):
    """A typed WeChat login failure carrying a stable machine code."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def get_wechat_client() -> httpx.AsyncClient:
    global _wechat_client
    if _wechat_client is None:
        with _wechat_client_lock:
            if _wechat_client is None:
                _wechat_client = httpx.AsyncClient(timeout=10)
    return _wechat_client


async def close_wechat_client() -> None:
    global _wechat_client
    with _wechat_client_lock:
        if _wechat_client is not None:
            await _wechat_client.aclose()
            _wechat_client = None


_ERRCODE_MAP: dict[int, tuple[str, int, str]] = {
    40029: ("wechat_code_invalid", 400, "登录凭证无效，请重试"),
    40163: ("wechat_code_invalid", 400, "登录凭证无效，请重试"),
    45011: ("wechat_rate_limited", 429, "登录过于频繁，请稍后再试"),
    -1: ("wechat_service_error", 502, "微信服务暂不可用，请重试"),
}


async def exchange_code_for_openid(code: str) -> str:
    """Exchange a wx.login temp code for the user's openid.

    WeChat also returns a session_key; it is intentionally discarded and never
    returned to the client (security).
    """
    settings = get_settings()
    if not settings.wechat_app_id or not settings.wechat_app_secret:
        raise WechatLoginError(
            "wechat_config_missing",
            "微信登录暂不可用",
            500,
        )

    params = {
        "appid": settings.wechat_app_id,
        "secret": settings.wechat_app_secret,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    try:
        client = get_wechat_client()
        response = await client.get(CODE2SESSION_URL, params=params)
    except httpx.HTTPError as exc:
        logger.warning("wechat_code2session_error error=%r", exc)
        raise WechatLoginError(
            "wechat_service_error",
            "微信服务暂不可用，请重试",
            502,
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning("wechat_code2session_bad_json status=%s", response.status_code)
        raise WechatLoginError(
            "wechat_service_error",
            "微信服务暂不可用，请重试",
            502,
        ) from exc

    errcode = data.get("errcode", 0)
    if errcode:
        code, http_status, message = _ERRCODE_MAP.get(
            errcode,
            ("wechat_login_failed", 502, "微信登录失败，请重试"),
        )
        logger.warning(
            "wechat_code2session_error errcode=%s errmsg=%s",
            errcode,
            data.get("errmsg"),
        )
        raise WechatLoginError(code, message, http_status)

    openid = data.get("openid")
    if not openid:
        logger.warning("wechat_code2session_missing_openid data=%r", data)
        raise WechatLoginError(
            "wechat_login_failed",
            "微信登录失败，请重试",
            502,
        )
    return openid
