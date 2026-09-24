from fastapi import APIRouter

from ..controllers import official_gazette_controller
from ..models.official_gazette import (
    OfficialGazetteDocument,
    OfficialGazetteDocumentRequest,
    OfficialGazetteSearchRequest,
    OfficialGazetteSearchResponse,
)

router = APIRouter(prefix="/api/v1/official-gazette", tags=["official-gazette"])


@router.post("/search", response_model=OfficialGazetteSearchResponse)
async def search(req: OfficialGazetteSearchRequest) -> OfficialGazetteSearchResponse:
    return await official_gazette_controller.search(req)


@router.post("/document", response_model=OfficialGazetteDocument)
async def document(req: OfficialGazetteDocumentRequest) -> OfficialGazetteDocument:
    return await official_gazette_controller.get_document(req)
