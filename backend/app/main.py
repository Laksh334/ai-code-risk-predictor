import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, github, health, repositories, scans
from app.config import settings
from app.db.session import init_db
from app.services.analysis import fail_interrupted_scans


@asynccontextmanager
async def lifespan(_: FastAPI):
    problems = settings.production_problems()
    if settings.environment == "production" and problems:
        # Refuse to start rather than run a public server with unsafe settings.
        raise RuntimeError("Unsafe production settings: " + "; ".join(problems))
    if settings.secret_key == "dev-only-change-me":
        logging.getLogger("uvicorn.error").warning(
            "SECRET_KEY is the dev default - set a real one before deploying!"
        )
    init_db()  # dev only: create tables on startup if they don't exist
    fail_interrupted_scans()  # scans cut off by a restart would otherwise block new ones
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
log = logging.getLogger("app")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Every response gets an X-Request-ID (reused from the caller if sent), so a user's error
    report can be matched to the server log line."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Unexpected bugs: log the full traceback, but never send internals (stack traces, SQL,
    file paths) to the client."""
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]
    log.exception("Unhandled error on %s %s (request %s)", request.method, request.url.path, request_id)
    return JSONResponse(status_code=500, headers={"X-Request-ID": request_id},
                        content={"detail": "Internal server error", "request_id": request_id})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(repositories.router, prefix="/api")
app.include_router(scans.router, prefix="/api")
app.include_router(github.router, prefix="/api")


@app.get("/")
def root() -> dict:
    return {"message": f"{settings.app_name} is running. See /docs for the API."}
