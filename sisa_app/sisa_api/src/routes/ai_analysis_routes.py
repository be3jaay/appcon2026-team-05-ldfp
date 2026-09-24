from fastapi import APIRouter
from ..controllers import ai_analysis_controller
from ..models.ai_analysis import AIAnalysisRequest, AIAnalysisResponse
#ai_analysis_routes.py
router = APIRouter(prefix="/api/ai", tags=["ai-analysis"])


@router.post("/verify-statement", response_model=AIAnalysisResponse)
def verify_statement(req: AIAnalysisRequest) -> AIAnalysisResponse:
    return ai_analysis_controller.check_statement(req)