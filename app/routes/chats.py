from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.appwrite_client import client_manager

router = APIRouter()


class ChatRequest(BaseModel):
    user_id: str
    workspace_id: str
    chat_id: Optional[str] = None
    chat_name: Optional[str] = None
    messages: list[dict[str, Any]]


@router.post("/", tags=["chats"])
def save_chat(request: ChatRequest):
    chat_id = request.chat_id or request.chat_id or f"chat-{request.workspace_id}-{len(request.messages)}"
    try:
        payload = client_manager.upsert_chat(
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            chat_id=chat_id,
            chat_name=request.chat_name or f"Chat {len(request.messages) or 1}",
            messages=request.messages,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Appwrite chat save failed: {exc}") from exc
    return {"status": "saved", **payload}


@router.get("/{workspace_id}", tags=["chats"])
def list_chats(workspace_id: str, user_id: str):
    try:
        return {"status": "ok", "chats": client_manager.list_chats(user_id=user_id, workspace_id=workspace_id)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Appwrite chat list failed: {exc}") from exc


@router.delete("/{chat_id}", tags=["chats"])
def delete_chat(chat_id: str):
    try:
        client_manager.delete_chat(chat_id=chat_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Appwrite chat delete failed: {exc}") from exc
    return {"status": "deleted", "chat_id": chat_id}
