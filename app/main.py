from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from .core.logging import init_logging
from .core.config import Settings
from .middlewares.request_id import RequestIDMiddleware
from .routes.upload import router as upload_router
from .routes.create_workspace import router as create_workspace_router
from .routes.signin import router as signin_router
from .routes.signout import router as signout_router
from .routes.signup import router as signup_router
from .routes.upload import router as upload_router

init_logging()
settings = Settings()

app = FastAPI(title=settings.PROJECT_NAME)

 # Basic CORS — adjust in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request ID middleware
app.add_middleware(RequestIDMiddleware)

app.include_router(upload_router, prefix="/api/v1/upload", tags=["upload"])
app.include_router(signup_router, prefix="/api/v1/signup", tags=["signup"])
app.include_router(signin_router, prefix="/api/v1/signin", tags=["signin"])
app.include_router(signout_router, prefix="/api/v1/signout", tags=["signout"])
app.include_router(create_workspace_router, prefix="/api/v1/create_workspace", tags=["workspace"])

@app.get("/health")
async def health():
    return {"status": "ok"}
