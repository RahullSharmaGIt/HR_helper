import json
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import (
    APIException,
    api_exception_handler,
    api_router,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.config import settings
from app.services.log_redaction import setup_logging_redaction


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path in {"/docs", "/redoc"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "connect-src 'self' https://cdn.jsdelivr.net; "
                "frame-ancestors 'none'; base-uri 'self'; object-src 'none';"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none';"
            )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


class CrossOriginProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            clean_origin = origin.rstrip("/")
            if (
                clean_origin not in settings.allowed_origins
                and origin not in settings.allowed_origins
            ):
                req_id = getattr(request.state, "request_id", "")
                return JSONResponse(
                    status_code=403,
                    content={
                        "code": "INVALID_ORIGIN",
                        "message": f"Request origin '{origin}' is not allowed by policy.",
                        "requestId": req_id,
                    },
                    headers={"X-Request-ID": req_id},
                )
        return await call_next(request)


def create_app() -> FastAPI:
    # Reject test adapters in production mode
    if settings.app_env == "production" and settings.allow_test_adapters:
        raise RuntimeError(
            "Production startup rejected: test adapters cannot be enabled in production."
        )

    # Initialize structured log redaction filter
    setup_logging_redaction()

    app = FastAPI(
        title="Resume Project Review API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Middleware execution: Outer -> Inner
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CrossOriginProtectionMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception Handlers
    app.add_exception_handler(APIException, api_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Health check (unauthenticated)
    @app.get("/health", summary="Health check")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    # Include versioned API router
    app.include_router(api_router)

    return app


def export_openapi(output_path: Path | str | None = None) -> Path:
    """Exports OpenAPI specification deterministically with sorted keys."""
    app = create_app()
    openapi_schema = app.openapi()
    target_path = (
        Path(output_path)
        if output_path
        else Path(__file__).resolve().parent.parent / "openapi.json"
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, sort_keys=True)
        f.write("\n")
    return target_path


app = create_app()

if __name__ == "__main__":
    export_openapi()
