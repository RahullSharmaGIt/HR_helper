import logging
import re
from typing import Any

# Regular expressions for identifying sensitive credentials and PII
_GITHUB_TOKEN_RE = re.compile(
    r"(?:ghp|gho|ghu|ghs|ghr|github_pat)_[a-zA-Z0-9_]{16,}",
    re.IGNORECASE,
)
_BEARER_TOKEN_RE = re.compile(
    r"(Bearer\s+)[a-zA-Z0-9_\-\.]{10,}",
    re.IGNORECASE,
)
_COOKIE_SESSION_RE = re.compile(
    r"(session_token=)[a-zA-Z0-9_\-]+",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PASSWORD_FIELD_RE = re.compile(
    r'(["\']?(?:password|admin_password|secret|token)["\']?\s*[:=]\s*["\'])([^"\',&\s]+)(["\'])',
    re.IGNORECASE,
)


def redact_sensitive_text(text: str) -> str:
    """
    Replaces sensitive access tokens, session cookies, candidate emails,
    and passwords with standardized redaction tokens.
    """
    if not isinstance(text, str):
        return text

    # Redact GitHub personal access tokens
    text = _GITHUB_TOKEN_RE.sub("[REDACTED_GITHUB_TOKEN]", text)

    # Redact Authorization Bearer headers/tokens
    text = _BEARER_TOKEN_RE.sub(r"\1[REDACTED_BEARER_TOKEN]", text)

    # Redact session cookies
    text = _COOKIE_SESSION_RE.sub(r"\1[REDACTED_COOKIE]", text)

    # Redact email addresses
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)

    # Redact structured secret fields
    text = _PASSWORD_FIELD_RE.sub(r"\1[REDACTED_SECRET]\3", text)

    return text


def _redact_arg(arg: Any) -> Any:
    if isinstance(arg, str):
        return redact_sensitive_text(arg)
    elif isinstance(arg, dict):
        return {k: _redact_arg(v) for k, v in arg.items()}
    elif isinstance(arg, (list, tuple)):
        redacted_items = [_redact_arg(item) for item in arg]
        return tuple(redacted_items) if isinstance(arg, tuple) else redacted_items
    return arg


class SensitiveDataRedactionFilter(logging.Filter):
    """
    A logging filter that intercepts log records and sanitizes tokens,
    cookies, candidate emails, and sensitive arguments before output.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact_arg(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_redact_arg(arg) for arg in record.args)

        return True


def setup_logging_redaction() -> None:
    """
    Attaches the SensitiveDataRedactionFilter to the root logger
    and all registered handlers.
    """
    redaction_filter = SensitiveDataRedactionFilter()
    root_logger = logging.getLogger()
    if not any(isinstance(f, SensitiveDataRedactionFilter) for f in root_logger.filters):
        root_logger.addFilter(redaction_filter)

    for handler in root_logger.handlers:
        if not any(isinstance(f, SensitiveDataRedactionFilter) for f in handler.filters):
            handler.addFilter(redaction_filter)
