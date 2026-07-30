from __future__ import annotations

from functools import wraps
from inspect import signature
from typing import Any, Callable, Optional

from fastapi import HTTPException

from app.core.singleton import singleton


@singleton
class WorkspaceRegistry:
    def __init__(self) -> None:
        self._workspaces: dict[str, str] = {}

    @staticmethod
    def _normalize_name(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A workspace name is required.")
        return value.strip()

    def create_workspace(self, workspace_name: str) -> dict[str, str]:
        collection_name = self._normalize_name(workspace_name)
        if collection_name in self._workspaces:
            return {"workspace_name": collection_name, "collection_name": collection_name}

        self._workspaces[collection_name] = collection_name
        return {"workspace_name": collection_name, "collection_name": collection_name}

    def resolve_collection_name(self, collection_name: Optional[str]) -> str:
        if not collection_name:
            raise ValueError("A workspace is required before this action can run.")

        candidate = self._normalize_name(collection_name)
        if candidate in self._workspaces:
            return self._workspaces[candidate]

        raise ValueError("The requested workspace does not exist. Create a workspace before uploading or asking questions.")

    def ensure_workspace(self, collection_name: Optional[str]) -> str:
        return self.resolve_collection_name(collection_name)


workspace_registry = WorkspaceRegistry()


def require_workspace(func: Callable[..., Any]) -> Callable[..., Any]:
    sig = signature(func)

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        collection_name = _extract_collection_name(sig, args, kwargs)
        try:
            workspace_registry.ensure_workspace(collection_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return await func(*args, **kwargs)

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        collection_name = _extract_collection_name(sig, args, kwargs)
        try:
            workspace_registry.ensure_workspace(collection_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return func(*args, **kwargs)

    return async_wrapper if hasattr(func, "__code__") and func.__code__.co_flags & 0x80 else sync_wrapper


def _extract_collection_name(sig: signature, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Optional[str]:
    bound = sig.bind_partial(*args, **kwargs)
    for name in ("collection_name", "workspace_name"):
        if name in bound.arguments and bound.arguments[name] is not None:
            return str(bound.arguments[name])

    for arg in args:
        if hasattr(arg, "collection_name") and getattr(arg, "collection_name"):
            return str(getattr(arg, "collection_name"))
        if hasattr(arg, "workspace_name") and getattr(arg, "workspace_name"):
            return str(getattr(arg, "workspace_name"))

    return None
