import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OpenStatClientError(RuntimeError):

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class OpenStatClient:

    def __init__(self, table_url: str, timeout: float = 15.0):
        self.table_url = table_url
        self.timeout = timeout

    async def get_metadata(self) -> dict[str, Any]:
        return await self._request("GET", None)

    async def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", payload)

    async def _request(self, method: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method,
                    self.table_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning("OpenSTAT timeout (%s %s): %s", method, self.table_url, exc)
            raise OpenStatClientError(504, "OpenSTAT did not respond in time.") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning(
                "OpenSTAT HTTP %s (%s %s): %s", status, method, self.table_url, exc.response.text[:500]
            )
            raise _error_for_status(status) from exc
        except httpx.RequestError as exc:
            logger.warning("OpenSTAT unreachable (%s %s): %s", method, self.table_url, exc)
            raise OpenStatClientError(502, "Could not reach OpenSTAT.") from exc

        try:
            data = json.loads(response.content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("OpenSTAT returned malformed JSON (%s %s): %s", method, self.table_url, exc)
            raise OpenStatClientError(502, "OpenSTAT returned a malformed response.") from exc

        if not isinstance(data, dict):
            raise OpenStatClientError(502, "OpenSTAT returned an unexpected response shape.")
        return data


def _error_for_status(status: int) -> OpenStatClientError:
    if status == 400:
        return OpenStatClientError(502, "OpenSTAT rejected the generated query.")
    if status == 404:
        return OpenStatClientError(
            502, "The configured OpenSTAT table was not found. It may have been moved or renamed."
        )
    if status == 429:
        return OpenStatClientError(503, "OpenSTAT rate limit reached. Please try again shortly.")
    if status >= 500:
        return OpenStatClientError(502, "OpenSTAT is currently experiencing a server error.")
    return OpenStatClientError(502, f"OpenSTAT returned an unexpected HTTP {status} response.")
