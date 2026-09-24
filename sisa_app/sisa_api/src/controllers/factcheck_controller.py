from fastapi import HTTPException

from ..clients.factcheck_client import FactCheckClientError
from ..clients.llm_chain import build_llm_client
from ..models.factcheck import FactCheckSearchRequest, FactCheckSearchResponse, SourcesStatus
from ..services import factcheck_service
from ..services.claims.classifier import LLMConfigError


async def search(req: FactCheckSearchRequest) -> FactCheckSearchResponse:
    try:
        return await factcheck_service.search(req.query, req.language)
    except FactCheckClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def sources_status() -> SourcesStatus:
    try:
        build_llm_client()
        llm = True
    except LLMConfigError:
        llm = False
    return SourcesStatus(factcheck=factcheck_service.is_configured(), llm=llm)
