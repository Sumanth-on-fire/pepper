import logging

from fastapi import APIRouter, HTTPException

from app.models.rag import CreateWorkspaceRequest
from app.services.appwrite_client import client_manager
from app.services.workspace_registry import workspace_registry

router = APIRouter()
logger = logging.getLogger("create_workspace")


@router.get("/fetch", tags=["workspace"])
def list_workspaces(user_id: str):
    try:
        return {"status": "ok", "workspaces": client_manager.list_workspace_details(user_id)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Appwrite database is unavailable: {exc}") from exc


@router.post("/create", tags=["workspace"])
def create_workspace(request: CreateWorkspaceRequest):
    payload = workspace_registry.create_workspace(request.workspace_name)
    try:
        appwrite_payload = client_manager.create_workspace(
            user_id=request.user_id or "anonymous",
            workspace_name=request.workspace_name,
            collection_name=payload["collection_name"],
        )
    except Exception as exc:
        logger.warning("Appwrite workspace save failed: %s", exc)
        appwrite_payload = {
            "workspace_id": None,
            "workspace_name": request.workspace_name,
            "collection_name": payload["collection_name"],
        }
    return {"status": "created", **payload, **appwrite_payload}
