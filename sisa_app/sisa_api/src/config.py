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

    # Official Gazette (primary source for laws and executive issuances).
    # Search uses the site's own WordPress search delivered as RSS (/feed/?s=...);
    # HTML pages sit behind a Cloudflare challenge and usually cannot be fetched.
    official_gazette_base_url: str = os.environ.get(
        "OFFICIAL_GAZETTE_BASE_URL", "https://www.officialgazette.gov.ph"
    )
    official_gazette_timeout_seconds: float = float(os.environ.get("OFFICIAL_GAZETTE_TIMEOUT_SECONDS", "20"))
    official_gazette_user_agent: str = os.environ.get(
        "OFFICIAL_GAZETTE_USER_AGENT", "SISA-FactCheck/0.1 (claim verification research prototype)"
    )
    # Be polite: at most this many requests per minute to the site from this process.
    official_gazette_rpm: float = float(os.environ.get("OFFICIAL_GAZETTE_RPM", "30"))
    official_gazette_cache_seconds: float = float(os.environ.get("OFFICIAL_GAZETTE_CACHE_SECONDS", "600"))

    # Claim detection (Gemini).
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY") or None
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    gemini_timeout_seconds: float = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "30"))
    # minimal | low | medium | high. Lower = faster; empty string = model default.
    gemini_thinking_level: str | None = os.environ.get("GEMINI_THINKING_LEVEL", "low") or None
    # Pace all claim LLM calls (every session) to this many per minute. Free tier: 5. 0 = no limit.
    gemini_rpm: float = float(os.environ.get("GEMINI_RPM", "5"))
    claims_llm_max_attempts: int = int(os.environ.get("CLAIMS_LLM_MAX_ATTEMPTS", "4"))
    # Batches that queue up while waiting for a call slot are merged, up to this many segments.
    claims_max_segments_per_call: int = int(os.environ.get("CLAIMS_MAX_SEGMENTS_PER_CALL", "8"))
    claims_batch_max_segments: int = int(os.environ.get("CLAIMS_BATCH_MAX_SEGMENTS", "3"))
    claims_batch_max_wait_s: float = float(os.environ.get("CLAIMS_BATCH_MAX_WAIT_S", "15"))
    claims_context_segments: int = int(os.environ.get("CLAIMS_CONTEXT_SEGMENTS", "2"))

    log_level: str = os.environ.get("LOG_LEVEL", "INFO").upper()


settings = Settings()


def is_origin_allowed(origin: str | None) -> bool:
    """Requests without an Origin header (curl, server-to-server) pass; browsers must match."""
    if origin is None:
        return True
    return origin.rstrip("/") in settings.cors_allow_origins
