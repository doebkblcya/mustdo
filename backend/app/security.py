from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from app.config import get_settings


PBKDF2_ITERATIONS = 210_000
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("用户名只能包含 3-24 位字母、数字或下划线")
    return username


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("密码至少需要 8 位")
    if len(password) > 128:
        raise ValueError("密码过长")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode())
        expected = base64.urlsafe_b64decode(digest_raw.encode())
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return hmac.compare_digest(actual, expected)


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


def generate_invite_code() -> str:
    chunks = []
    for _ in range(3):
        chunks.append("".join(secrets.choice(INVITE_ALPHABET) for _ in range(4)))
    return "TODO-" + "-".join(chunks)
