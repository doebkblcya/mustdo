from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from time import perf_counter
from typing import AsyncIterator, Awaitable, Callable

from app.config import get_settings
from app.services.audio import PCM_BYTES_PER_SECOND
from app.services.iflytek import IflytekError, IflytekIatClient, IflytekIatSession


@dataclass(frozen=True)
class VoiceStreamEvent:
    type: str
    text: str = ""
    transcript: str = ""

    def as_payload(self) -> dict[str, str]:
        payload = {"type": self.type}
        if self.text:
            payload["text"] = self.text
        if self.transcript:
            payload["transcript"] = self.transcript
        return payload


@dataclass(frozen=True)
class VoiceStreamResult:
    transcript: str
    audio_seconds: float
    sent_audio_frames: int
    iflytek_messages: int
    iflytek_connect_ms: int
    final_source: str


EmitVoiceEvent = Callable[[VoiceStreamEvent], Awaitable[None]]


async def transcribe_pcm_stream(
    chunks: AsyncIterator[bytes],
    emit: EmitVoiceEvent,
) -> VoiceStreamResult:
    settings = get_settings()
    started_at = perf_counter()
    audio_bytes = 0
    latest_transcript = ""

    async def relay_results(session: IflytekIatSession) -> str:
        nonlocal latest_transcript
        async for event in session.recognition_events():
            if event.transcript:
                latest_transcript = event.transcript
            if event.text:
                await emit(
                    VoiceStreamEvent(
                        type="partial",
                        text=event.text,
                        transcript=event.transcript,
                    )
                )
            if event.is_final:
                if not event.transcript:
                    raise IflytekError("讯飞未返回有效文本")
                await emit(VoiceStreamEvent(type="final", transcript=event.transcript))
                return event.transcript
        raise IflytekError("讯飞连接提前关闭")

    client = IflytekIatClient()
    async with client.session() as session:
        iflytek_connect_ms = round((perf_counter() - started_at) * 1000)
        await emit(VoiceStreamEvent(type="ready"))
        receiver = asyncio.create_task(relay_results(session))
        next_chunk = asyncio.create_task(anext(chunks, None))
        final_source = "iflytek_final"
        transcript = ""
        try:
            while True:
                done, _pending = await asyncio.wait(
                    {next_chunk, receiver},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if receiver in done:
                    next_chunk.cancel()
                    transcript = receiver.result()
                    break

                chunk = next_chunk.result()
                if chunk is None:
                    break
                audio_bytes += len(chunk)
                await session.send_pcm(chunk)
                next_chunk = asyncio.create_task(anext(chunks, None))

            if not transcript:
                await session.finish()
                try:
                    transcript = await asyncio.wait_for(
                        receiver,
                        timeout=settings.iflytek_final_timeout_seconds,
                    )
                except TimeoutError:
                    if not latest_transcript:
                        raise IflytekError("讯飞最终结果超时且无可用文本") from None
                    transcript = latest_transcript
                    final_source = "partial_timeout"
                    await emit(VoiceStreamEvent(type="final", transcript=transcript))
        finally:
            if not next_chunk.done():
                next_chunk.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await next_chunk
            if not receiver.done():
                receiver.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receiver

    return VoiceStreamResult(
        transcript=transcript,
        audio_seconds=audio_bytes / PCM_BYTES_PER_SECOND,
        sent_audio_frames=session.sent_audio_frames,
        iflytek_messages=session.received_messages,
        iflytek_connect_ms=iflytek_connect_ms,
        final_source=final_source,
    )
