from fastapi import HTTPException

from ..config import is_origin_allowed
from ..models.soniox import TemporaryKeyRequest
from ..services import soniox_service


def create_temporary_key(req: TemporaryKeyRequest, origin: str | None = None) -> dict:
    # CORS only stops browsers from reading the response; the key would still be minted.
    # Reject foreign origins before we spend a Soniox key on them.
    if not is_origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed.")
    try:
        return soniox_service.create_temporary_key(req.expires_in_seconds)
    except soniox_service.SonioxConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except soniox_service.SonioxRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
