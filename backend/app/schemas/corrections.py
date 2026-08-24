from pydantic import BaseModel, ConfigDict, Field


class CorrectionConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=36, max_length=64)
