from fastapi import HTTPException

from ..models.soniox import TemporaryKeyRequest
from ..services import soniox_service


def create_temporary_key(req: TemporaryKeyRequest) -> dict:
    try:
        return soniox_service.create_temporary_key(req.expires_in_seconds)
    except soniox_service.SonioxConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except soniox_service.SonioxRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
