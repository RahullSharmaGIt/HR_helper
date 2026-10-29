import hashlib
import json
import logging
import secrets
from typing import Any

import redis
from fastapi import Depends, Request

from app.api.errors import APIException
from app.config import settings

logger = logging.getLogger("auth")

# In-memory session and throttle fallback for tests or when Redis is absent
_LOCAL_SESSION_STORE: dict[str, dict[str, Any]] = {}
_LOCAL_THROTTLE_STORE: dict[str, list[float]] = {}


def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2-HMAC-SHA256 with 100,000 iterations and salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"pbkdf2:sha256:100000${salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against the stored PBKDF2 hash or dev password."""
    # Allow fallback in development if admin_password is set
    if settings.admin_password and secrets.compare_digest(plain_password, settings.admin_password):
        return True

    try:
        parts = hashed_password.split("$")
        if len(parts) != 3:
            return False
        method, salt, expected_hex = parts[0], parts[1], parts[2]
        _, algo, iters = method.split(":")
        derived_key = hashlib.pbkdf2_hmac(
            algo,
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iters),
        )
        return secrets.compare_digest(derived_key.hex(), expected_hex)
    except Exception:
        return False


def get_redis_client() -> redis.Redis | None:
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def check_exact_origin(request: Request) -> None:
    """Enforces exact-origin checks for state-mutating requests."""
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if referer:
            from urllib.parse import urlparse

            parsed = urlparse(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}"

    if origin:
        allowed = set(settings.allowed_origins)
        # Normalize origin trailing slash
        clean_origin = origin.rstrip("/")
        if clean_origin not in allowed and origin not in allowed:
            raise APIException(
                status_code=403,
                code="INVALID_ORIGIN",
                message=f"Request origin '{origin}' is not allowed by policy.",
            )


def check_login_throttling(ip: str, client: redis.Redis | None = None) -> None:
    """Ensures IP has not exceeded maximum failed login attempts within window."""
    if client:
        try:
            key = f"login_throttle:{ip}"
            attempts = client.get(key)
            if attempts and int(attempts) >= settings.max_login_attempts:
                raise APIException(
                    status_code=429,
                    code="LOGIN_THROTTLED",
                    message="Too many failed login attempts. Please wait before retrying.",
                )
            return
        except APIException:
            raise
        except Exception as e:
            logger.warning("Redis throttle check failed; using local fallback: %s", e)

    import time

    now = time.monotonic()
    attempts = _LOCAL_THROTTLE_STORE.get(ip, [])
    # Keep attempts within lockout window
    recent = [t for t in attempts if now - t < settings.login_lockout_seconds]
    _LOCAL_THROTTLE_STORE[ip] = recent
    if len(recent) >= settings.max_login_attempts:
        raise APIException(
            status_code=429,
            code="LOGIN_THROTTLED",
            message="Too many failed login attempts. Please wait before retrying.",
        )


def record_login_failure(ip: str, client: redis.Redis | None = None) -> None:
    if client:
        try:
            key = f"login_throttle:{ip}"
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, settings.login_lockout_seconds)
            pipe.execute()
            return
        except Exception as e:
            logger.warning("Redis throttle record failed; using local fallback: %s", e)

    import time

    now = time.monotonic()
    if ip not in _LOCAL_THROTTLE_STORE:
        _LOCAL_THROTTLE_STORE[ip] = []
    _LOCAL_THROTTLE_STORE[ip].append(now)


def reset_login_failures(ip: str, client: redis.Redis | None = None) -> None:
    if client:
        try:
            client.delete(f"login_throttle:{ip}")
            return
        except Exception:
            pass
    _LOCAL_THROTTLE_STORE.pop(ip, None)


def create_session(ip_address: str, client: redis.Redis | None = None) -> tuple[str, str]:
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)

    payload = {
        "csrf_token": csrf_token,
        "ip": ip_address,
    }

    if client:
        try:
            key = f"session:{session_token}"
            client.setex(key, settings.session_ttl_seconds, json.dumps(payload))
            return session_token, csrf_token
        except Exception as e:
            logger.warning("Redis session create failed; using local fallback: %s", e)

    _LOCAL_SESSION_STORE[session_token] = payload
    return session_token, csrf_token


def get_session(session_token: str, client: redis.Redis | None = None) -> dict[str, Any] | None:
    if client:
        try:
            raw = client.get(f"session:{session_token}")
            if raw:
                return json.loads(raw)
            return None
        except Exception as e:
            logger.warning("Redis session fetch failed; using local fallback: %s", e)

    return _LOCAL_SESSION_STORE.get(session_token)


def destroy_session(session_token: str, client: redis.Redis | None = None) -> None:
    if client:
        try:
            client.delete(f"session:{session_token}")
            return
        except Exception:
            pass
    _LOCAL_SESSION_STORE.pop(session_token, None)


def require_admin_session(request: Request) -> dict[str, Any]:
    """Dependency validating the HttpOnly session cookie against Redis or session store."""
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise APIException(
            status_code=401,
            code="UNAUTHORIZED",
            message="Valid admin authentication session cookie required.",
        )

    r_client = get_redis_client()
    session = get_session(session_token, r_client)
    if not session:
        raise APIException(
            status_code=401,
            code="UNAUTHORIZED",
            message="Session expired or invalid.",
        )

    return session


def require_csrf(
    request: Request,
    session: dict[str, Any] = Depends(require_admin_session),
) -> dict[str, Any]:
    """Dependency enforcing exact-origin verification and CSRF token matching for mutations."""
    check_exact_origin(request)

    expected_csrf = session.get("csrf_token")
    header_csrf = request.headers.get("X-CSRF-Token")

    if not header_csrf or not expected_csrf:
        raise APIException(
            status_code=403,
            code="CSRF_TOKEN_INVALID",
            message="Missing or empty CSRF token header (X-CSRF-Token).",
        )

    if not secrets.compare_digest(header_csrf, expected_csrf):
        raise APIException(
            status_code=403,
            code="CSRF_TOKEN_INVALID",
            message="CSRF token mismatch.",
        )

    return session
