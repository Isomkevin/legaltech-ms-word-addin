import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.db.store import get_store, require_supabase_or_raise
from app.routers import auth, chat, drafting, legal_tools, playbooks, prompts, research, shell

logger = logging.getLogger("hakichain")
logging.basicConfig(level=logging.INFO, format="%(message)s")

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    require_supabase_or_raise()
    yield


app = FastAPI(title="HakiChain AI", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Organization-ID",
        "X-Timezone",
    ],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def request_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    org = request.headers.get("x-organization-id") or "-"
    logger.info(
        "method=%s path=%s status=%s duration_ms=%.1f org=%s",
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
        org,
    )
    return response


PREFIX = "/api/v1"
app.include_router(auth.router, prefix=PREFIX)
app.include_router(shell.router, prefix=PREFIX)
app.include_router(legal_tools.router, prefix=PREFIX)
app.include_router(chat.router, prefix=PREFIX)
app.include_router(playbooks.router, prefix=PREFIX)
app.include_router(drafting.router, prefix=PREFIX)
app.include_router(prompts.router, prefix=PREFIX)
app.include_router(research.router, prefix=PREFIX)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", response_model=None)
async def ready() -> JSONResponse:
    cfg = get_settings()
    if cfg.require_supabase:
        if not cfg.has_supabase:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        try:
            await get_store().ping()
        except Exception:
            return JSONResponse({"status": "not_ready"}, status_code=503)
    return JSONResponse({"status": "ok"})
