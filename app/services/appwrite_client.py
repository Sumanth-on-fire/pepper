import inspect
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.singleton import singleton

from ..core.config import Settings

try:
    from appwrite.client import Client
    from appwrite.exception import AppwriteException
    from appwrite.id import ID
    from appwrite.input_file import InputFile
    from appwrite.query import Query
    from appwrite.services.tables_db import TablesDB
    from appwrite.services.storage import Storage
except ImportError:  # pragma: no cover - optional dependency handling
    Client = Any  # type: ignore[assignment]
    AppwriteException = Exception  # type: ignore[assignment]
    ID = None
    InputFile = None
    Query = None
    TablesDB = None
    Storage = None

logger = logging.getLogger("appwrite_client")


WORKSPACES_COLLECTION_ID = "workspaces"
FILES_COLLECTION_ID = "files"
CHATS_COLLECTION_ID = "chats"
PROFILES_COLLECTION_ID = "profiles"
USER_BUCKETS_COLLECTION_ID = "user_bucket"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _model_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_map"):
        return value.to_map()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(getattr(value, "__dict__", {}))


@singleton
class AppwriteClientManager:
    def __init__(self) -> None:
        self.settings = Settings()
        self.endpoint = self.settings.APPWRITE_URL
        self.project_id = self.settings.APPWRITE_ID
        self.api_key = self.settings.APPWRITE_KEY
        self.storage_bucket_id = self.settings.APPWRITE_STR
        self.database_id = self.settings.APPWRITE_DB_ID

    def get_admin_client(self) -> Any:
        """Returns a master client authenticated with the API key."""
        if Client is Any:
            return None
        client = Client()
        client.set_endpoint(self.endpoint).set_project(self.project_id).set_key(self.api_key)
        return client

    def get_user_client(self, session_token: Optional[str] = None) -> Any:
        """Returns a client scoped specifically to an active user's session token."""
        if Client is Any:
            return None
        client = Client()
        client.set_endpoint(self.endpoint).set_project(self.project_id)
        if session_token:
            client.set_session(session_token)
        return client

    def get_appwrite_storage(self) -> tuple[Any, str]:
        client = self.get_admin_client()
        if Storage is None:
            return None, self.endpoint
        storage = Storage(client=client)
        return storage, self.endpoint

    def _storage_client(self) -> Any:
        client = self.get_admin_client()
        if Storage is None:
            return None
        return Storage(client=client)

    def _database_client(self) -> Any:
        client = self.get_admin_client()
        if TablesDB is None:
            return None
        return TablesDB(client=client)

    def _ensure_database(self, databases: Any) -> None:
        try:
            databases.get(database_id=self.database_id)
        except Exception as exc:
            if not self._is_appwrite_error(exc, 404):
                raise
            databases.create(database_id=self.database_id, name="Pepper", enabled=True)

    def _ensure_collection(self, databases: Any, collection_id: str, name: str, attributes: list[tuple[str, str]]) -> None:
        try:
            databases.get_table(database_id=self.database_id, table_id=collection_id)
        except Exception as exc:
            if not self._is_appwrite_error(exc, 404):
                print("404 database get error")
                raise
            try:
                databases.create_table(
                    database_id=self.database_id,
                    table_id=collection_id,
                    name=name,
                    permissions=None,
                    row_security=False,
                    enabled=True,
                )
            except Exception as e:
                print("Failed to create a database....")

        for key, kind in attributes:
            self._ensure_attribute(databases, collection_id, key, kind)

    def _ensure_attribute(self, databases: Any, collection_id: str, key: str, kind: str) -> None:
        try:
            attribute = databases.get_column(self.database_id, collection_id, key)
            if _model_to_dict(attribute).get("status") == "available":
                return
        except Exception as exc:
            if not self._is_appwrite_error(exc, 404):
                print("404 appwrite error")
                raise
            try:
                if kind == "datetime":
                    databases.create_datetime_column(self.database_id, collection_id, key, False)
                elif kind == "email":
                    databases.create_email_column(self.database_id, collection_id, key, False)
                elif kind == "longtext":
                    databases.create_longtext_column(self.database_id, collection_id, key, False)
                else:
                    databases.create_text_column(self.database_id, collection_id, key, False)
            except Exception as create_exc:
                print("something failed here either datetime, longtest, email")
                if not self._is_appwrite_error(create_exc, 409):
                    raise

        for _ in range(12):
            try:
                attribute = databases.get_column(self.database_id, collection_id, key)
                if _model_to_dict(attribute).get("status") == "available":
                    return
            except Exception:
                pass
            time.sleep(0.5)

    def _ensure_schema(self, check_if_database_initialized=False) -> Any:
        try:
            databases = self._database_client()
        except Exception as e:
            print("Data based did not get initialized")

        if databases is None or ID is None:
            raise RuntimeError("Appwrite database SDK is unavailable.")

        if check_if_database_initialized:
            try:
                self._ensure_database(databases)
            except Exception as e:
                print("Failed to ensure schema")

            try:
                self._ensure_collection(
                    databases,
                    PROFILES_COLLECTION_ID,
                    "Profiles",
                    [
                        ("user_id", "string"),
                        ("email", "email"),
                        ("username", "string"),
                        ("display_name", "string"),
                        ("created_at", "datetime"),
                        ("updated_at", "datetime"),
                    ],
                )
            except Exception as e:
                print("Failed to ensure profiles collections")

            try:
                self._ensure_collection(
                    databases,
                    USER_BUCKETS_COLLECTION_ID,
                    "User Buckets",
                    [
                        ("user_id", "string"),
                        ("bucket_id", "string"),
                        ("created_at", "datetime"),
                    ],
                )
            except Exception as e:
                print("User buckets not initialized")

            try:
                self._ensure_collection(
                    databases,
                    WORKSPACES_COLLECTION_ID,
                    "Workspaces",
                    [
                        ("user_id", "string"),
                        ("workspace_name", "string"),
                        ("collection_name", "string"),
                        ("created_at", "datetime"),
                        ("updated_at", "datetime"),
                    ],
                )
            except Exception as e:
                print("Workspaces not initialized correctly")

            try:
                self._ensure_collection(
                    databases,
                    FILES_COLLECTION_ID,
                    "Files",
                    [
                        ("workspace_id", "string"),
                        ("file_name", "string"),
                        ("file_url", "string"),
                        ("storage_file_id", "string"),
                        ("created_at", "datetime"),
                    ],
                )
            except Exception as e:
                print("files collection not initializeed properly.")

            try:
                self._ensure_collection(
                    databases,
                    CHATS_COLLECTION_ID,
                    "Chats",
                    [
                        ("user_id", "string"),
                        ("workspace_id", "string"),
                        ("chat_name", "string"),
                        ("messages_json", "longtext"),
                        ("created_at", "datetime"),
                        ("updated_at", "datetime"),
                    ],
                )
            except Exception as e:
                print("chats collections not initialized properly.")

        return databases

    def _list_table_rows(self, databases: Any, table_id: str) -> list[dict[str, Any]]:
        if databases is None:
            return []
        try:
            response = databases.list_rows(
                database_id=self.database_id,
                table_id=table_id,
                model_type=dict,
            )
        except Exception:
            return []
        payload = _model_to_dict(response)
        return [_model_to_dict(row) for row in payload.get("rows", [])]

    def _sanitize_storage_path_segment(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", value or "workspace").strip("-") or "workspace"

    def _build_workspace_file_id(self, workspace_name: str, file_name: str) -> str:
        workspace_segment = self._sanitize_storage_path_segment(workspace_name)
        file_segment = self._sanitize_storage_path_segment(file_name)
        return f"{workspace_segment}-{file_segment}"

    def _create_storage_bucket(self, storage: Any, bucket_id: str, name: str) -> Any:
        if storage is None:
            raise RuntimeError("Appwrite storage SDK is unavailable.")

        candidate_kwargs = [
            {"bucket_id": bucket_id, "name": name, "permissions": None, "file_security": False, "enabled": True},
            {"bucket_id": bucket_id, "name": name, "file_security": False, "enabled": True},
            {"bucket_id": bucket_id, "name": name, "permissions": None},
            {"bucket_id": bucket_id, "name": name},
        ]
        last_error: Optional[Exception] = None
        for kwargs in candidate_kwargs:
            try:
                return storage.create_bucket(**kwargs)
            except TypeError as exc:
                last_error = exc
            except Exception:
                raise
        if last_error is not None:
            raise last_error
        return None

    def ensure_user_bucket_legacy(self, user_id: str) -> str:
        if not user_id:
            return self.storage_bucket_id

        databases = self._ensure_schema()
        rows = self._list_table_rows(databases, USER_BUCKETS_COLLECTION_ID)
        for row in rows:
            if row.get("user_id") == user_id and row.get("bucket_id"):
                return str(row.get("bucket_id"))

        bucket_id = f"pepper-user-{self._sanitize_storage_path_segment(user_id)}"
        storage = self._storage_client()
        if storage is not None:
            try:
                self._create_storage_bucket(storage, bucket_id, f"User bucket for {user_id}")
            except Exception as exc:
                if not self._is_appwrite_error(exc, 409):
                    logger.warning("Bucket creation skipped for user %s: %s", user_id, exc)

        payload = {
            "user_id": user_id,
            "bucket_id": bucket_id,
            "created_at": _utc_now(),
        }
        row_id = ID.unique() if ID is not None else f"bucket-{datetime.now(timezone.utc).timestamp()}"
        databases.create_row(
            database_id=self.database_id,
            table_id=USER_BUCKETS_COLLECTION_ID,
            row_id=row_id,
            data=payload,
            model_type=dict,
        )
        return bucket_id

    def ensure_user_bucket(self, user_id: str) -> str:
        bucket_id = self.storage_bucket_id    
        storage = self._storage_client()

        if storage is not None and InputFile is not None:
            marker_file_id = self._build_workspace_file_id(user_id, "init.txt")
            input_file = InputFile.from_bytes(b"", filename=".keep", mime_type="text/plain")
            try:
                storage.create_file(bucket_id=bucket_id, file_id=marker_file_id, file=input_file)
            except Exception as exc:
                logger.warning("Workspace marker creation skipped for %s: %s", user_id, exc)

        return bucket_id
    
    def get_user_bucket_id(self, user_id: str, create_if_missing: bool = True) -> str:
        return self.storage_bucket_id

    @staticmethod
    def _is_appwrite_error(exc: Exception, status_code: int) -> bool:
        return isinstance(exc, AppwriteException) and getattr(exc, "code", None) == status_code

    def _list_documents(self, collection_id: str, workspace_id: str=None) -> list[dict[str, Any]]:
        databases = self._ensure_schema()
        queries = [Query.equal('workspace_id', workspace_id) if workspace_id else Query.limit(100)] if Query is not None else None
        documents = databases.list_rows(
            database_id=self.database_id,
            table_id=collection_id,
            queries=queries,
            model_type=dict,
        )
        workspace_file_names = [dict(row.data) for row in documents.rows]
        # payload = _model_to_dict(documents)
        # return [_model_to_dict(row) for row in payload.get("rows", [])]
        return workspace_file_names

    def _document_id(self, document: dict[str, Any]) -> str:
        return str(document.get("$id") or document.get("id") or "")

    def _write_json_document(self, file_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        storage = self._storage_client()
        if storage is None or InputFile is None or ID is None:
            raise RuntimeError("Appwrite storage SDK is unavailable.")

        serialised = json.dumps(payload).encode("utf-8")
        input_file = InputFile.from_bytes(bytes=serialised, filename=file_name, mime_type="application/json")
        result = storage.create_file(bucket_id=self.storage_bucket_id, file_id=ID.unique(), file=input_file)
        return {"file_id": result.id, "file_name": file_name}

    def _read_json_document(self, file_name: str) -> Optional[dict[str, Any]]:
        storage = self._storage_client()
        if storage is None:
            return None

        try:
            files = storage.list_files(bucket_id=self.storage_bucket_id, search=file_name)
        except Exception:
            return None

        for file in getattr(files, "files", []):
            if getattr(file, "name", "") == file_name:
                try:
                    file_data = storage.get_file_download(bucket_id=self.storage_bucket_id, file_id=file.id)
                    if isinstance(file_data, dict):
                        return file_data
                    return json.loads(file_data.decode("utf-8")) if isinstance(file_data, bytes) else None
                except Exception:
                    return None
        return None

    def _list_json_documents(self, prefix: str) -> list[dict[str, Any]]:
        storage = self._storage_client()
        if storage is None:
            return []

        try:
            files = storage.list_files(bucket_id=self.storage_bucket_id)
        except Exception:
            return []

        records: list[dict[str, Any]] = []
        for file in getattr(files, "files", []):
            name = getattr(file, "name", "")
            if name.startswith(prefix):
                try:
                    file_data = storage.get_file_download(bucket_id=self.storage_bucket_id, file_id=file.id)
                    if isinstance(file_data, dict):
                        records.append(file_data)
                    elif isinstance(file_data, bytes):
                        records.append(json.loads(file_data.decode("utf-8")))
                except Exception:
                    continue
        return records

    def create_workspace(self, user_id: str, workspace_name: str, collection_name: str) -> dict[str, Any]:
        if not user_id:
            user_id = "anonymous"
        workspace_id = ID.unique() if ID is not None else f"workspace-{datetime.now(timezone.utc).timestamp()}"
        timestamp = _utc_now()
        payload = {
            "user_id": user_id,
            "workspace_name": workspace_name,
            "workspace_id": workspace_id,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        databases = self._ensure_schema()
        databases.create_row(
            database_id=self.database_id,
            table_id=WORKSPACES_COLLECTION_ID,
            row_id=workspace_id,
            data=payload,
            model_type=dict,
        )

        # bucket_id = self.get_user_bucket_id(user_id, create_if_missing=True)
        bucket_id = self.storage_bucket_id
        storage = self._storage_client()
        if storage is not None and InputFile is not None:
            marker_file_id = self._build_workspace_file_id(workspace_name, "init.txt")
            input_file = InputFile.from_bytes(b"", filename=".keep", mime_type="text/plain")
            try:
                storage.create_file(bucket_id=bucket_id, file_id=marker_file_id, file=input_file)
            except Exception as exc:
                logger.warning("Workspace marker creation skipped for %s: %s", workspace_name, exc)

        return {"workspace_id": workspace_id, "workspace_name": workspace_name, "collection_name": collection_name}

    # def list_workspaces(self, user_id: str) -> list[dict[str, Any]]:
    #     records = self._list_documents(WORKSPACES_COLLECTION_ID)
    #     filtered = [
    #         {
    #             "workspace_id": self._document_id(item),
    #             "workspace_name": item.get("workspace_name"),
    #             "collection_name": item.get("collection_name"),
    #             "created_at": item.get("created_at"),
    #             "updated_at": item.get("updated_at"),
    #         }
    #         for item in records
    #         if item.get("user_id") == user_id
    #     ]
    #     return sorted(filtered, key=lambda item: item.get("created_at") or "", reverse=True)

    def list_workspaces(self, user_id: str) -> list[str]:
        databases = self._ensure_schema()

        try:
            response = databases.list_rows(
                database_id=self.database_id,
                table_id=WORKSPACES_COLLECTION_ID,
                queries=[
                    Query.equal('user_id', user_id)
                ]
            )
        except Exception as e:
            print('Failed to fetch workspace list')

        try:
            active_workspaces = [dict(row.data) for row in response.rows]
            print(active_workspaces)
        except Exception as e:
            print('Failed to get rows from the response')

        return active_workspaces
    
    def list_workspace_details(self, user_id: str) -> list[dict[str, Any]]:
        try:
            workspaces = self.list_workspaces(user_id)
        except Exception as e:
            print("Failed to list the workspace details due to list_workspaces")
        return [
            {
                **workspace,
                "files": self.list_file_records(workspace["workspace_id"]),
                "chats": self.list_chats(user_id=user_id, workspace_id=workspace["workspace_id"]),
            }
            for workspace in workspaces
        ]

    def find_workspace(self, workspace_id: str) -> Optional[dict[str, Any]]:
        records = self._list_documents(WORKSPACES_COLLECTION_ID, workspace_id)
        for item in records:
            if self._document_id(item) == workspace_id:
                return {
                    "workspace_id": workspace_id,
                    "user_id": item.get("user_id"),
                    "workspace_name": item.get("workspace_name"),
                    "collection_name": item.get("collection_name"),
                }
        return None

    def find_workspace_by_collection(self, user_id: str, collection_name: str) -> Optional[dict[str, Any]]:
        for item in self.list_workspaces(user_id):
            if item.get("collection_name") == collection_name:
                return item
        return None

    def find_user_by_email_or_username(self, identifier: str) -> Optional[dict[str, Any]]:
        from appwrite.services.users import Users

        client = self.get_admin_client()
        users = Users(client)
        users_payload = users.list(search=identifier, model_type=dict)
        for user in _model_to_dict(users_payload).get("users", []):
            user_dict = _model_to_dict(user)
            prefs = user_dict.get("prefs") or {}
            if user_dict.get("email") == identifier or prefs.get("username") == identifier:
                return user_dict
        try:
            profile = self.find_profile_by_email_or_username(identifier)
        except Exception as exc:
            logger.warning("Profile lookup skipped: %s", exc)
            profile = None
        if not profile:
            return None
        user = users.get(user_id=profile["user_id"], model_type=dict)
        user_dict = _model_to_dict(user)
        user_dict["prefs"] = {
            **(user_dict.get("prefs") or {}),
            "username": profile.get("username") or "",
            "display_name": profile.get("display_name") or "",
        }
        return user_dict

    def upsert_user_profile(self, user_id: str, email: str, username: Optional[str], display_name: Optional[str]) -> dict[str, Any]:
        databases = self._ensure_schema()
        timestamp = _utc_now()
        existing = self.find_profile_by_email_or_username(email) or (self.find_profile_by_email_or_username(username) if username else None)
        created_at = existing.get("created_at") if existing else timestamp
        payload = {
            "user_id": user_id,
            "email": email,
            "username": username or "",
            "display_name": display_name or username or email,
            "created_at": created_at,
            "updated_at": timestamp,
        }
        document_id = self._document_id(existing) if existing else user_id
        databases.upsert_row(
            database_id=self.database_id,
            table_id=PROFILES_COLLECTION_ID,
            row_id=document_id,
            data=payload,
            model_type=dict,
        )
        return {"user_id": user_id, "email": email, "username": username, "display_name": payload["display_name"]}

    def find_profile_by_email_or_username(self, identifier: Optional[str]) -> Optional[dict[str, Any]]:
        if not identifier:
            return None
        for item in self._list_documents(PROFILES_COLLECTION_ID):
            if item.get("email") == identifier or item.get("username") == identifier:
                return {
                    "$id": self._document_id(item),
                    "user_id": item.get("user_id"),
                    "email": item.get("email"),
                    "username": item.get("username"),
                    "display_name": item.get("display_name"),
                    "created_at": item.get("created_at"),
                }
        return None

    def list_workspace_files_by_collection(self, user_id: str, collection_name: str) -> list[dict[str, Any]]:
        workspace = self.find_workspace_by_collection(user_id, collection_name)
        return self.list_file_records(workspace["workspace_id"]) if workspace else []

    def create_file_record(self, workspace_id: str, file_name: str, file_url: str, file_id: str) -> dict[str, Any]:
        timestamp = _utc_now()
        payload = {
            "workspace_id": workspace_id,
            "file_name": file_name,
            "file_url": file_url,
            "storage_file_id": file_id,
            "created_at": timestamp,
        }
        databases = self._ensure_schema()
        document_id = ID.unique() if ID is not None else f"file-{datetime.now(timezone.utc).timestamp()}"
        document = databases.create_row(
            database_id=self.database_id,
            table_id=FILES_COLLECTION_ID,
            row_id=document_id,
            data=payload,
            model_type=dict,
        )
        return {"file_id": self._document_id(_model_to_dict(document)), "storage_file_id": file_id, "file_name": file_name, "file_url": file_url}

    def list_file_records(self, workspace_id: str) -> list[dict[str, Any]]:
        records = self._list_documents(FILES_COLLECTION_ID, workspace_id)
        return [
            {
                "file_id": self._document_id(item),
                "storage_file_id": item.get("storage_file_id"),
                "file_name": item.get("file_name"),
                "file_url": item.get("file_url"),
                "created_at": item.get("created_at"),
            }
            for item in records
            if item.get("workspace_id") == workspace_id
        ]

    def upsert_chat(self, user_id: str, workspace_id: str, chat_id: str, chat_name: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        timestamp = _utc_now()
        existing = None
        try:
            existing = self._ensure_schema().get_row(
                database_id=self.database_id,
                table_id=CHATS_COLLECTION_ID,
                row_id=chat_id,
                model_type=dict,
            )
        except Exception as exc:
            if not self._is_appwrite_error(exc, 404):
                raise

        payload = {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "chat_name": chat_name,
            "messages_json": json.dumps(messages),
            "created_at": _model_to_dict(existing).get("created_at") if existing else timestamp,
            "updated_at": timestamp,
        }
        databases = self._ensure_schema()
        databases.upsert_row(
            database_id=self.database_id,
            table_id=CHATS_COLLECTION_ID,
            row_id=chat_id,
            data=payload,
            model_type=dict,
        )
        return {"chat_id": chat_id, "messages": messages, "chat_name": chat_name}

    def list_chats(self, user_id: str, workspace_id: str) -> list[dict[str, Any]]:
        records = self._list_documents(CHATS_COLLECTION_ID)
        chats = []
        for item in records:
            if item.get("user_id") != user_id or item.get("workspace_id") != workspace_id:
                continue
            try:
                messages = json.loads(item.get("messages_json") or "[]")
            except json.JSONDecodeError:
                messages = []
            chats.append(
                {
                    "chat_id": self._document_id(item),
                    "chat_name": item.get("chat_name"),
                    "messages": messages,
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                }
            )
        return sorted(chats, key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)

    def delete_chat(self, chat_id: str) -> None:
        databases = self._ensure_schema()
        try:
            databases.delete_row(
                database_id=self.database_id,
                table_id=CHATS_COLLECTION_ID,
                row_id=chat_id,
            )
        except Exception as exc:
            if not self._is_appwrite_error(exc, 404):
                raise


client_manager = AppwriteClientManager()
