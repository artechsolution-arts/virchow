from fastapi import APIRouter
from virchow.error_handling.error_codes import VirchowErrorCode
from virchow.error_handling.exceptions import VirchowError

admin_router = APIRouter(prefix="/admin/kg")

@admin_router.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def disabled_kg_router(path_name: str) -> None:
    raise VirchowError(VirchowErrorCode.FORBIDDEN, "Knowledge Graph features are disabled")
