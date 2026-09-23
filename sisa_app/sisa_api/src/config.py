import os

from dotenv import load_dotenv

load_dotenv()


def _csv(value: str) -> list[str]:
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


class Settings:
    soniox_api_key: str | None = os.environ.get("SONIOX_API_KEY") or None
    soniox_temporary_key_url: str = "https://api.soniox.com/v1/auth/temporary-api-key"
    # Browser origins allowed to call the API (CORS) and open websockets.
    # Comma-separated, e.g. "http://localhost:3000,https://sisa.example.com".
    cors_allow_origins: list[str] = _csv(
        os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:3000")
    )

    # PSA OpenSTAT PXWeb API. GET returns table metadata, POST runs a query.
    # Table: Labor Force Survey > "Rates Key Employment Indicators".
    openstat_unemployment_url: str = os.environ.get(
        "OPENSTAT_UNEMPLOYMENT_URL",
        "https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB/1B/LFS/0021B3FKEI2.px",
    )
    # Human-facing page for the same table, for source citations.
    openstat_unemployment_page_url: str = (
        "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__1B__LFS/0021B3FKEI2.px/"
    )
    openstat_timeout_seconds: float = 15.0

    # Claim detection (Gemini).
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY") or None
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_timeout_seconds: float = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "30"))
    # 0 turns thinking off on 2.5 Flash for low latency; unset leaves the model default.
    gemini_thinking_budget: int | None = (
        int(os.environ["GEMINI_THINKING_BUDGET"]) if os.environ.get("GEMINI_THINKING_BUDGET") else 0
    )
    claims_batch_max_segments: int = int(os.environ.get("CLAIMS_BATCH_MAX_SEGMENTS", "3"))
    claims_batch_max_wait_s: float = float(os.environ.get("CLAIMS_BATCH_MAX_WAIT_S", "15"))
    claims_context_segments: int = int(os.environ.get("CLAIMS_CONTEXT_SEGMENTS", "2"))


settings = Settings()


def is_origin_allowed(origin: str | None) -> bool:
    """Requests without an Origin header (curl, server-to-server) pass; browsers must match."""
    if origin is None:
        return True
    return origin.rstrip("/") in settings.cors_allow_origins
