from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

def normalize_db_url(url: str) -> str:
    """Hosting providers (Render, Heroku...) hand out postgres:// URLs; SQLAlchemy needs to be
    told which driver to use (psycopg 3)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = normalize_db_url(settings.database_url)
# SQLite needs this flag because FastAPI may use the connection from another thread.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Parent class of every database model."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one DB session per request, always closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Local development: create missing tables directly. Production (AUTO_CREATE_TABLES=false)
    uses Alembic migrations instead: `alembic upgrade head`, run by the Docker entrypoint."""
    if not settings.auto_create_tables:
        return
    import app.models  # noqa: F401  registers the models on Base

    Base.metadata.create_all(bind=engine)
