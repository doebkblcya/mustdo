from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.utils import formatdate
from time import perf_counter
from typing import AsyncIterator
from urllib.parse import urlencode, urlsplit

import websockets
from websockets.exceptions import WebSocketException

from app.config import get_settings


IFLYTEK_PCM_FRAME_BYTES = 1280
IFLYTEK_FRAME_INTERVAL_SECONDS = 0.04
IFLYTEK_AUDIO_FORMAT = "audio/L16;rate=16000"
IFLYTEK_AUDIO_ENCODING = "raw"
IFLYTEK_EOS_MS = 3000
logger = logging.getLogger("uvicorn.error")


class IflytekError(RuntimeError):
    pass


@dataclass(frozen=True)
class IflytekRecognitionEvent:
    text: str
    transcript: str
    is_final: bool


def extract_iflytek_text(result: dict) -> str:
    words = []
    for segment in result.get("ws", []):
        for candidate in segment.get("cw", []):
            word = candidate.get("w")
            if word:
                words.append(word)
    return "".join(words)


class IflytekIatClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _endpoint(self) -> tuple[str, str]:
        raw_host = self.settings.iflytek_iat_host.strip()
        path = self.settings.iflytek_iat_path.strip() or "/v2/iat"
        if "://" in raw_host:
            parsed = urlsplit(raw_host)
            raw_host = parsed.netloc
            if parsed.path:
                path = parsed.path
        return raw_host.strip("/"), path if path.startswith("/") else f"/{path}"

    def _build_url(self) -> str:
        host, path = self._endpoint()
        date = formatdate(usegmt=True)
        request_line = f"GET {path} HTTP/1.1"
        signature_origin = (
            f"host: {host}\n"
            f"date: {date}\n"
            f"{request_line}"
        )
        signature = hmac.new(
            self.settings.iflytek_api_secret.encode(),
            signature_origin.encode(),
            hashlib.sha256,
        ).digest()
        signature_base64 = base64.b64encode(signature).decode()
        authorization_origin = (
            f'api_key="{self.settings.iflytek_api_key}", '
            f'algorithm="hmac-sha256", '
            f'headers="host date request-line", '
            f'signature="{signature_base64}"'
        )
        query = urlencode(
            {
                "authorization": base64.b64encode(authorization_origin.encode()).decode(),
                "date": date,
                "host": host,
            }
        )
        return f"wss://{host}{path}?{query}"

    def _ensure_configured(self) -> None:
        if not (
            self.settings.iflytek_app_id
            and self.settings.iflytek_api_key
            and self.settings.iflytek_api_secret
        ):
            raise IflytekError("讯飞配置缺失")

    def connect(self):
        self._ensure_configured()
        return websockets.connect(
            self._build_url(),
            max_size=8 * 1024 * 1024,
            open_timeout=self.settings.iflytek_connect_timeout_seconds,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[IflytekIatSession]:
        try:
            async with self.connect() as websocket:
                yield IflytekIatSession(self, websocket)
        except TimeoutError as exc:
            logger.warning("iflytek_timeout host=%s path=%s error=%r", *self._endpoint(), exc)
            raise IflytekError("讯飞响应超时") from exc
        except (OSError, WebSocketException) as exc:
            logger.warning(
                "iflytek_connection_failed host=%s path=%s error=%r",
                *self._endpoint(),
                exc,
            )
            raise IflytekError("讯飞连接失败") from exc

    def _audio_frame(self, status: int, audio: bytes = b"") -> dict:
        if status == 2 and not audio:
            return {"data": {"status": 2}}

        frame = {
            "data": {
                "status": status,
                "format": IFLYTEK_AUDIO_FORMAT,
                "audio": base64.b64encode(audio).decode(),
                "encoding": IFLYTEK_AUDIO_ENCODING,
            }
        }
        if status == 0:
            frame["common"] = {"app_id": self.settings.iflytek_app_id}
            frame["business"] = {
                "language": self.settings.iflytek_language,
                "domain": "iat",
                "accent": self.settings.iflytek_accent,
                "eos": IFLYTEK_EOS_MS,
            }
        return frame

    async def transcribe_pcm(self, pcm: bytes) -> str:
        transcript = ""
        async with self.session() as session:
            receiver = asyncio.create_task(_collect_final_transcript(session))
            try:
                await session.send_pcm(pcm)
                await session.finish()
                transcript = await asyncio.wait_for(
                    receiver,
                    timeout=self.settings.iflytek_final_timeout_seconds,
                )
            finally:
                if not receiver.done():
                    receiver.cancel()
        if not transcript:
            raise IflytekError("讯飞未返回有效文本")
        return transcript


class IflytekIatSession:
    def __init__(self, client: IflytekIatClient, websocket) -> None:
        self.client = client
        self.websocket = websocket
        self._pending = bytearray()
        self._transcript_parts: list[str] = []
        self._finished = False
        self._last_frame_sent_at: float | None = None
        self.sent_audio_frames = 0
        self.received_messages = 0

    async def send_pcm(self, pcm: bytes) -> None:
        if self._finished:
            raise IflytekError("讯飞会话已结束")
        if len(pcm) % 2 != 0:
            raise IflytekError("音频帧长度不合法")
        if not pcm:
            return

        self._pending.extend(pcm)
        while len(self._pending) >= IFLYTEK_PCM_FRAME_BYTES:
            chunk = bytes(self._pending[:IFLYTEK_PCM_FRAME_BYTES])
            del self._pending[:IFLYTEK_PCM_FRAME_BYTES]
            await self._send_audio_chunk(chunk)

    async def finish(self) -> None:
        if self._finished:
            return
        if self._pending:
            padding = IFLYTEK_PCM_FRAME_BYTES - len(self._pending)
            chunk = bytes(self._pending) + (b"\0" * padding)
            self._pending.clear()
            await self._send_audio_chunk(chunk)
        await self._send_end_marker()
        self._finished = True

    async def recognition_events(self) -> AsyncIterator[IflytekRecognitionEvent]:
        async for raw_message in self.websocket:
            self.received_messages += 1
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError as exc:
                raise IflytekError("讯飞响应格式不合法") from exc

            code = message.get("code", 0)
            if code != 0:
                error_message = message.get("message") or "讯飞识别失败"
                raise IflytekError(f"{error_message}({code})")

            data = message.get("data") or {}
            result = data.get("result")
            text = ""
            if isinstance(result, dict):
                text = extract_iflytek_text(result)
                if text:
                    self._transcript_parts.append(text)

            status = data.get("status")
            transcript = "".join(self._transcript_parts).strip()
            is_final = status == 2
            yield IflytekRecognitionEvent(
                text=text,
                transcript=transcript,
                is_final=is_final,
            )
            if is_final:
                return

        raise IflytekError("讯飞连接提前关闭")

    async def _send_audio_chunk(self, chunk: bytes) -> None:
        if len(chunk) != IFLYTEK_PCM_FRAME_BYTES:
            raise IflytekError("讯飞音频帧必须是 1280B")
        status = 0 if self.sent_audio_frames == 0 else 1
        await self._send_frame(self.client._audio_frame(status, chunk))
        self.sent_audio_frames += 1

    async def _send_end_marker(self) -> None:
        await self._send_frame(self.client._audio_frame(2))

    async def _send_frame(self, frame: dict) -> None:
        await self._wait_frame_interval()
        await self.websocket.send(json.dumps(frame, ensure_ascii=False))
        self._last_frame_sent_at = perf_counter()

    async def _wait_frame_interval(self) -> None:
        if self._last_frame_sent_at is None:
            return
        elapsed = perf_counter() - self._last_frame_sent_at
        remaining = IFLYTEK_FRAME_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)


async def _collect_final_transcript(session: IflytekIatSession) -> str:
    transcript = ""
    async for event in session.recognition_events():
        if event.transcript:
            transcript = event.transcript
        if event.is_final:
            return transcript
    return transcript
