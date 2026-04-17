from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from virchow.auth.users import current_user
from virchow.db.engine.sql_engine import get_session
from virchow.db.models import User
from virchow.db.notification import dismiss_notification
from virchow.db.notification import get_notification_by_id
from virchow.db.notification import get_notifications
from virchow.server.features.build.utils import ensure_build_mode_intro_notification
from virchow.server.features.release_notes.utils import (
    ensure_release_notes_fresh_and_notify,
)
from virchow.server.settings.models import Notification as NotificationModel
from virchow.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(prefix="/notifications")


@router.get("")
def get_notifications_api(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[NotificationModel]:
    """
    Get all undismissed notifications for the current user.

    Note: also executes background checks that should create notifications.

    Examples of checks that create new notifications:
    - Checking for new release notes the user hasn't seen
    - Checking for misconfigurations due to version changes
    - Explicitly announcing breaking changes
    """
    # Background checks that create notifications
    try:
        ensure_build_mode_intro_notification(user, db_session)
    except Exception:
        logger.exception(
            "Failed to check for build mode intro in notifications endpoint"
        )

    try:
        ensure_release_notes_fresh_and_notify(db_session)
    except Exception:
        logger.exception("Failed to check for release notes in notifications endpoint")

    notifications = [
        NotificationModel.from_model(notif)
        for notif in get_notifications(user, db_session, include_dismissed=True)
    ]
    return notifications


@router.post("/{notification_id}/dismiss")
def dismiss_notification_endpoint(
    notification_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        notification = get_notification_by_id(notification_id, user, db_session)
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="Not authorized to dismiss this notification"
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Notification not found")

    dismiss_notification(notification, db_session)
