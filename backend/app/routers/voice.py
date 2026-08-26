from __future__ import annotations

import logging
import sqlite3
from time import perf_counter

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.deps import current_user_invited
from app.errors import raise_api_error
from app.schemas import TranscriptionResponse
from app.services.asr import VolcAsrError, VolcSilentAudioError, recognize_pcm
from app.services.audio import PCM_BYTES_PER_SECOND, read_upload_as_pcm


router = APIRouter(prefix="/api", tags=["voice"])
logger = logging.getLogger("uvicorn.error")


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)


@router.post("/voice/transcriptions", response_model=TranscriptionResponse)
async def create_transcription(
    file: UploadFile = File(...),
    user: sqlite3.Row = Depends(current_user_invited),
):
    _ = user
    started_at = perf_counter()
    pcm = await read_upload_as_pcm(file)
    try:
        transcript = await recognize_pcm(pcm)
    except VolcSilentAudioError:
        # Sample first 64 bytes to diagnose silent audio (e.g. DevTools all-zeros)
        pcm_sample = pcm[:64].hex()
        pcm_zero = all(b == 0 for b in pcm[:1024])
        logger.info(
            "voice_transcription_silent elapsed_ms=%s audio_seconds=%.3f "
            "pcm_all_zero_first_1k=%s pcm_first_64_hex=%s",
            _elapsed_ms(started_at),
            len(pcm) / PCM_BYTES_PER_SECOND,
            pcm_zero,
            pcm_sample,
        )
        return TranscriptionResponse(transcript="")
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
