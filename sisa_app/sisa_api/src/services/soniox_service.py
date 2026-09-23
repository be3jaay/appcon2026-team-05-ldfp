import httpx

from ..config import settings


class SonioxConfigError(RuntimeError):
    pass


class SonioxRequestError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def create_temporary_key(expires_in_seconds: int) -> dict:
    if not settings.soniox_api_key:
        raise SonioxConfigError(
            "Server is missing SONIOX_API_KEY. Add it to .env (get one from console.soniox.com)."
        )

    try:
        resp = httpx.post(
            settings.soniox_temporary_key_url,
            json={
                "usage_type": "transcribe_websocket",
                "expires_in_seconds": max(1, min(expires_in_seconds, 3600)),
            },
            headers={
                "Authorization": f"Bearer {settings.soniox_api_key}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise SonioxRequestError(502, f"Failed to reach Soniox: {exc}") from exc

    if resp.status_code >= 300:
        raise SonioxRequestError(resp.status_code, resp.text)

    return resp.json()
