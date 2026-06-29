from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Response, UploadFile, WebSocket, status

from app.config import get_settings
from app.db import get_connection
from app.deps import bearer_token_from_authorization, current_user, get_db, user_from_session_token
from app.errors import raise_api_error
from app.schemas import AiCreateRequest, AiCreateResponse, TranscriptionResponse
from app.services.audio import PCM_BYTES_PER_SECOND, read_upload_as_pcm
from app.services.deepseek import DeepSeekParseError, NoTodoParsedError, parse_todos_with_deepseek
from app.services.iflytek import IflytekError, IflytekIatClient
from app.services.todos import create_todos
from app.services.voice_stream import VoiceStreamEvent, transcribe_pcm_stream


router = APIRouter(prefix="/api", tags=["voice"])
logger = logging.getLogger("uvicorn.error")


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)


def _websocket_user_id(websocket: WebSocket, db: sqlite3.Connection) -> int | None:
    settings = get_settings()
    bearer_token = bearer_token_from_authorization(websocket.headers.get("authorization"))
    session_token = bearer_token or websocket.cookies.get(settings.session_cookie_name)
    row = user_from_session_token(db, session_token)
    if row is None:
        return None
    return int(row["id"])


class VoiceStreamClientError(RuntimeError):
    def __init__(self, message: str, *, close_code: int = 1008) -> None:
        super().__init__(message)
        self.close_code = close_code
        self.message = message


@router.post("/voice/transcriptions", response_model=TranscriptionResponse)
async def create_transcription(
    file: UploadFile = File(...),
    user: sqlite3.Row = Depends(current_user),
):
    _ = user
    started_at = perf_counter()
    pcm = await read_upload_as_pcm(file)
    try:
        transcript = await IflytekIatClient().transcribe_pcm(pcm)
    except IflytekError as exc:
        logger.warning("voice_http_transcription_failed elapsed_ms=%s", _elapsed_ms(started_at))
        raise_api_error(
            status.HTTP_502_BAD_GATEWAY,
            "speech_recognition_failed",
            "语音识别失败，未添加待办",
        )
    logger.info(
        "voice_http_transcription_done elapsed_ms=%s audio_seconds=%.3f transcript_chars=%s",
        _elapsed_ms(started_at),
        len(pcm) / PCM_BYTES_PER_SECOND,
        len(transcript),
    )
    return TranscriptionResponse(transcript=transcript)


@router.websocket("/voice/stream")
async def stream_transcription(websocket: WebSocket):
    await websocket.accept()
    stream_id = uuid4().hex[:8]
    stream_started_at = perf_counter()

    db = get_connection()
    try:
        authenticated = _websocket_user_id(websocket, db) is not None
    finally:
        db.close()
    if not authenticated:
        await websocket.send_json({"type": "error", "error": "Not authenticated"})
        await websocket.close(code=1008)
        return

    settings = get_settings()
    send_lock = asyncio.Lock()
    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    total_audio_bytes = 0

    def audio_seconds() -> float:
        return total_audio_bytes / PCM_BYTES_PER_SECOND

    async def send_client(payload: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def read_browser_audio() -> None:
        nonlocal total_audio_bytes
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                await audio_queue.put(None)
                return

            audio = message.get("bytes")
            if audio is not None:
                if len(audio) % 2 != 0:
                    raise VoiceStreamClientError("音频帧长度不合法")
                audio_bytes = bytes(audio)
                total_audio_bytes += len(audio_bytes)
                if audio_seconds() > settings.max_audio_seconds:
                    raise VoiceStreamClientError("录音超过 30 秒", close_code=1009)
                await audio_queue.put(audio_bytes)
                continue

            raw_text = message.get("text")
            if raw_text is None:
                continue
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise VoiceStreamClientError("消息格式不合法") from exc
            if payload.get("type") != "end":
                continue

            if audio_seconds() < settings.min_audio_seconds:
                raise VoiceStreamClientError("录音太短")

            await audio_queue.put(None)
            return

    async def audio_chunks():
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                return
            yield chunk

    async def send_voice_event(event: VoiceStreamEvent) -> None:
        if event.type == "ready":
            logger.info(
                "voice_iflytek_connected stream_id=%s iflytek_connect_ms=%s",
                stream_id,
                _elapsed_ms(stream_started_at),
            )
        await send_client(event.as_payload())

    async def run_recognition() -> None:
        result = await transcribe_pcm_stream(audio_chunks(), send_voice_event)
        logger.info(
            "voice_stream_done stream_id=%s total_ms=%s iflytek_connect_ms=%s "
            "audio_seconds=%.3f sent_audio_frames=%s iflytek_messages=%s "
            "transcript_chars=%s final_source=%s",
            stream_id,
            _elapsed_ms(stream_started_at),
            result.iflytek_connect_ms,
            result.audio_seconds,
            result.sent_audio_frames,
            result.iflytek_messages,
            len(result.transcript),
            result.final_source,
        )

    reader_task: asyncio.Task[None] | None = None
    recognition_task: asyncio.Task[None] | None = None
    logger.info("voice_stream_open stream_id=%s", stream_id)
    try:
        reader_task = asyncio.create_task(read_browser_audio())
        recognition_task = asyncio.create_task(run_recognition())
        await asyncio.gather(reader_task, recognition_task)
        await websocket.close(code=1000)
    except VoiceStreamClientError as exc:
        logger.warning(
            "voice_stream_client_failed stream_id=%s elapsed_ms=%s audio_seconds=%.3f error=%s",
            stream_id,
            _elapsed_ms(stream_started_at),
            audio_seconds(),
            exc.message,
        )
        with contextlib.suppress(Exception):
            await send_client({"type": "error", "error": exc.message})
            await websocket.close(code=exc.close_code)
    except IflytekError as exc:
        logger.warning(
            "voice_stream_failed stream_id=%s elapsed_ms=%s audio_seconds=%.3f error=%s",
            stream_id,
            _elapsed_ms(stream_started_at),
            audio_seconds(),
            exc,
        )
        with contextlib.suppress(Exception):
            await send_client({"type": "error", "error": "语音识别失败，未添加待办"})
            await websocket.close(code=1011)
    except Exception as exc:
        logger.exception(
            "voice_stream_unhandled stream_id=%s elapsed_ms=%s audio_seconds=%.3f error=%s",
            stream_id,
            _elapsed_ms(stream_started_at),
            audio_seconds(),
            exc,
        )
        with contextlib.suppress(Exception):
            await send_client({"type": "error", "error": "语音处理失败，未添加待办"})
            await websocket.close(code=1011)
    finally:
        for task in (reader_task, recognition_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


@router.post("/todos/ai", response_model=AiCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_todos_from_transcript(
    payload: AiCreateRequest,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
):
    started_at = perf_counter()
    parsed_at: float | None = None
    try:
        parsed_items = await parse_todos_with_deepseek(payload.transcript)
        parsed_at = perf_counter()
        created = create_todos(db, int(user["id"]), parsed_items)
    except NoTodoParsedError as exc:
        response.status_code = status.HTTP_200_OK
        logger.info(
            "todos_ai_no_items elapsed_ms=%s transcript_chars=%s",
            _elapsed_ms(started_at),
            len(payload.transcript),
        )
        return AiCreateResponse(
            transcript=payload.transcript,
            items=[],
            message=str(exc),
        )
    except DeepSeekParseError as exc:
        logger.warning(
            "todos_ai_parse_failed elapsed_ms=%s transcript_chars=%s error=%s detail=%s",
            _elapsed_ms(started_at),
            len(payload.transcript),
            exc,
            exc.detail,
        )
        raise_api_error(
            status.HTTP_502_BAD_GATEWAY,
            "todo_parse_unavailable",
            "解析服务暂时不可用，未添加待办",
        )
    except sqlite3.Error as exc:
        logger.exception(
            "todos_ai_save_failed elapsed_ms=%s parse_ms=%s transcript_chars=%s",
            _elapsed_ms(started_at),
            round((parsed_at - started_at) * 1000) if parsed_at is not None else None,
            len(payload.transcript),
        )
        raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "todo_save_failed",
            f"保存待办失败：{exc}",
        )

    logger.info(
        "todos_ai_done total_ms=%s parse_ms=%s save_ms=%s transcript_chars=%s items=%s",
        _elapsed_ms(started_at),
        round((parsed_at - started_at) * 1000) if parsed_at is not None else None,
        round((perf_counter() - parsed_at) * 1000) if parsed_at is not None else None,
        len(payload.transcript),
        len(created),
    )
    return AiCreateResponse(transcript=payload.transcript, items=created)
