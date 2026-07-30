import urllib3
from fastapi import APIRouter

from app.models.rag import SearchVectorizedPDFs, VectorizeRequest
from app.services.rag_client import rag_client
from app.services.workspace_registry import require_workspace, workspace_registry
from ..services.appwrite_client import client_manager
from appwrite.query import Query

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

router = APIRouter()


# @require_workspace
# async def vectorize_documents(request: VectorizeRequest):
#     project_id = client_manager.project_id
#     bucket_id = client_manager.storage_bucket_id
#     endpoint = client_manager.endpoint
#     api_key = client_manager.api_key
#     processed_files = []
#     failed_files = []

#     headers = {
#         "X-Appwrite-Project": project_id,
#         "X-Appwrite-Key": api_key,
#     }

#     collection_name = workspace_registry.resolve_collection_name(request.collection_name)

#     for file_id in request.file_ids:
#         public_url = f"{endpoint}/storage/buckets/{bucket_id}/files/{file_id}/download?project={project_id}"
#         try:
#             rag_client.save(collection_name, public_url, headers)
#             processed_files.append(file_id)
#         except Exception as exc:
#             failed_files.append({"file_id": file_id, "error": str(exc)})

#     return {
#         "message": "Processing complete",
#         "successfully_vectorized": processed_files,
#         "failed": failed_files,
#         "collection_name": collection_name,
#     }
@router.post("/", tags=["Authentication"])
def vectorize_documents(request: VectorizeRequest):
    databases = client_manager._ensure_schema()
    workspace_id = request.workspace_id
    collection_name = request.collection_name

    try:
        response = databases.list_rows(
            database_id=client_manager.database_id,
            table_id='files',
            queries=[
                Query.equal('workspace_id', workspace_id)
            ]
        )

        active_files = [dict(row.data) for row in response.rows]

    except Exception as e:
        print('Failed..., unable to fetch the files')

    processed_files = []
    failed_files = []
    for file in active_files:
        public_url = file.get('file_url')
        try:
            rag_client.save(collection_name=collection_name, public_url=public_url)
            processed_files.append(file)
        except Exception as e:
            failed_files.append(file)
            print(f"Error enable to vectorize the files... {e}")

    return {
        "message": "Processing complete",
        "successfully_vectorized": processed_files,
        "failed": failed_files,
        "collection_name": collection_name,
    }

@router.post("/search", tags=["Searching"])
@require_workspace
async def search_vectorized_files(request: SearchVectorizedPDFs):
    collection_name = workspace_registry.resolve_collection_name(request.collection_name)
    return rag_client.query(collection_name=collection_name, question=request.query, top_k=request.limit)

    