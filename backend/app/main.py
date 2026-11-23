import logging
import uuid
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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


FRONTEND = Path(settings.frontend_dist) if settings.frontend_dist else None

if FRONTEND and (FRONTEND / "index.html").is_file():
    # Production: the built React app (frontend/dist) is served by this same server, so the whole
    # product is ONE service on ONE URL (no CORS, one deploy). /api/* and /docs stay the API.
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "docs", "redoc", "openapi.json")):
            raise HTTPException(404)  # unknown API route: a JSON 404, not the web page
        file = (FRONTEND / path).resolve()
        if path and file.is_file() and FRONTEND.resolve() in file.parents:
            return FileResponse(file)  # favicon, robots.txt, ...
        # Any other path (/repos/1, /login, ...) is a page of the React app: let its router decide.
        return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
else:
    @app.get("/")
    def root() -> dict:
        return {"message": f"{settings.app_name} is running. See /docs for the API."}
