from pydantic import BaseModel, Field


class PublishedFactCheck(BaseModel):
    """One published fact-check (ClaimReview) returned by Google's Fact Check Tools API."""

    claim_text: str | None = Field(None, description="The claim the fact-checker reviewed, as they wrote it.")
    claimant: str | None = None
    claim_date: str | None = None
    publisher: str | None = None
    publisher_site: str | None = None
    url: str
    title: str | None = None
    review_date: str | None = None
    rating: str | None = Field(None, description="The fact-checker's own rating, verbatim.")
    language: str | None = None


class FactCheckSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    language: str | None = Field(None, description="BCP-47 code, e.g. 'en' or 'fil'. Omit for all languages.")


class FactCheckSearchResponse(BaseModel):
    query: str
    results: list[PublishedFactCheck]


class SourcesStatus(BaseModel):
    """Which optional sources are usable on this server (for the frontend's source list)."""

    factcheck: bool
    llm: bool
