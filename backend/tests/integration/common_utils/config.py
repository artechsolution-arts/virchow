import generated.virchow_openapi_client.virchow_openapi_client as virchow_api  # type: ignore[import-untyped,unused-ignore]
from tests.integration.common_utils.constants import API_SERVER_URL

api_config = virchow_api.Configuration(host=API_SERVER_URL)
