from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OFFICIAL_GAZETTE_NAME = "Official Gazette of the Republic of the Philippines"
OFFICIAL_GAZETTE_PUBLISHER = "Presidential Communications Office"

Relevance = Literal["DIRECT", "RELATED"]


class OfficialGazetteSearchRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"query": "Executive Order No. 124"},
                {"query": "The President issued Executive Order No. 124"},
            ]
        }
    )

    query: str = Field(min_length=2, max_length=300)
    limit: int = Field(10, ge=1, le=20)


class OfficialGazetteSource(BaseModel):
    name: str = OFFICIAL_GAZETTE_NAME
    source_type: Literal["OFFICIAL_DOCUMENT"] = "OFFICIAL_DOCUMENT"
    base_url: str


class OfficialGazetteResult(BaseModel):
    title: str
    document_type: str | None = Field(None, description="Parsed from the title, e.g. 'Executive Order'.")
    document_number: str | None = None
    series_year: str | None = Field(None, description="The 's. 2026' part of the title, when present.")
    date: str | None = Field(None, description="Publication date on the Official Gazette (YYYY-MM-DD).")
    url: str
    snippet: str | None = Field(None, description="Opening text of the document as published in the site feed.")
    categories: list[str] = []
    relevance: Relevance = "RELATED"


class OfficialGazetteSearchResponse(BaseModel):
    source: OfficialGazetteSource
    query: str
    search_query: str = Field(description="The query actually sent to the site's search.")
    results: list[OfficialGazetteResult]


class OfficialGazetteDocument(BaseModel):
    title: str
    document_type: str | None = None
    document_number: str | None = None
    series_year: str | None = None
    date: str | None = None
    issuing_authority: str | None = Field(None, description="Only when stated in the document text itself.")
    text: str | None = None
    text_scope: Literal["FULL_PAGE", "FEED_EXCERPT"] = Field(
        description="FEED_EXCERPT when the page was not reachable and the text is the site feed's excerpt."
    )
    url: str
    categories: list[str] = []


class OfficialGazetteDocumentRequest(BaseModel):
    url: str = Field(description="An officialgazette.gov.ph document URL, e.g. from a search result.")


class StructuredClaimContext(BaseModel):
    date: str | None = None
    geography: str | None = None


class StructuredLegalClaim(BaseModel):
    """Shape produced by the claim detector for legal claims (not extracted here)."""

    claim: str
    claim_type: str = "LEGAL"
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    context: StructuredClaimContext = StructuredClaimContext()
