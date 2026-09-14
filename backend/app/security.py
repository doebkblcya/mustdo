from __future__ import annotations

import hashlib
import hmac
import secrets

from app.config import get_settings


def _peppered_hash(value: str, purpose: str) -> str:
    secret = get_settings().secret_key.encode()
    payload = f"{purpose}:{value}".encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def hash_session_token(token: str) -> str:
    return _peppered_hash(token, "session")


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)
