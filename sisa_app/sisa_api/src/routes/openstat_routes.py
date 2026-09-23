from fastapi import APIRouter

from ..controllers import openstat_controller
from ..models.openstat import OpenStatCheckResponse, OpenStatClaimRequest

router = APIRouter(prefix="/api/v1/openstat", tags=["openstat"])


@router.post("/check", response_model=OpenStatCheckResponse, response_model_exclude_none=True)
async def check(req: OpenStatClaimRequest) -> OpenStatCheckResponse:
    return await openstat_controller.check_claim(req)
