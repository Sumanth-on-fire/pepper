from pydantic import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "pepper-fastapi"
    SUPABASE_URL: str = "https://tgvzvhyeiighicugghyn.supabase.co"
    SUPABASE_KEY: str = "sb_publishable_3HNmseMMVmN6GLiOuX59Qg_FN-6gn2i"

    class Config:
        env_file = ".env"
