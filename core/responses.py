"""Format de réponse API uniforme."""

from typing import Any, Optional

from fastapi.responses import JSONResponse


def success_response(
    data: Any = None,
    message: str = "OK",
    code: int = 200,
) -> dict:
    return {"success": True, "data": data, "message": message, "code": code}


def error_response(
    message: str,
    code: int = 400,
    data: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={
            "success": False,
            "data": data,
            "message": message,
            "code": code,
        },
    )
