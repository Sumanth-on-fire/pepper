from fastapi import APIRouter

from app.models.rag import AskAIRequest
from app.services.gemini_orchestrator import GeminiOrchestrator
from app.services.workspace_registry import require_workspace, workspace_registry

router = APIRouter()
orchestrator = GeminiOrchestrator()


@router.post("/ask", tags=["ASK AI"])
async def ask_ai(request: AskAIRequest):
    # collection_name = workspace_registry.resolve_collection_name(request.collection_name)
    result = orchestrator.generate_answer(
        question=request.question,
        collection_name=request.collection_name,
        tool_schema=orchestrator.build_tool_definition(),
    )
    return {
        "answer": result.get("answer"),
        "collection_name": request.collection_name,
        "evidence": result.get("evidence", []),
    }