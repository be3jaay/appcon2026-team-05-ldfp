from pydantic import BaseModel, Field

class AIAnalysisRequest(BaseModel):
    statement: str = Field(..., description="The statement to verify.")

class AIAnalysisResponse(BaseModel):
    statement: str
    is_true: bool
    reasoning: str
    sources: list[str] = Field(default=[], description="List of source URLs/links used for verification.")