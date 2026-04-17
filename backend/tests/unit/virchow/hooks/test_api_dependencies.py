"""Unit tests for the hooks feature gate."""

from unittest.mock import patch

import pytest

from virchow.error_handling.error_codes import VirchowErrorCode
from virchow.error_handling.exceptions import VirchowError
from virchow.hooks.api_dependencies import require_hook_enabled


class TestRequireHookEnabled:
    def test_raises_when_multi_tenant(self) -> None:
        with (
            patch("virchow.hooks.api_dependencies.MULTI_TENANT", True),
            patch("virchow.hooks.api_dependencies.HOOK_ENABLED", True),
        ):
            with pytest.raises(VirchowError) as exc_info:
                require_hook_enabled()
        assert exc_info.value.error_code is VirchowErrorCode.SINGLE_TENANT_ONLY
        assert exc_info.value.status_code == 403
        assert "multi-tenant" in exc_info.value.detail

    def test_raises_when_flag_disabled(self) -> None:
        with (
            patch("virchow.hooks.api_dependencies.MULTI_TENANT", False),
            patch("virchow.hooks.api_dependencies.HOOK_ENABLED", False),
        ):
            with pytest.raises(VirchowError) as exc_info:
                require_hook_enabled()
        assert exc_info.value.error_code is VirchowErrorCode.ENV_VAR_GATED
        assert exc_info.value.status_code == 403
        assert "HOOK_ENABLED" in exc_info.value.detail

    def test_passes_when_enabled_single_tenant(self) -> None:
        with (
            patch("virchow.hooks.api_dependencies.MULTI_TENANT", False),
            patch("virchow.hooks.api_dependencies.HOOK_ENABLED", True),
        ):
            require_hook_enabled()  # must not raise
