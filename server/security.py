"""密碼雜湊與 JWT。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

import jwt

from .config import settings
from .db import utcnow

# 與原 C# 版相同格式:PBKDF2$iterations$saltBase64$hashBase64 (HMAC-SHA256),
# 因此既有資料庫內的帳號密碼可直接沿用。
_ITERATIONS = 100_000
_SALT_SIZE = 16
_KEY_SIZE = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_SIZE)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS, _KEY_SIZE)
    return f"PBKDF2${_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    parts = (encoded or "").split("$")
    if len(parts) != 4 or parts[0] != "PBKDF2":
        return False
    try:
        iterations = int(parts[1])
        salt = base64.b64decode(parts[2])
        expected = base64.b64decode(parts[3])
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, len(expected))
    return hmac.compare_digest(actual, expected)


def create_access_token(user_id: int, username: str, display_name: str, role_code: str,
                        permissions: list[str]) -> tuple[str, int]:
    """回傳 (token, 有效秒數)。"""
    now = utcnow()
    lifetime = timedelta(minutes=settings.jwt.access_token_minutes)
    payload = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "name": username,
        "display_name": display_name,
        "role_code": role_code,
        "perm": permissions,
        "iss": settings.jwt.issuer,
        "aud": settings.jwt.audience,
        "nbf": now,
        "iat": now,
        "exp": now + lifetime,
    }
    token = jwt.encode(payload, settings.jwt.secret_key, algorithm="HS256")
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict:
    """驗證失敗會擲出 jwt.InvalidTokenError。"""
    return jwt.decode(
        token,
        settings.jwt.secret_key,
        algorithms=["HS256"],
        audience=settings.jwt.audience,
        issuer=settings.jwt.issuer,
        leeway=30,
    )


def new_refresh_token() -> tuple[str, object]:
    return (base64.b64encode(secrets.token_bytes(48)).decode(),
            utcnow() + timedelta(days=settings.jwt.refresh_token_days))
