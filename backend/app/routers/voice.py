from __future__ import annotations

import logging
import sqlite3
from time import perf_counter

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.deps import current_user, get_db
from app.errors import raise_api_error
from app.schemas import AiCreateRequest, AiCreateResponse, TranscriptionResponse
from app.services.asr import VolcAsrError, recognize_pcm
from app.services.audio import PCM_BYTES_PER_SECOND, read_upload_as_pcm
from app.services.deepseek import DeepSeekParseError, NoTodoParsedError, parse_todos_with_deepseek
from app.services.todos import create_todos


router = APIRouter(prefix="/api", tags=["voice"])
logger = logging.getLogger("uvicorn.error")


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)


@router.post("/voice/transcriptions", response_model=TranscriptionResponse)
async def create_transcription(
    file: UploadFile = File(...),
    user: sqlite3.Row = Depends(current_user),
):
    _ = user
    started_at = perf_counter()
    pcm = await read_upload_as_pcm(file)
    try:
        transcript = await recognize_pcm(pcm)
    except VolcAsrError as exc:
        logger.warning(
            "voice_transcription_failed elapsed_ms=%s error=%s",
            _elapsed_ms(started_at),
            exc,
        )
        raise_api_error(
            status.HTTP_502_BAD_GATEWAY,
            "speech_recognition_failed",
            "语音识别失败，未添加待办",
        )
    logger.info(
        "voice_transcription_done elapsed_ms=%s audio_seconds=%.3f transcript_chars=%s",
        _elapsed_ms(started_at),
        len(pcm) / PCM_BYTES_PER_SECOND,
        len(transcript),
    )
    return TranscriptionResponse(transcript=transcript)


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
