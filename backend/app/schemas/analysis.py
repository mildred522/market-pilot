from pydantic import BaseModel, ConfigDict, Field


class AnalysisChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)
