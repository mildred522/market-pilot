from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    stage: str = Field(pattern="^(pre_open|operating)$")


class ProjectRead(BaseModel):
    id: int
    name: str
    stage: str

    model_config = {"from_attributes": True}
