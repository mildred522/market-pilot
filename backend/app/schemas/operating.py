from pydantic import BaseModel


class UploadResponse(BaseModel):
    project_id: int
    file_type: str
    filename: str
    storage_path: str


class OperatingAnalyzeSampleRequest(BaseModel):
    project_id: int
    question: str
