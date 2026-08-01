from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from .core.config import Settings
from .core.logging import init_logging
from .middlewares.request_id import RequestIDMiddleware
from .routes.ask_ai import router as ask_ai_router
from .routes.create_workspace import router as create_workspace_router
from .routes.rag import router as rag_router
from .routes.signin import router as signin_router
from .routes.signout import router as signout_router
from .routes.signup import router as signup_router
from .routes.upload import router as upload_router
from .routes.chats import router as chats_router

init_logging()
settings = Settings()

app = FastAPI(title=settings.PROJECT_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIDMiddleware)

app.include_router(upload_router, prefix="/api/v1/upload", tags=["upload"])
app.include_router(signup_router, prefix="/api/v1/signup", tags=["signup"])
app.include_router(signin_router, prefix="/api/v1/signin", tags=["signin"])
app.include_router(signout_router, prefix="/api/v1/signout", tags=["signout"])
app.include_router(create_workspace_router, prefix="/api/v1/workspace", tags=["workspace"])
app.include_router(rag_router, prefix="/api/v1/vectorize", tags=["vectorize"])
app.include_router(ask_ai_router, prefix="/api/v1/ask_ai", tags=["ask_ai"])
app.include_router(chats_router, prefix="/api/v1/chats", tags=["chats"])


@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def main():
    return {"status": "ok"}
