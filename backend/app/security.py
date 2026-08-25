from __future__ import annotations

import hashlib
import hmac
import secrets

from app.config import get_settings


INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _peppered_hash(value: str, purpose: str) -> str:
    secret = get_settings().secret_key.encode()
    payload = f"{purpose}:{value}".encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def hash_session_token(token: str) -> str:
    return _peppered_hash(token, "session")


def hash_invite_code(code: str) -> str:
    return _peppered_hash(normalize_invite_code(code), "invite")


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def normalize_invite_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


def generate_invite_code(invite_type: str = "single") -> str:
    prefix = {"single": "TODO-S", "multi": "TODO-M"}[invite_type]
    chunks = []
    for _ in range(3):
        chunks.append("".join(secrets.choice(INVITE_ALPHABET) for _ in range(4)))
    return prefix + "-" + "-".join(chunks)
