import sys
import types

rag_client_stub = types.ModuleType("app.services.rag_client")
rag_client_stub.rag_client = types.SimpleNamespace(query=lambda *args, **kwargs: [])
sys.modules.setdefault("app.services.rag_client", rag_client_stub)

from app.services.gemini_orchestrator import AgentConfig


def test_token_budgets_allow_longer_responses():
    config = AgentConfig()

    assert config.max_tokens_reasoning >= 2048
    assert config.max_tokens_format >= 2048
