from fastapi import APIRouter

from ..controllers import soniox_controller
from ..models.soniox import TemporaryKeyRequest

router = APIRouter(prefix="/api/soniox", tags=["soniox"])


@router.post("/temporary-key")
def temporary_key(req: TemporaryKeyRequest) -> dict:
    return soniox_controller.create_temporary_key(req)
