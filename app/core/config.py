from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = os.environ.get('PROJECT_NAME')
    SUPABASE_URL: str = os.environ.get('SUPABASE_URL')
    SUPABASE_KEY: str = os.environ.get('SUPABASE_KEY')
    APPWRITE_URL: str = os.environ.get('APPWRITE_URL')
    APPWRITE_KEY: str = os.environ.get('APPWRITE_KEY')
    APPWRITE_ID: str = os.environ.get('APPWRITE_ID')
    APPWRITE_STR: str = os.environ.get('APPWRITE_STR')
    APPWRITE_DB_ID: str = os.environ.get('APPWRITE_DB_ID')
    GEMINI_API_KEY: str = os.environ.get('GEMINI_API_KEY')
    GEMINI_MODEL_NAME: str = os.environ.get('GEMINI_MODEL_NAME')
    GORQ_API_KEY: str = os.environ.get('GORQ_API_KEY')
