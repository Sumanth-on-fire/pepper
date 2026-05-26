import logging
from typing import Optional
from app.core.singleton import singleton
from ..core.config import Settings
from supabase import create_client, Client

logger = logging.getLogger("supabase_client")

@singleton
class SupabaseClient:
    """Placeholder Supabase client wrapper.

    Replace the internals with the real supabase-py client connection
    and storage upload calls. This implementation returns a placeholder URL.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.url = self.settings.SUPABASE_URL
        self.key = self.settings.SUPABASE_KEY

        self.supabase: Client = create_client(self.url, self.key)


def get_supabase_client() -> SupabaseClient:
    return SupabaseClient()
