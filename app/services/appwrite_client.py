import logging
from typing import Optional
from app.core.singleton import singleton
from ..core.config import Settings
from appwrite.client import Client
from appwrite.services.databases import Databases

logger = logging.getLogger("supabase_client")

@singleton
class AppwriteClientManager:
    def __init__(self):
        self.settings = Settings()
        self.endpoint = self.settings.APPWRITE_URL
        self.project_id = self.settings.APPWRITE_ID
        self.api_key = self.settings.APPWRITE_KEY

    def get_admin_client(self) -> Client:
        """Returns a master client authenticated with the API key."""
        client = Client()
        client.set_endpoint(self.endpoint).set_project(self.project_id).set_key(self.api_key)
        return client

    def get_user_client(self) -> Client:
        """Returns a client scoped specifically to an active user's session token."""
        client = Client()
        client.set_endpoint(self.endpoint).set_project(self.project_id)

        return client

client_manager = AppwriteClientManager()