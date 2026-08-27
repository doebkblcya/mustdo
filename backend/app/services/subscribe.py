from __future__ import annotations

import logging
import threading
import time

import httpx

from app.config import get_settings
from app.services.wechat import get_wechat_client

logger = logging.getLogger("uvicorn.error")

TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
SUBSEND_URL = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"

# 提前 10 分钟过期，避免令牌刚好在发送请求时失效。
_TOKEN_REFRESH_MARGIN_SECONDS = 600

# access_token 失效码：需重取令牌后重试一次。
_TOKEN_EXPIRED_CODES = {40001, 40014, 42001}

_access_token: str | None = None
_access_token_expires_at: float = 0.0
_token_lock = threading.Lock()


class SubscribeSendError(RuntimeError):
    """A typed subscribe/send failure carrying the WeChat errcode."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _invalidate_token() -> None:
    global _access_token, _access_token_expires_at
    _access_token = None
    _access_token_expires_at = 0.0


async def get_access_token(force: bool = False) -> str:
    """Cached WeChat access_token, refreshed before expiry (thread-safe)."""
    global _access_token, _access_token_expires_at
    now = time.monotonic()
    if not force and _access_token and _access_token_expires_at - now > _TOKEN_REFRESH_MARGIN_SECONDS:
        return _access_token

    settings = get_settings()
    if not settings.wechat_app_id or not settings.wechat_app_secret:
        raise SubscribeSendError("wechat_config_missing", "微信配置缺失")

    with _token_lock:
        now = time.monotonic()
        if not force and _access_token and _access_token_expires_at - now > _TOKEN_REFRESH_MARGIN_SECONDS:
            return _access_token

        client = get_wechat_client()
        try:
            response = await client.get(
                TOKEN_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": settings.wechat_app_id,
                    "secret": settings.wechat_app_secret,
                },
            )
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("wechat_token_fetch_error error=%r", exc)
            raise SubscribeSendError("wechat_service_error", "微信服务暂不可用") from exc

        errcode = data.get("errcode", 0)
        if errcode or not data.get("access_token"):
            logger.warning("wechat_token_fetch_failed errcode=%s errmsg=%s", errcode, data.get("errmsg"))
            raise SubscribeSendError(str(errcode) or "wechat_token_missing", str(data.get("errmsg") or "获取令牌失败"))

        _access_token = data["access_token"]
        _access_token_expires_at = now + int(data.get("expires_in", 7200))
        return _access_token


async def send_subscribe_message(
    *,
    openid: str,
    template_id: str,
    page: str,
    data: dict[str, dict[str, str]],
) -> None:
    """Send a one-time subscribe message; retries once on token expiry.

    Raises SubscribeSendError on any failure (caller records status/failed).
    """
    token = await get_access_token()
    payload = {
        "touser": openid,
        "template_id": template_id,
        "page": page,
        "data": data,
    }
    try:
        response = await get_wechat_client().post(
            SUBSEND_URL,
            params={"access_token": token},
            json=payload,
        )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("wechat_subscribe_send_error error=%r", exc)
        raise SubscribeSendError("wechat_service_error", "微信服务暂不可用") from exc

    errcode = body.get("errcode", 0)
    if errcode == 0:
        return

    if errcode in _TOKEN_EXPIRED_CODES:
        _invalidate_token()
        token = await get_access_token(force=True)
        try:
            response = await get_wechat_client().post(
                SUBSEND_URL,
                params={"access_token": token},
                json=payload,
            )
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("wechat_subscribe_send_retry_error error=%r", exc)
            raise SubscribeSendError("wechat_service_error", "微信服务暂不可用") from exc
        if body.get("errcode", 0) == 0:
            return
        errcode = body.get("errcode", 0)

    logger.warning(
        "wechat_subscribe_send_failed errcode=%s errmsg=%s openid=%s template_id=%s",
        errcode,
        body.get("errmsg"),
        openid,
        template_id,
    )
    raise SubscribeSendError(str(errcode), str(body.get("errmsg") or "发送失败"))
