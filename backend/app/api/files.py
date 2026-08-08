from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models import Project, UploadedFile
from app.db.session import get_db
from app.schemas.operating import UploadResponse
from app.services.csv_ingestion_service import (
    CSV_FILE_TYPES,
    CsvIngestionError,
    mapping_summary,
    read_csv_bytes,
)

router = APIRouter(prefix="/files", tags=["files"])

UPLOAD_DIR = Path("storage/uploads")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    project_id: int = Form(...),
    file_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": "project not found"})
    if project.stage != "operating":
        raise HTTPException(status_code=422, detail={"code": "invalid_project_stage", "message": "CSV uploads require an operating project"})
    if file_type not in CSV_FILE_TYPES:
        raise HTTPException(status_code=422, detail={"code": "invalid_file_type", "message": "unsupported CSV file type"})
    original_name = Path(file.filename or "upload.csv").name
    if Path(original_name).suffix.lower() != ".csv":
        raise HTTPException(status_code=422, detail={"code": "invalid_file_extension", "message": "only CSV files are supported"})
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail={"code": "file_too_large", "message": "CSV file exceeds 5 MB"})
    try:
        frame = read_csv_bytes(data)
        summary = mapping_summary(frame, file_type)
    except CsvIngestionError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": str(error)}) from error
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{project_id}-{file_type}-{uuid4().hex}.csv"
    target.write_bytes(data)
    row = UploadedFile(
        project_id=project_id,
        file_type=file_type,
        original_name=original_name,
        storage_path=str(target),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return UploadResponse(
        file_id=row.id,
        project_id=project_id,
        file_type=file_type,
        filename=original_name,
        **summary,
    )
