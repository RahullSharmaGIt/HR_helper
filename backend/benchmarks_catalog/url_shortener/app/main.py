from app.rate_limiter import TokenBucketRateLimiter
from app.shortener import generate_short_code, validate_destination_url
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="Rate Limited URL Shortener", version="1.0.0")
rate_limiter = TokenBucketRateLimiter(rate=10.0, capacity=20)
url_store: dict[str, str] = {}
click_counts: dict[str, int] = {}


class ShortenRequest(BaseModel):
    url: HttpUrl
    custom_alias: str | None = None


class ShortenResponse(BaseModel):
    short_code: str
    destination_url: str
    clicks: int = 0


@app.post("/api/v1/shorten", response_model=ShortenResponse)
async def shorten_url(payload: ShortenRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    allowed, remaining = await rate_limiter.acquire(f"rl:{client_ip}")
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    clean_dest = validate_destination_url(str(payload.url))
    if payload.custom_alias:
        code = payload.custom_alias
        if code in url_store:
            raise HTTPException(status_code=409, detail="Custom alias already in use.")
    else:
        code = generate_short_code(clean_dest)

    url_store[code] = clean_dest
    click_counts[code] = 0
    return ShortenResponse(short_code=code, destination_url=clean_dest, clicks=0)


@app.get("/{short_code}")
async def redirect_url(short_code: str):
    destination = url_store.get(short_code)
    if not destination:
        raise HTTPException(status_code=404, detail="Shortened URL not found.")
    click_counts[short_code] = click_counts.get(short_code, 0) + 1
    return {"destination": destination}
