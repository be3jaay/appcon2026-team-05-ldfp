from fastapi import APIRouter, Depends, WebSocket

from ..controllers import claims_controller
from ..controllers.claims_controller import LLMFactory, get_llm_factory
from ..models.verification import VerificationResponse, VerifyClaimRequest

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])


@router.websocket("/ws")
async def claims_ws(websocket: WebSocket, llm_factory: LLMFactory = Depends(get_llm_factory)) -> None:
    await claims_controller.run_session(websocket, llm_factory)


@router.post("/verify", response_model=VerificationResponse)
async def verify(req: VerifyClaimRequest) -> VerificationResponse:
    return await claims_controller.verify_claim(req)
