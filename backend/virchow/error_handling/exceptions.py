"""VirchowError — the single exception type for all Virchow business errors.

Raise ``VirchowError`` instead of ``HTTPException`` in business code.  A global
FastAPI exception handler (registered via ``register_virchow_exception_handlers``)
converts it into a JSON response with the standard
``{"error_code": "...", "detail": "..."}`` shape.

Usage::

    from virchow.error_handling.error_codes import VirchowErrorCode
    from virchow.error_handling.exceptions import VirchowError

    raise VirchowError(VirchowErrorCode.NOT_FOUND, "Session not found")

For upstream errors with a dynamic HTTP status (e.g. billing service),
use ``status_code_override``::

    raise VirchowError(
        VirchowErrorCode.BAD_GATEWAY,
        detail,
        status_code_override=upstream_status,
    )
"""

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse

from virchow.error_handling.error_codes import VirchowErrorCode
from virchow.utils.logger import setup_logger

logger = setup_logger()


class VirchowError(Exception):
    """Structured error that maps to a specific ``VirchowErrorCode``.

    Attributes:
        error_code: The ``VirchowErrorCode`` enum member.
        detail: Human-readable detail (defaults to the error code string).
        status_code: HTTP status — either overridden or from the error code.
    """

    def __init__(
        self,
        error_code: VirchowErrorCode,
        detail: str | None = None,
        *,
        status_code_override: int | None = None,
    ) -> None:
        resolved_detail = detail or error_code.code
        super().__init__(resolved_detail)
        self.error_code = error_code
        self.detail = resolved_detail
        self._status_code_override = status_code_override

    @property
    def status_code(self) -> int:
        return self._status_code_override or self.error_code.status_code


def log_virchow_error(exc: VirchowError) -> None:
    detail = exc.detail
    status_code = exc.status_code
    if status_code >= 500:
        logger.error(f"VirchowError {exc.error_code.code}: {detail}")
    elif status_code >= 400:
        logger.warning(f"VirchowError {exc.error_code.code}: {detail}")


def virchow_error_to_json_response(exc: VirchowError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.error_code.detail(exc.detail),
    )


def register_virchow_exception_handlers(app: FastAPI) -> None:
    """Register a global handler that converts ``VirchowError`` to JSON responses.

    Must be called *after* the app is created but *before* it starts serving.
    The handler logs at WARNING for 4xx and ERROR for 5xx.
    """

    @app.exception_handler(VirchowError)
    async def _handle_virchow_error(
        request: Request,  # noqa: ARG001
        exc: VirchowError,
    ) -> JSONResponse:
        log_virchow_error(exc)
        return virchow_error_to_json_response(exc)
