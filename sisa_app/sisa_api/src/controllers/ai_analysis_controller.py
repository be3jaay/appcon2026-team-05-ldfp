from fastapi import HTTPException
from ..models.ai_analysis import AIAnalysisRequest, AIAnalysisResponse
from ..services import ai_analysis_service
# ai_analysis_controller.py

def check_statement(req: AIAnalysisRequest) -> AIAnalysisResponse:
    try:
        data = ai_analysis_service.analyze_statement(req.statement)
        return AIAnalysisResponse(**data)
    except ai_analysis_service.AIAnalysisError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc