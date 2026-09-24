import os

from dotenv import load_dotenv

load_dotenv()


def _csv(value: str) -> list[str]:
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


class Settings:
    soniox_api_key: str | None = os.environ.get("SONIOX_API_KEY") or None
    soniox_temporary_key_url: str = "https://api.soniox.com/v1/auth/temporary-api-key"

    # Soniox Text-to-Speech (REST): end-of-session Tagalog summary audio. Reuses SONIOX_API_KEY.
    soniox_tts_url: str = os.environ.get("SONIOX_TTS_URL", "https://tts-rt.soniox.com/tts")
    soniox_tts_model: str = os.environ.get("SONIOX_TTS_MODEL", "tts-rt-v2")
    soniox_tts_voice: str = os.environ.get("SONIOX_TTS_VOICE", "Adrian")
    soniox_tts_language: str = os.environ.get("SONIOX_TTS_LANGUAGE", "tl")
    soniox_tts_audio_format: str = os.environ.get("SONIOX_TTS_AUDIO_FORMAT", "mp3")
    soniox_tts_timeout_seconds: float = float(os.environ.get("SONIOX_TTS_TIMEOUT_SECONDS", "20"))
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

    # DPWH flood control projects, compiled by BetterGov.ph (CC0). Downloaded on first use
    # and cached on disk; refreshed when older than the max age.
    flood_control_data_url: str = os.environ.get(
        "FLOOD_CONTROL_DATA_URL",
        "https://raw.githubusercontent.com/bettergovph/bettergov/refs/heads/main/src/data/flood_control/flood_control.json",
    )
    flood_control_cache_path: str = os.environ.get("FLOOD_CONTROL_CACHE_PATH", "data/sources/flood_control.json")
    flood_control_max_age_hours: float = float(os.environ.get("FLOOD_CONTROL_MAX_AGE_HOURS", "168"))
    flood_control_timeout_seconds: float = float(os.environ.get("FLOOD_CONTROL_TIMEOUT_SECONDS", "120"))

    # Google Fact Check Tools API (published ClaimReview fact-checks). Key: Google Cloud
    # console -> enable "Fact Check Tools API" -> Credentials -> API key (starts with AIza).
    factcheck_api_key: str | None = os.environ.get("FACTCHECK_API_KEY") or None
    factcheck_api_url: str = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
    factcheck_timeout_seconds: float = float(os.environ.get("FACTCHECK_TIMEOUT_SECONDS", "15"))
    factcheck_page_size: int = int(os.environ.get("FACTCHECK_PAGE_SIZE", "10"))
    factcheck_cache_seconds: float = float(os.environ.get("FACTCHECK_CACHE_SECONDS", "86400"))

    # AI web search (last resort, after data sources and published fact-checks). Uses an
    # OpenAI search-enabled model through the Chat Completions API (idea from feat/pdm-test).
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY") or None
    openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    web_search_model: str = os.environ.get("WEB_SEARCH_MODEL", "gpt-5-search-api")
    web_search_timeout_seconds: float = float(os.environ.get("WEB_SEARCH_TIMEOUT_SECONDS", "60"))
    # Paid calls: paced, cached, and only for claims worth checking.
    web_search_rpm: float = float(os.environ.get("WEB_SEARCH_RPM", "10"))
    web_search_cache_seconds: float = float(os.environ.get("WEB_SEARCH_CACHE_SECONDS", "86400"))
    web_search_min_checkworthiness: float = float(os.environ.get("WEB_SEARCH_MIN_CHECKWORTHINESS", "0.6"))

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

    # OpenAI-compatible providers (free tiers). Model defaults may go stale:
    # if a model is retired the error lists the provider's current models.
    groq_api_key: str | None = os.environ.get("GROQ_API_KEY") or None
    groq_model: str = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    cerebras_api_key: str | None = os.environ.get("CEREBRAS_API_KEY") or None
    cerebras_model: str = os.environ.get("CEREBRAS_MODEL", "llama-3.3-70b")
    openrouter_api_key: str | None = os.environ.get("OPENROUTER_API_KEY") or None
    openrouter_model: str = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    llm_timeout_seconds: float = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
    # For reasoning models (gpt-oss, qwen3...): low | medium | high; empty = don't send.
    llm_reasoning_effort: str | None = os.environ.get("LLM_REASONING_EFFORT", "low") or None

    # Order to try providers in; the next one is used when one is busy or rate-limited.
    # Empty = every provider that has a key, in this order: groq, cerebras, openrouter, gemini.
    llm_providers: list[str] = [p.lower() for p in _csv(os.environ.get("LLM_PROVIDERS", ""))] or [
        name
        for name, key in (
            ("groq", groq_api_key),
            ("cerebras", cerebras_api_key),
            ("openrouter", openrouter_api_key),
            ("gemini", gemini_api_key),
        )
        if key
    ]
    # Pace all claim LLM calls (every session) to this many per minute; 0 = no limit.
    # Free tiers (Sept 2026): Gemini 5 req/min; Groq 8k tokens/min (~3-4 calls). When the
    # first provider is rate-limited the chain falls back to the next, so 6 uses both.
    llm_rpm: float = float(
        os.environ.get("LLM_RPM")
        or os.environ.get("GEMINI_RPM")
        or ("5" if not llm_providers or llm_providers[0] == "gemini" else "6")
    )
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
