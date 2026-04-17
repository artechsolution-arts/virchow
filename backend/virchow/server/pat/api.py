from fastapi import APIRouter
from virchow.error_handling.error_codes import VirchowErrorCode
from virchow.error_handling.exceptions import VirchowError

router = APIRouter(prefix="/user/pats")

@router.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def disabled_pat_router(path_name: str) -> None:
    raise VirchowError(VirchowErrorCode.FORBIDDEN, "Personal Access Tokens are disabled")
