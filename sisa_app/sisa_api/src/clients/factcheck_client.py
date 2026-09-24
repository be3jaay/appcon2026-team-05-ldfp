"""Google Fact Check Tools API: GET /v1alpha1/claims:search.

Response shape (documented): {"claims": [{"text", "claimant", "claimDate",
"claimReview": [{"publisher": {"name", "site"}, "url", "title", "reviewDate",
"textualRating", "languageCode"}]}], "nextPageToken"}. Observed errors: 403
without a key, 400 API_KEY_INVALID with a bad one.
"""

import logging
from typing import Any

import httpx

from ..models.factcheck import PublishedFactCheck

logger = logging.getLogger(__name__)


class FactCheckClientError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class FactCheckConfigError(FactCheckClientError):
    """Missing or rejected API key: not worth retrying."""


def parse_claims(data: Any) -> list[PublishedFactCheck]:
    """One PublishedFactCheck per ClaimReview; items without a URL are skipped."""
    if not isinstance(data, dict):
        raise FactCheckClientError(502, "The Fact Check API returned an unexpected response.")
    results: list[PublishedFactCheck] = []
    for claim in data.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for review in claim.get("claimReview") or []:
            if not isinstance(review, dict) or not review.get("url"):
                continue
            publisher = review.get("publisher") or {}
            results.append(
                PublishedFactCheck(
                    claim_text=claim.get("text"),
                    claimant=claim.get("claimant"),
                    claim_date=(claim.get("claimDate") or "")[:10] or None,
                    publisher=publisher.get("name") if isinstance(publisher, dict) else None,
                    publisher_site=publisher.get("site") if isinstance(publisher, dict) else None,
                    url=review["url"],
                    title=review.get("title"),
                    review_date=(review.get("reviewDate") or "")[:10] or None,
                    rating=(review.get("textualRating") or "").strip() or None,
                    language=review.get("languageCode"),
                )
            )
    return results


class FactCheckClient:
    def __init__(
        self,
        api_key: str | None,
        url: str,
        timeout: float = 15.0,
        page_size: int = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise FactCheckConfigError(503, "FACTCHECK_API_KEY is not set.")
        self._key = api_key
        self.url = url
        self.timeout = timeout
        self.page_size = page_size
        self._transport = transport

    async def search(self, query: str, language: str | None = None) -> list[PublishedFactCheck]:
        params: dict[str, str | int] = {"query": query, "pageSize": self.page_size, "key": self._key}
        if language:
            params["languageCode"] = language
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                response = await client.get(self.url, params=params)
        except httpx.TimeoutException as exc:
            raise FactCheckClientError(504, "The Fact Check API did not respond in time.") from exc
        except httpx.RequestError as exc:
            logger.warning("Fact Check API unreachable: %s", exc)
            raise FactCheckClientError(502, "Could not reach the Fact Check API.") from exc

        if response.status_code in (401, 403) or (
            response.status_code == 400 and "API_KEY_INVALID" in response.text
        ):
            raise FactCheckConfigError(503, "The Fact Check API rejected the key. Check FACTCHECK_API_KEY.")
        if response.status_code == 429:
            raise FactCheckClientError(503, "Fact Check API quota reached. Try again later.")
        if response.status_code >= 400:
            raise FactCheckClientError(502, f"The Fact Check API returned HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise FactCheckClientError(502, "The Fact Check API returned malformed JSON.") from exc
        return parse_claims(data)
