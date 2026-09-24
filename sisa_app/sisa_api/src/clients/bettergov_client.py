"""Download of BetterGov.ph datasets (plain files on GitHub, CC0)."""

import logging

import httpx

logger = logging.getLogger(__name__)


class DatasetDownloadError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def download(url: str, timeout: float = 120.0, transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "SISA-FactCheck/0.1 (claim verification research prototype)"},
            transport=transport,
        ) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise DatasetDownloadError(504, "Downloading the flood control dataset timed out.") from exc
    except httpx.RequestError as exc:
        logger.warning("dataset download failed (%s): %s", url, exc)
        raise DatasetDownloadError(502, "Could not reach the flood control dataset.") from exc
    if response.status_code != 200:
        raise DatasetDownloadError(502, f"The flood control dataset returned HTTP {response.status_code}.")
    return response.content
