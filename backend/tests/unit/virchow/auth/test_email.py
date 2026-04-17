import pytest

from virchow.auth.email_utils import build_user_email_invite
from virchow.auth.email_utils import send_email
from virchow.configs.constants import AuthType
from virchow.configs.constants import VIRCHOW_DEFAULT_APPLICATION_NAME
from virchow.db.engine.sql_engine import SqlEngine
from virchow.server.runtime.virchow_runtime import VirchowRuntime


@pytest.mark.skip(
    reason="This sends real emails, so only run when you really want to test this!"
)
def test_send_user_email_invite() -> None:
    SqlEngine.init_engine(pool_size=20, max_overflow=5)

    application_name = VIRCHOW_DEFAULT_APPLICATION_NAME

    virchow_file = VirchowRuntime.get_emailable_logo()

    subject = f"Invitation to Join {application_name} Organization"

    FROM_EMAIL = "noreply@virchow.app"
    TO_EMAIL = "support@virchow.app"
    text_content, html_content = build_user_email_invite(
        FROM_EMAIL, TO_EMAIL, VIRCHOW_DEFAULT_APPLICATION_NAME, AuthType.CLOUD
    )

    send_email(
        TO_EMAIL,
        subject,
        html_content,
        text_content,
        mail_from=FROM_EMAIL,
        inline_png=("logo.png", virchow_file.data),
    )
