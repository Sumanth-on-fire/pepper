import io

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_create_workspace_registers_collection_name():
    response = client.post(
        "/api/v1/create_workspace/",
        json={"workspace_name": "Alpha"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_name"] == "Alpha"
    assert payload["collection_name"] == "Alpha"


def test_upload_requires_workspace(monkeypatch):
    monkeypatch.setattr(
        "app.routes.upload.client_manager.get_appwrite_storage",
        lambda: (object(), "https://example.com"),
    )

    response = client.post(
        "/api/v1/upload/",
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )

    assert response.status_code == 400
    assert "workspace" in response.json()["detail"].lower()


def test_ask_ai_requires_workspace(monkeypatch):
    monkeypatch.setattr(
        "app.routes.ask_ai.GeminiOrchestrator.generate_answer",
        lambda self, question, context=None, tool_schema=None, collection_name=None, **kwargs: {"answer": "stubbed"},
    )

    response = client.post(
        "/api/v1/ask_ai/ask",
        json={"question": "What is in the document?"},
    )

    assert response.status_code == 400
    assert "workspace" in response.json()["detail"].lower()
