from fastapi import APIRouter
from virchow.error_handling.error_codes import VirchowErrorCode
from virchow.error_handling.exceptions import VirchowError

router = APIRouter(prefix="/federated")

@router.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def disabled_federated_router(path_name: str) -> None:
    raise VirchowError(VirchowErrorCode.FORBIDDEN, "Federated features are disabled")
