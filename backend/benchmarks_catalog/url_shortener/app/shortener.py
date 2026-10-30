import hashlib
import re

BASE62_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def generate_short_code(url: str, length: int = 7) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).digest()
    num = int.from_bytes(digest[:8], byteorder="big")
    chars = []
    while num > 0 and len(chars) < length:
        num, rem = divmod(num, 62)
        chars.append(BASE62_ALPHABET[rem])
    code = "".join(chars)
    return code.ljust(length, "0")


def validate_destination_url(url: str) -> str:
    cleaned = url.strip()
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise ValueError("URL must start with http:// or https://")
    private_pattern = re.compile(
        r"^https?://(?:localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01]))"
    )
    if private_pattern.match(cleaned):
        raise ValueError("Private IP destinations and local networks are forbidden.")
    return cleaned
