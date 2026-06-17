from __future__ import annotations

import asyncio
import base64
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import HTTPException  # noqa: E402
from starlette.responses import Response  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.routers.voice import _websocket_user_id, create_todos_from_transcript  # noqa: E402
from app.security import hash_session_token  # noqa: E402
from app.schemas import AiCreateRequest  # noqa: E402
from app.services.deepseek import NoTodoParsedError  # noqa: E402
from app.services.audio import PCM_BYTES_PER_SECOND, read_upload_as_pcm  # noqa: E402
from app.services.iflytek import (  # noqa: E402
    IFLYTEK_PCM_FRAME_BYTES,
    IflytekIatClient,
    IflytekIatSession,
    extract_iflytek_text,
)
from app.services.voice_stream import transcribe_pcm_stream  # noqa: E402
from app.time_utils import now_shanghai  # noqa: E402


class FakeIflytekWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class FakeReceivingIflytekWebSocket(FakeIflytekWebSocket):
    def __init__(self, messages: list[dict]) -> None:
        super().__init__()
        self.messages = messages

    def __aiter__(self):
        self._message_iter = iter(self.messages)
        return self

    async def __anext__(self) -> str:
        try:
            return json.dumps(next(self._message_iter), ensure_ascii=False)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeStreamingIflytekWebSocket(FakeIflytekWebSocket):
    def __init__(self, messages: list[dict]) -> None:
        super().__init__()
        self.messages = messages
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self.index >= len(self.messages):
            raise StopAsyncIteration
        while len(self.sent) <= self.index:
            await asyncio.sleep(0)
        message = self.messages[self.index]
        self.index += 1
        return json.dumps(message, ensure_ascii=False)


async def send_pcm_and_finish(session: IflytekIatSession, pcm: bytes) -> None:
    await session.send_pcm(pcm)
    await session.finish()


async def iter_pcm_chunks(chunks: list[bytes]):
    for chunk in chunks:
        yield chunk


class FakeUpload:
    def __init__(self, raw: bytes, filename: str, content_type: str) -> None:
        self.raw = raw
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self.raw


class IflytekClientTests(unittest.TestCase):
    def test_audio_frames_follow_iflytek_shape(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IFLYTEK_APP_ID": "appid",
                "IFLYTEK_API_KEY": "apikey",
                "IFLYTEK_API_SECRET": "secret",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            client = IflytekIatClient()

        first = client._audio_frame(0, b"abcd")
        middle = client._audio_frame(1, b"efgh")
        end = client._audio_frame(2)

        self.assertEqual(first["data"]["status"], 0)
        self.assertEqual(first["data"]["format"], "audio/L16;rate=16000")
        self.assertEqual(first["data"]["encoding"], "raw")
        self.assertEqual(first["common"], {"app_id": "appid"})
        self.assertEqual(first["business"]["domain"], "iat")
        self.assertEqual(first["business"]["eos"], 3000)

        self.assertEqual(middle["data"]["status"], 1)
        self.assertNotIn("business", middle)
        self.assertNotIn("common", middle)

        self.assertEqual(end["data"], {"status": 2})

    def test_extract_iflytek_text_joins_candidates(self) -> None:
        result = {
            "ws": [
                {"cw": [{"w": "买"}, {"w": "卖"}]},
                {"cw": [{"w": "菜"}]},
            ]
        }

        self.assertEqual(extract_iflytek_text(result), "买卖菜")

    def test_endpoint_accepts_host_or_full_websocket_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IFLYTEK_IAT_HOST": "wss://iat-api.xfyun.cn/v2/iat",
                "IFLYTEK_IAT_PATH": "/ignored",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            client = IflytekIatClient()

        self.assertEqual(client._endpoint(), ("iat-api.xfyun.cn", "/v2/iat"))

    def test_send_audio_uses_full_audio_frames_and_separate_end_marker(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IFLYTEK_APP_ID": "appid",
                "IFLYTEK_API_KEY": "apikey",
                "IFLYTEK_API_SECRET": "secret",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            client = IflytekIatClient()

        websocket = FakeIflytekWebSocket()
        session = IflytekIatSession(client, websocket)
        pcm = b"\1" * (IFLYTEK_PCM_FRAME_BYTES * 2 + 10)

        asyncio.run(send_pcm_and_finish(session, pcm))

        statuses = [frame["data"]["status"] for frame in websocket.sent]
        self.assertEqual(statuses, [0, 1, 1, 2])
        self.assertEqual(websocket.sent[-1]["data"], {"status": 2})
        self.assertEqual(
            len(base64.b64decode(websocket.sent[-2]["data"]["audio"])),
            IFLYTEK_PCM_FRAME_BYTES,
        )

    def test_send_audio_keeps_single_chunk_initial_frame_shape(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IFLYTEK_APP_ID": "appid",
                "IFLYTEK_API_KEY": "apikey",
                "IFLYTEK_API_SECRET": "secret",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            client = IflytekIatClient()

        websocket = FakeIflytekWebSocket()
        session = IflytekIatSession(client, websocket)
        asyncio.run(send_pcm_and_finish(session, b"\1" * 100))

        statuses = [frame["data"]["status"] for frame in websocket.sent]
        self.assertEqual(statuses, [0, 2])
        self.assertIn("common", websocket.sent[0])
        self.assertEqual(
            len(base64.b64decode(websocket.sent[0]["data"]["audio"])),
            IFLYTEK_PCM_FRAME_BYTES,
        )
        self.assertEqual(websocket.sent[-1]["data"], {"status": 2})

    def test_recognition_events_accumulate_transcript(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IFLYTEK_APP_ID": "appid",
                "IFLYTEK_API_KEY": "apikey",
                "IFLYTEK_API_SECRET": "secret",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            client = IflytekIatClient()

        websocket = FakeReceivingIflytekWebSocket(
            [
                {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "status": 0,
                        "result": {"sn": 1, "ls": False, "ws": [{"cw": [{"w": "买"}]}]},
                    },
                },
                {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "status": 2,
                        "result": {"sn": 2, "ls": True, "ws": [{"cw": [{"w": "菜"}]}]},
                    },
                },
            ]
        )
        session = IflytekIatSession(client, websocket)

        async def collect_events() -> list[str]:
            transcripts = []
            async for event in session.recognition_events():
                transcripts.append(event.transcript)
            return transcripts

        self.assertEqual(asyncio.run(collect_events()), ["买", "买菜"])


class AudioUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "MIN_AUDIO_SECONDS": "0.5",
                "MAX_AUDIO_SECONDS": "30",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        get_settings.cache_clear()

    def test_pcm_upload_is_accepted_without_transcoding(self) -> None:
        raw = b"\0" * PCM_BYTES_PER_SECOND
        upload = FakeUpload(raw, "recording.pcm", "audio/pcm")

        result = asyncio.run(read_upload_as_pcm(upload))

        self.assertEqual(result, raw)

    def test_too_short_pcm_is_rejected(self) -> None:
        raw = b"\0" * (PCM_BYTES_PER_SECOND // 10)
        upload = FakeUpload(raw, "recording.pcm", "audio/pcm")

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(read_upload_as_pcm(upload))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "录音太短")

    def test_too_long_pcm_is_rejected(self) -> None:
        raw = b"\0" * (PCM_BYTES_PER_SECOND * 31)
        upload = FakeUpload(raw, "recording.pcm", "audio/pcm")

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(read_upload_as_pcm(upload))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "录音超过 30 秒")


class VoiceStreamServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "IFLYTEK_APP_ID": "appid",
                "IFLYTEK_API_KEY": "apikey",
                "IFLYTEK_API_SECRET": "secret",
                "IFLYTEK_FINAL_TIMEOUT_SECONDS": "1",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        get_settings.cache_clear()

    def test_stream_service_emits_ready_after_iflytek_session_connects(self) -> None:
        client = IflytekIatClient()
        websocket = FakeStreamingIflytekWebSocket(
            [
                {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "status": 0,
                        "result": {"sn": 1, "ls": False, "ws": [{"cw": [{"w": "买"}]}]},
                    },
                },
                {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "status": 2,
                        "result": {"sn": 2, "ls": True, "ws": [{"cw": [{"w": "菜"}]}]},
                    },
                },
            ]
        )
        session = IflytekIatSession(client, websocket)

        class FakeSessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return None

        class FakeClient:
            def session(self):
                return FakeSessionContext()

        async def run_stream():
            events = []

            async def emit(event):
                events.append(event.as_payload())

            with patch("app.services.voice_stream.IflytekIatClient", FakeClient):
                result = await transcribe_pcm_stream(iter_pcm_chunks([b"\1" * 100]), emit)
            return events, result

        events, result = asyncio.run(run_stream())

        self.assertEqual([event["type"] for event in events], ["ready", "partial", "partial", "final"])
        self.assertEqual(events[0], {"type": "ready"})
        self.assertEqual(result.transcript, "买菜")
        self.assertEqual(result.sent_audio_frames, 1)
        self.assertEqual(result.iflytek_messages, 2)


class AiTodoRouteTests(unittest.TestCase):
    def test_no_todo_parse_result_returns_empty_success_response(self) -> None:
        async def no_todo(_transcript):
            raise NoTodoParsedError("没有识别到需要新增的待办")

        async def run_route():
            response = Response()
            with patch("app.routers.voice.parse_todos_with_deepseek", no_todo):
                result = await create_todos_from_transcript(
                    AiCreateRequest(transcript="今天天气不错"),
                    response=response,
                    db=SimpleNamespace(),
                    user={"id": 1},
                )
            return response, result

        response, result = asyncio.run(run_route())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(result.items, [])
        self.assertEqual(result.message, "没有识别到需要新增的待办")


class WebSocketAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_PATH": os.path.join(self.tmpdir.name, "test.db"),
                "SECRET_KEY": "test-secret",
                "SESSION_COOKIE_NAME": "todo_session",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmpdir.cleanup()
        get_settings.cache_clear()

    def test_websocket_user_id_rejects_missing_cookie(self) -> None:
        websocket = SimpleNamespace(cookies={})
        with get_connection() as db:
            self.assertIsNone(_websocket_user_id(websocket, db))

    def test_websocket_user_id_accepts_active_session(self) -> None:
        session_token = "raw-session-token"
        now = now_shanghai()
        with get_connection() as db:
            cursor = db.execute(
                """
                INSERT INTO users (
                    username, username_normalized, password_hash, status, created_at, updated_at
                )
                VALUES ('tester', 'tester', 'hash', 'active', ?, ?)
                """,
                (now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
            )
            user_id = int(cursor.lastrowid)
            db.execute(
                """
                INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    hash_session_token(session_token),
                    now.isoformat(timespec="seconds"),
                    (now + timedelta(days=1)).isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        websocket = SimpleNamespace(cookies={"todo_session": session_token})
        with get_connection() as db:
            self.assertEqual(_websocket_user_id(websocket, db), user_id)

    def test_websocket_user_id_rejects_expired_session(self) -> None:
        session_token = "expired-session-token"
        now = now_shanghai()
        with get_connection() as db:
            cursor = db.execute(
                """
                INSERT INTO users (
                    username, username_normalized, password_hash, status, created_at, updated_at
                )
                VALUES ('tester', 'tester', 'hash', 'active', ?, ?)
                """,
                (now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
            )
            user_id = int(cursor.lastrowid)
            db.execute(
                """
                INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    hash_session_token(session_token),
                    (now - timedelta(days=2)).isoformat(timespec="seconds"),
                    (now - timedelta(days=1)).isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        websocket = SimpleNamespace(cookies={"todo_session": session_token})
        with get_connection() as db:
            self.assertIsNone(_websocket_user_id(websocket, db))


if __name__ == "__main__":
    unittest.main()
