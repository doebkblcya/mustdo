from __future__ import annotations

import base64
import logging
import struct
from uuid import uuid4

import httpx

from app.config import get_settings

logger = logging.getLogger("uvicorn.error")

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30))
    return _client


async def close_asr_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def pcm_to_wav(
    pcm: bytes,
    sample_rate: int = 16000,
    num_channels: int = 1,
    bits_per_sample: int = 16,
) -> bytes:
    """Wrap raw 16kHz/16bit/mono PCM in a WAV container header."""
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm)

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,  # Subchunk1Size (PCM)
        1,   # AudioFormat (PCM = 1)
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm


class VolcAsrError(RuntimeError):
    """火山引擎 ASR 识别失败。"""


async def recognize_pcm(pcm: bytes) -> str:
    """将 PCM 音频发送到火山引擎录音文件极速版识别，返回识别文本。

    https://docs.volcengine.com/docs/6561/1631584
    """
    settings = get_settings()

    wav = pcm_to_wav(pcm)
    audio_base64 = base64.b64encode(wav).decode()

    request_id = uuid4().hex

    headers: dict[str, str] = {
        "X-Api-Resource-Id": "volc.bigasr.auc_turbo",
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
    }

    # 新版控制台只需 X-Api-Key，旧版需要 App-Key + Access-Key
    if settings.volc_api_key:
        headers["X-Api-Key"] = settings.volc_api_key
    else:
        headers["X-Api-App-Key"] = settings.volc_app_key
        headers["X-Api-Access-Key"] = settings.volc_access_key

    body = {
        "user": {
            "uid": settings.volc_app_key or settings.volc_api_key,
        },
        "audio": {
            "data": audio_base64,
        },
        "request": {
            "model_name": "bigmodel",
        },
    }

    client = _get_client()

    try:
        response = await client.post(
            "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash",
            json=body,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        logger.warning("volc_asr_http_error error=%r", exc)
        raise VolcAsrError("火山引擎 ASR 请求失败") from exc

    status_code = response.headers.get("X-Api-Status-Code", "")
    logid = response.headers.get("X-Tt-Logid", "")

    if status_code != "20000000":
        logger.warning(
            "volc_asr_failed status_code=%s logid=%s body_preview=%s",
            status_code,
            logid,
            response.text[:500],
        )
        if status_code == "20000003":
            raise VolcAsrError("火山引擎检测到静音音频")
        raise VolcAsrError(f"火山引擎识别失败(code={status_code})")

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning("volc_asr_invalid_json logid=%s", logid)
        raise VolcAsrError("火山引擎返回格式异常") from exc

    text = (data.get("result") or {}).get("text", "")
    if not text:
        raise VolcAsrError("火山引擎未返回有效文本")

    logger.info(
        "volc_asr_done logid=%s audio_seconds=%.3f text_chars=%s",
        logid,
        len(pcm) / 32000,
        len(text),
    )

    return text.strip()
