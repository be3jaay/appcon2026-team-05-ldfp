import logging

from fastapi import HTTPException

from ..clients.official_gazette_client import OfficialGazetteClientError, OfficialGazetteURLError
from ..models.official_gazette import (
    OfficialGazetteDocument,
    OfficialGazetteDocumentRequest,
    OfficialGazetteSearchRequest,
    OfficialGazetteSearchResponse,
)
from ..services import official_gazette_service

logger = logging.getLogger(__name__)


async def search(req: OfficialGazetteSearchRequest) -> OfficialGazetteSearchResponse:
    try:
        return await official_gazette_service.search(req.query, limit=req.limit)
    except OfficialGazetteClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


async def get_document(req: OfficialGazetteDocumentRequest) -> OfficialGazetteDocument:
    try:
        return await official_gazette_service.get_document(req.url)
    except OfficialGazetteURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OfficialGazetteClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
