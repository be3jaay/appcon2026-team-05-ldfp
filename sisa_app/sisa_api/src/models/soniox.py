from pydantic import BaseModel


class TemporaryKeyRequest(BaseModel):
    expires_in_seconds: int = 60
