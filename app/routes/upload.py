from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from ..services.supabase_client import get_supabase_client, SupabaseClient
from ..models.upload import UploadResponse
import uuid

router = APIRouter()


@router.post("/", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...), client: SupabaseClient = Depends(get_supabase_client)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")


    contents = await file.read()
    filename = file.filename
    supabase = client.supabase
    bucket_name = "KB"
    destination_path = f"documents/{filename}"
    
    try:
        _ = supabase.storage.from_(bucket_name).upload(
            path=destination_path,
            file=contents,
            file_options={"content-type": "application/pdf"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return UploadResponse(id=str(uuid.uuid4()), url=f"{client.url}/storage/v1/object/public/pdfs/{filename}", filename=filename)
