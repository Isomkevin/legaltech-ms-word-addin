from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.routers import auth, chat, drafting, legal_tools, playbooks, research, shell

settings = get_settings()

app = FastAPI(title="HakiChain AI", version="0.1.0")
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

PREFIX = "/api/v1"
app.include_router(auth.router, prefix=PREFIX)
app.include_router(shell.router, prefix=PREFIX)
app.include_router(legal_tools.router, prefix=PREFIX)
app.include_router(chat.router, prefix=PREFIX)
app.include_router(playbooks.router, prefix=PREFIX)
app.include_router(drafting.router, prefix=PREFIX)
app.include_router(research.router, prefix=PREFIX)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
