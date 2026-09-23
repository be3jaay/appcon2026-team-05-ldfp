from fastapi import APIRouter, Depends, WebSocket

from ..controllers import claims_controller
from ..controllers.claims_controller import LLMFactory, get_llm_factory

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])


@router.websocket("/ws")
async def claims_ws(websocket: WebSocket, llm_factory: LLMFactory = Depends(get_llm_factory)) -> None:
    await claims_controller.run_session(websocket, llm_factory)
