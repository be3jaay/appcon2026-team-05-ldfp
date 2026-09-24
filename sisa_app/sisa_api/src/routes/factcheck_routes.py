from fastapi import APIRouter

from ..controllers import factcheck_controller
from ..models.factcheck import FactCheckSearchRequest, FactCheckSearchResponse, SourcesStatus

router = APIRouter(prefix="/api/v1", tags=["fact-checks"])


@router.post("/fact-checks/search", response_model=FactCheckSearchResponse)
async def search(req: FactCheckSearchRequest) -> FactCheckSearchResponse:
    """Published fact-checks (Google Fact Check Tools API) matching a claim."""
    return await factcheck_controller.search(req)


@router.get("/sources/status", response_model=SourcesStatus)
def sources_status() -> SourcesStatus:
    """Which optional sources are usable on this server (keys present)."""
    return factcheck_controller.sources_status()
