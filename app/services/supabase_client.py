import logging
from typing import Optional

from app.core.singleton import singleton

from ..core.config import Settings

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - optional dependency handling
    Client = Optional  # type: ignore[assignment]
    create_client = None

logger = logging.getLogger("supabase_client")


@singleton
class SupabaseClient:
    """Placeholder Supabase client wrapper."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()
        self.url = self.settings.SUPABASE_URL
        self.key = self.settings.SUPABASE_KEY
        self.supabase: Optional[Client] = create_client(self.url, self.key) if create_client else None


def get_supabase_client() -> SupabaseClient:
    return SupabaseClient()
