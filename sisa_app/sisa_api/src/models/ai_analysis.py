from typing import Literal
from pydantic import BaseModel, Field

class AIAnalysisRequest(BaseModel):
    statement: str = Field(..., description="The statement to verify.")

class AIAnalysisResponse(BaseModel):
    statement: str
    verdict: Literal["factual", "misleading", "needscontext", "unfounded"] = Field(
        ..., description="The evaluation category of the statement."
    )
    reasoning: str
    sources: list[str] = Field(default=[], description="Source URLs used for verification.")
    
    # Evasion and subtext metrics
    evasion_detected: bool = Field(default=False, description="Whether the speaker is dodging or avoiding the core issue.")
    evasion_details: str = Field(default="", description="Explanation of what they are avoiding, if applicable.")
    emotion: str = Field(default="neutral", description="Detected primary emotion or tone.")
    fallacy: str = Field(default="none", description="Any logical fallacy identified.")
    subtext_or_extrinsic_dialogue: str = Field(default="", description="Hidden motives or underlying agendas.")