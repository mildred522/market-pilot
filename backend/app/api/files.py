from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

router = APIRouter(prefix="/files", tags=["files"])

UPLOAD_DIR = Path("storage/uploads")


@router.post("/upload")
async def upload_file(
    project_id: int = Form(...),
    file_type: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, str | int]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{project_id}-{file_type}-{file.filename}"
    target.write_bytes(await file.read())
    return {
        "project_id": project_id,
        "file_type": file_type,
        "filename": file.filename or "",
        "storage_path": str(target),
    }
