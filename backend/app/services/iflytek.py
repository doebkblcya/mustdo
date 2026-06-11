from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from email.utils import formatdate
from urllib.parse import urlencode

import websockets

from app.config import get_settings


class IflytekError(RuntimeError):
    pass


def _extract_text(result: dict) -> str:
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

    def _build_url(self) -> str:
        date = formatdate(usegmt=True)
        request_line = f"GET {self.settings.iflytek_iat_path} HTTP/1.1"
        signature_origin = (
            f"host: {self.settings.iflytek_iat_host}\n"
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
                "host": self.settings.iflytek_iat_host,
            }
        )
        return f"wss://{self.settings.iflytek_iat_host}{self.settings.iflytek_iat_path}?{query}"

    async def transcribe_pcm(self, pcm: bytes) -> str:
        if not (
            self.settings.iflytek_app_id
            and self.settings.iflytek_api_key
            and self.settings.iflytek_api_secret
        ):
            raise IflytekError("讯飞配置缺失")

        transcript_parts: list[str] = []
        url = self._build_url()
        async with websockets.connect(url, max_size=8 * 1024 * 1024) as websocket:
            receiver = asyncio.create_task(self._receive(websocket, transcript_parts))
            try:
                await self._send_audio(websocket, pcm)
                await receiver
            finally:
                if not receiver.done():
                    receiver.cancel()

        transcript = "".join(transcript_parts).strip()
        if not transcript:
            raise IflytekError("讯飞未返回有效文本")
        return transcript

    async def _send_audio(self, websocket, pcm: bytes) -> None:
        chunk_size = 1280
        chunks = [pcm[index : index + chunk_size] for index in range(0, len(pcm), chunk_size)]

        for index, chunk in enumerate(chunks):
            status = 0 if index == 0 else 1
            frame = {
                "data": {
                    "status": status,
                    "format": "audio/L16;rate=16000",
                    "audio": base64.b64encode(chunk).decode(),
                    "encoding": "raw",
                }
            }
            if index == 0:
                frame["common"] = {"app_id": self.settings.iflytek_app_id}
                frame["business"] = {
                    "language": self.settings.iflytek_language,
                    "domain": "iat",
                    "accent": self.settings.iflytek_accent,
                    "vad_eos": 10000,
                }
            await websocket.send(json.dumps(frame, ensure_ascii=False))
            await asyncio.sleep(0.04)

        await websocket.send(
            json.dumps(
                {
                    "data": {
                        "status": 2,
                        "format": "audio/L16;rate=16000",
                        "audio": "",
                        "encoding": "raw",
                    }
                },
                ensure_ascii=False,
            )
        )

    async def _receive(self, websocket, transcript_parts: list[str]) -> None:
        async for raw_message in websocket:
            message = json.loads(raw_message)
            code = message.get("code", 0)
            if code != 0:
                raise IflytekError(message.get("message") or "讯飞识别失败")

            data = message.get("data") or {}
            result = data.get("result")
            if result:
                transcript_parts.append(_extract_text(result))
            if data.get("status") == 2:
                return
