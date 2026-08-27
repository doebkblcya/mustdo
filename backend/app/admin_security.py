"""Admin-account security: password hashing and session-token management.

This is deliberately separate from ``app.security`` (which handles WeChat-user
bearer tokens). An admin is NOT a WeChat user; the two identities must never
mix. Passwords use PBKDF2-SHA256 with a per-admin random salt. Sessions are
encoded in a signed cookie managed by SQLAdmin's SessionMiddleware, and we
track a server-side ``session_version`` per admin so that bumping it (password
change / disable) invalidates every existing session at once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from app.config import get_settings

_PBKDF2_ITERATIONS = 210_000
_SCHEME = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Return ``pbkdf2_sha256$iterations$salt$hash``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return f"{_SCHEME}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of a password against a stored hash."""
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$", 3)
    except ValueError:
        return False
    if scheme != _SCHEME:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        int(iterations),
    )
    return hmac.compare_digest(actual, expected)


def generate_admin_session_nonce() -> str:
    """Random nonce stored in the signed session cookie.

    Kept separate from ``session_version`` so a nonce is per-session while the
    version is per-account; we validate both in ``authenticate``.
    """
    return secrets.token_urlsafe(32)


def admin_session_payload(
    admin_id: int, username: str, session_version: int, nonce: str
) -> dict[str, object]:
    """The object written into ``request.session`` on login."""
    return {
        "admin_id": admin_id,
        "username": username,
        "session_version": session_version,
        "nonce": nonce,
    }


def sqladmin_secret_key() -> str:
    """Secret for SQLAdmin's SessionMiddleware cookie signature.

    Derives a distinct key from the app secret so admin cookies don't collide
    with any other signing use.
    """
    secret = get_settings().secret_key.encode()
    return hashlib.sha256(secret + b":admin-cookie").hexdigest()
