from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router
from app.db.session import create_tables, get_db
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_settings(settings)
    await create_tables()
    logger.info("agro-ai backend started | debug=%s | db=%s",
                settings.debug, settings.database_url.split("///")[-1])
    yield


def _validate_settings(s) -> None:
    """Fail fast on critical misconfigurations."""
    if not s.secret_key or s.secret_key == "dev-secret-key":
        if not s.debug:
            raise RuntimeError("SECRET_KEY must be set in production (DEBUG=false)")
    if s.database_url.startswith("sqlite") and not s.debug:
        logger.warning("SQLite in non-debug mode — use PostgreSQL for production")


app = FastAPI(
    title="AI-Агроном API",
    description="Диагностика болезней растений по фото с AI-агрономом",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,   # Swagger только в dev
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# CORS: explicit origins always — ["*"] + credentials is invalid per spec
_allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["Infra"])
async def health():
    """Базовая проверка — сервис запущен."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/health/db", tags=["Infra"])
async def health_db():
    """Проверка подключения к БД (для docker healthcheck)."""
    from sqlalchemy import text
    try:
        async for db in get_db():
            await db.execute(text("SELECT 1"))
            return {"status": "ok", "db": "connected"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"DB unavailable: {e}")
