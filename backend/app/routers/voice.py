from __future__ import annotations

import sqlite3
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.deps import current_user, get_db
from app.schemas import AiCreateRequest, AiCreateResponse, TranscriptionResponse
from app.services.audio import read_upload_as_pcm
from app.services.deepseek import DeepSeekParseError, parse_todos_with_deepseek
from app.services.iflytek import IflytekError, IflytekIatClient
from app.services.todos import create_todos


router = APIRouter(prefix="/api", tags=["voice"])
logger = logging.getLogger(__name__)


@router.post("/voice/transcriptions", response_model=TranscriptionResponse)
async def create_transcription(
    file: UploadFile = File(...),
    user: sqlite3.Row = Depends(current_user),
):
    _ = user
    pcm = await read_upload_as_pcm(file)
    try:
        transcript = await IflytekIatClient().transcribe_pcm(pcm)
    except IflytekError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="语音识别失败，未添加待办",
        ) from exc
    return TranscriptionResponse(transcript=transcript)


@router.post("/todos/ai", response_model=AiCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_todos_from_transcript(
    payload: AiCreateRequest,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
):
    try:
        parsed_items = await parse_todos_with_deepseek(payload.transcript)
        created = create_todos(db, int(user["id"]), parsed_items)
    except DeepSeekParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI 解析失败，未添加待办",
        ) from exc
    except sqlite3.Error as exc:
        logger.exception("Failed to save AI-created todos")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存待办失败：{exc}",
        ) from exc

    return AiCreateResponse(transcript=payload.transcript, items=created)
