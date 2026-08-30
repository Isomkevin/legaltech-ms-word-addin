from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        message: str,
        error_code: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.error_code = error_code
        self.extra = extra or {}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        detail: dict[str, Any] = {"message": exc.message}
        if exc.error_code:
            detail["error_code"] = exc.error_code
        detail.update(exc.extra)
        return JSONResponse(status_code=exc.status, content={"detail": detail})
