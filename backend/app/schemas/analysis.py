from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalysisChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, min_length=1, max_length=500)
    parent_version_id: int | None = Field(default=None, ge=1)
    feedback: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_initial_or_revision(self) -> "AnalysisChatRequest":
        if self.parent_version_id is None:
            if self.question is None:
                raise ValueError("question is required for a new follow-up")
            if self.feedback is not None:
                raise ValueError("feedback requires parent_version_id")
            return self
        if self.feedback is None:
            raise ValueError("feedback is required for an answer revision")
        return self
