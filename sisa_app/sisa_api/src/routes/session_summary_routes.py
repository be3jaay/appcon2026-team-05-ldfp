from fastapi import APIRouter

from ..controllers import session_summary_controller
from ..models.session_summary import SessionSummaryRequest, SessionSummaryResponse

router = APIRouter(prefix="/api/v1/session-summary", tags=["session-summary"])


@router.post("", response_model=SessionSummaryResponse)
async def session_summary(req: SessionSummaryRequest) -> SessionSummaryResponse:
    """Tagalog spoken analysis of a finished session (transcript + claims + evidence the
    client already has), synthesized to audio with Soniox TTS."""
    return await session_summary_controller.generate(req)
