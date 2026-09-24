from fastapi import HTTPException

from ..clients.llm_chain import build_llm_client
from ..models.session_summary import SessionSummaryRequest, SessionSummaryResponse
from ..services import session_summary_service
from ..services.claims.classifier import LLMConfigError
from .claims_controller import shared_rate_limiter


async def generate(req: SessionSummaryRequest) -> SessionSummaryResponse:
    try:
        llm = build_llm_client()
    except LLMConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        # Same process-wide RateLimiter as detection/verification, so this shares the quota
        # instead of bursting past it right after a busy session ends.
        return await session_summary_service.generate(req, llm, shared_rate_limiter())
    except session_summary_service.SessionSummaryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
