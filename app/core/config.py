from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "pepper-fastapi"
    SUPABASE_URL: str = "https://tgvzvhyeiighicugghyn.supabase.co"
    SUPABASE_KEY: str = "sb_publishable_3HNmseMMVmN6GLiOuX59Qg_FN-6gn2i"
    APPWRITE_URL: str = "https://sgp.cloud.appwrite.io/v1"
    APPWRITE_KEY: str = "standard_f6b51e0f1e58895b8e384ead019dc2fbc5c77fa95ec4d7974f1dd6f669d7a01f1bf765baafaa0b8ea44eb0ce1974cfd21c1423d8dcbbdda0ef180f4b2f1a05fb1f6acf439467a175fd75578b8863e2e612edc1ecd165bd40a53ca0f27e9322f5e6cc9e86bceed2bebd16e601f87e35d76dfb220d37ab5e88946faeee60040612"
    APPWRITE_ID: str  = "6a15b6810010ba5db4dc"
    class Config:
        env_file = ".env"
