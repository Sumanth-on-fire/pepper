from types import SimpleNamespace

from app.services.appwrite_client import client_manager


class StubDatabases:
    def __init__(self):
        self.rows = []
        self.created_rows = []

    def get(self, database_id):
        return {"$id": database_id}

    def list_rows(self, database_id, table_id, **kwargs):
        return SimpleNamespace(rows=list(self.rows))

    def create_row(self, **kwargs):
        self.created_rows.append(kwargs)
        return SimpleNamespace(**{"$id": kwargs["row_id"]})

    def upsert_row(self, **kwargs):
        self.created_rows.append(kwargs)
        return SimpleNamespace(**{"$id": kwargs["row_id"]})


class StubStorage:
    def __init__(self):
        self.created_files = []
        self.created_buckets = []

    def create_bucket(self, **kwargs):
        self.created_buckets.append(kwargs)
        return SimpleNamespace(id=kwargs["bucket_id"])

    def create_file(self, **kwargs):
        self.created_files.append(kwargs)
        return SimpleNamespace(id=kwargs["file_id"])


def test_ensure_user_bucket_creates_bucket_and_mapping(monkeypatch):
    databases = StubDatabases()
    storage = StubStorage()

    monkeypatch.setattr(client_manager, "_ensure_schema", lambda: databases)
    monkeypatch.setattr(client_manager, "_storage_client", lambda: storage)
    monkeypatch.setattr(client_manager, "_database_client", lambda: databases)

    bucket_id = client_manager.ensure_user_bucket("user-123")

    assert bucket_id == "pepper-user-user-123"
    assert storage.created_buckets[0]["bucket_id"] == bucket_id
    assert databases.created_rows[0]["data"]["user_id"] == "user-123"
    assert databases.created_rows[0]["data"]["bucket_id"] == bucket_id


def test_create_workspace_creates_virtual_folder_marker(monkeypatch):
    databases = StubDatabases()
    storage = StubStorage()

    monkeypatch.setattr(client_manager, "_ensure_schema", lambda: databases)
    monkeypatch.setattr(client_manager, "_storage_client", lambda: storage)
    monkeypatch.setattr(client_manager, "get_user_bucket_id", lambda user_id, create_if_missing=True: "user-bucket")

    result = client_manager.create_workspace("user-123", "Alpha", "alpha")

    assert result["workspace_name"] == "Alpha"
    assert storage.created_files[0]["file_id"] == "Alpha/init.txt"
    assert storage.created_files[0]["bucket_id"] == "user-bucket"
