from typing import List, Optional

from pydantic import BaseModel


class CreateWorkspaceRequest(BaseModel):
    workspace_name: str
    user_id: Optional[str] = None


class VectorizeRequest(BaseModel):
    collection_name: str
    workspace_id: Optional[str] = None


class SearchVectorizedPDFs(BaseModel):
    collection_name: str
    query: str
    limit: int = 5


class AskAIRequest(BaseModel):
    question: str
    collection_name: str
    workspace_id: Optional[str] = None