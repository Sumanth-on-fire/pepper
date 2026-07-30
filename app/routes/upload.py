from typing import Optional
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.services.workspace_registry import require_workspace, workspace_registry
from ..models.upload import UploadResponse
from ..services.appwrite_client import client_manager

try:
    from appwrite.id import ID
    from appwrite.input_file import InputFile
except ImportError:  # pragma: no cover - optional dependency handling
    ID = None
    InputFile = None

router = APIRouter()


@router.post("/", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    collection_name: Optional[str] = Form(default=None),
    workspace_name: Optional[str] = Form(default=None),
    workspace_id: Optional[str] = Form(default=None),
    user_id: Optional[str] = Form(default=None),
    deps: tuple = Depends(client_manager.get_appwrite_storage),
):
    effective_collection_name = collection_name or workspace_name
    # try:
    #     workspace_registry.ensure_workspace(effective_collection_name)
    # except ValueError as exc:
    #     raise HTTPException(status_code=400, detail=str(exc)) from exc

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    storage, endpoint = client_manager.get_appwrite_storage()
    bucket_id = client_manager.storage_bucket_id
    project_id = client_manager.project_id
    contents = await file.read()

    try:
        if InputFile is None or ID is None:
            raise RuntimeError("Appwrite SDK is not available in this environment.")

        input_file = InputFile.from_bytes(
            bytes=contents,
            filename=file.filename,
            mime_type="application/pdf",
        )
        result = storage.create_file(
            bucket_id=bucket_id,
            file_id=ID.unique(),
            file=input_file,
        )
        file_id = result.id
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    public_url = f"{endpoint}/storage/buckets/{bucket_id}/files/{file_id}/view?project={project_id}"

    file_record = None
    file_record = client_manager.create_file_record(
        workspace_id=workspace_id,
        file_name=file.filename or "uploaded.pdf",
        file_url=public_url,
        file_id=file_id,
    )
    
    
    return {
        "id": str(uuid.uuid4()),
        "url": public_url,
        "filename": file.filename,
        "file_id": file_record.get("file_id") if file_record else None,
        "storage_file_id": file_id,
        "workspace_id": workspace_id,
        "collection_name": effective_collection_name,
    }
