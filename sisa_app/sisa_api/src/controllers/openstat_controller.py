import logging

from fastapi import HTTPException

from ..clients.openstat_client import OpenStatClientError
from ..models.openstat import OpenStatCheckResponse, OpenStatClaimRequest
from ..services import openstat_service
from ..services.openstat_parser import OpenStatParseError

logger = logging.getLogger(__name__)


async def check_claim(req: OpenStatClaimRequest) -> OpenStatCheckResponse:
    try:
        return await openstat_service.check_claim(req)
    except openstat_service.UnsupportedMetricError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OpenStatClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except OpenStatParseError as exc:
        logger.warning("OpenSTAT response could not be interpreted: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="OpenSTAT returned data in an unexpected structure.",
        ) from exc
