from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Resume Project Review API"
    app_env: str = "development"
    debug: bool = False
    database_url: str = "postgresql+psycopg://app_user:app_password@localhost:5432/resume_review"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "dev-insecure-secret-key-change-in-prod"
    storage_dir: str = "/tmp/resume_storage"

    # Authentication & Security
    admin_password_hash: str = "pbkdf2:sha256:100000$a1783fe82466dc57c90b2a01600f68f7$1c441d1969fb69f0ed7bca3b1f9b273d60efcbee6d7f729b501371c34141419e"
    admin_password: str | None = None
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "testserver",
    ]
    session_ttl_seconds: int = 86400
    max_login_attempts: int = 5
    login_lockout_seconds: int = 300

    # GitHub integration
    github_token: str | None = None
    github_api_base: str = "https://api.github.com"
    github_api_timeout_seconds: float = 10.0
    github_cache_ttl_seconds: int = 3600

    # Optional Free LLM for Intelligent Repository Matching (e.g. Gemini / Grok)
    gemini_api_key: str | None = None

    # Git fetcher & sandbox limits
    git_clone_timeout_seconds: float = 30.0
    git_blob_timeout_seconds: float = 5.0
    git_max_pack_size_bytes: int = 50 * 1024 * 1024  # 50 MB
    git_max_blob_size_bytes: int = 200 * 1024  # 200 KB
    git_max_concurrent_clones: int = 4
    git_max_blobs_per_job: int = 50
    git_max_total_blob_bytes: int = 2 * 1024 * 1024  # 2 MB

    # Intake limits
    max_upload_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_batch_size: int = 20
    max_pdf_pages: int = 20
    max_text_chars: int = 100_000
    max_docx_uncompressed_bytes: int = 30 * 1024 * 1024  # 30 MB

    # Retention & Privacy
    retention_days: int = 7

    # Test Adapters & Isolation (Forbidden in production)
    allow_test_adapters: bool = False


settings = Settings()
