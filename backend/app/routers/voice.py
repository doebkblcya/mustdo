from __future__ import annotations

import logging
import sqlite3
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.deps import current_user_invited, get_db
from app.errors import raise_api_error
from app.schemas import TranscriptionResponse
from app.services.asr import VolcAsrError, VolcSilentAudioError, recognize_pcm
from app.services.audio import PCM_BYTES_PER_SECOND, read_upload_as_pcm
from app.services.quota import check_asr_quota, record_asr_usage

router = APIRouter(prefix="/api", tags=["voice"])
logger = logging.getLogger("uvicorn.error")


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)


def _record_asr(
    db: sqlite3.Connection,
    user_id: int,
    *,
    request_id: str,
    logid: str | None,
    audio_seconds: float,
    status_str: str,
    error_code: str | None,
    started_at: float,
) -> None:
    record_asr_usage(
        db,
        user_id,
        request_id=request_id,
        logid=logid,
        audio_seconds=audio_seconds,
        status=status_str,
        error_code=error_code,
        duration_ms=_elapsed_ms(started_at),
    )


@router.post("/voice/transcriptions", response_model=TranscriptionResponse)
async def create_transcription(
    file: UploadFile = File(...),
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
):
    user_id = int(user["id"])
    started_at = perf_counter()

    # Validate/decode the upload first. Format/length errors raise here and
    # never reach an upstream ASR call, so they consume no quota.
    pcm = await read_upload_as_pcm(file)
    audio_seconds = len(pcm) / PCM_BYTES_PER_SECOND
    request_id = uuid4().hex

    # Quota check uses the known audio length BEFORE anything is sent upstream.
    check_asr_quota(db, user_id, audio_seconds)

    try:
        result = await recognize_pcm(pcm, request_id=request_id)
    except VolcSilentAudioError as exc:
        # Sample first 64 bytes to diagnose silent audio (e.g. DevTools all-zeros)
        pcm_sample = pcm[:64].hex()
        pcm_zero = all(b == 0 for b in pcm[:1024])
        logger.info(
            "voice_transcription_silent elapsed_ms=%s audio_seconds=%.3f "
            "pcm_all_zero_first_1k=%s pcm_first_64_hex=%s",
            _elapsed_ms(started_at),
            audio_seconds,
            pcm_zero,
            pcm_sample,
        )
        _record_asr(
            db, user_id,
            request_id=request_id,
            logid=exc.logid,
            audio_seconds=audio_seconds,
            status_str="silence",
            error_code=None,
            started_at=started_at,
        )
        return TranscriptionResponse(transcript="")
    except VolcAsrError as exc:
        logger.warning(
            "voice_transcription_failed elapsed_ms=%s error=%s",
            _elapsed_ms(started_at),
            exc,
        )
        _record_asr(
            db, user_id,
            request_id=request_id,
            logid=exc.logid,
            audio_seconds=audio_seconds,
            status_str="failed",
            error_code="asr_error",
            started_at=started_at,
        )
        raise_api_error(
            status.HTTP_502_BAD_GATEWAY,
            "speech_recognition_failed",
            "语音识别失败，未添加待办",
        )

    _record_asr(
        db, user_id,
        request_id=request_id,
        logid=result.logid,
        audio_seconds=audio_seconds,
        status_str="success",
        error_code=None,
        started_at=started_at,
    )
    logger.info(
        "voice_transcription_done elapsed_ms=%s audio_seconds=%.3f transcript_chars=%s",
        _elapsed_ms(started_at),
        audio_seconds,
        len(result.text),
    )
    return TranscriptionResponse(transcript=result.text)
