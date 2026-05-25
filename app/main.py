import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.database import init_db
from app.vector_store.store import init_collection
from app.embeddings.embedder import warm_up

from app.auth.router import router as auth_router
from app.documents.router import router as documents_router
from app.chat.router import router as chat_router
from app.admin.router import router as admin_router
from app.settings_router import router as settings_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("lingualrag")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initializing database…")
    await init_db()
    log.info("Initializing Qdrant collection…")
    init_collection()
    log.info("Warming up embedding model (this may take a minute on first run)…")
    try:
        warm_up()
        log.info("Embedding model ready.")
    except Exception as e:
        log.warning("Embedding warm-up failed: %s", e)
    log.info("LingualRAG backend ready on http://%s:%d", settings.HOST, settings.PORT)
    yield
    log.info("Shutting down.")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_origin_regex=settings.BACKEND_CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_handler(_, exc):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    detail = str(exc) if settings.DEBUG else "Internal server error"
    return JSONResponse(status_code=500, content={"detail": detail, "type": type(exc).__name__})


@app.get("/")
async def root():
    return {"app": settings.APP_NAME, "status": "ok"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(documents_router, prefix="/documents", tags=["documents"])
app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(settings_router, prefix="/settings", tags=["settings"])
