from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from virchow.auth.users import current_admin_user
from virchow.auth.users import current_user
from virchow.auth.users import is_user_admin
from virchow.configs.app_configs import DISABLE_VECTOR_DB
from virchow.configs.constants import KV_REINDEX_KEY
from virchow.configs.constants import NotificationType
from virchow.db.engine.sql_engine import get_session
from virchow.db.models import User
from virchow.db.notification import dismiss_all_notifications
from virchow.db.notification import get_notifications
from virchow.db.notification import update_notification_last_shown
from virchow.key_value_store.factory import get_kv_store
from virchow.key_value_store.interface import KvKeyNotFoundError
from virchow.server.features.build.utils import is_virchow_craft_enabled
from virchow.server.settings.models import Notification
from virchow.server.settings.models import Settings
from virchow.server.settings.models import UserSettings
from virchow.server.settings.store import load_settings
from virchow.server.settings.store import store_settings
from virchow.utils.logger import setup_logger
from virchow.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/settings")
basic_router = APIRouter(prefix="/settings")


@admin_router.put("")
def admin_put_settings(
    settings: Settings, _: User = Depends(current_admin_user)
) -> None:
    store_settings(settings)


def apply_license_status_to_settings(settings: Settings) -> Settings:
    """MIT version: no-op, returns settings unchanged."""
    return settings


@basic_router.get("")
def fetch_settings(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserSettings:
    """Settings and notifications are stuffed into this single endpoint to reduce number of
    Postgres calls"""
    general_settings = load_settings()
    settings_notifications = get_settings_notifications(user, db_session)

    try:
        kv_store = get_kv_store()
        needs_reindexing = cast(bool, kv_store.load(KV_REINDEX_KEY))
    except KvKeyNotFoundError:
        needs_reindexing = False

    apply_fn = fetch_versioned_implementation_with_fallback(
        "virchow.server.settings.api",
        "apply_license_status_to_settings",
        apply_license_status_to_settings,
    )
    general_settings = apply_fn(general_settings)

    # Check if Virchow Craft is enabled for this user (used for server-side redirects)
    virchow_craft_enabled_for_user = is_virchow_craft_enabled(user) if user else False

    return UserSettings(
        **general_settings.model_dump(),
        notifications=settings_notifications,
        needs_reindexing=needs_reindexing,
        virchow_craft_enabled=virchow_craft_enabled_for_user,
        vector_db_enabled=not DISABLE_VECTOR_DB,
    )


def get_settings_notifications(user: User, db_session: Session) -> list[Notification]:
    """Get notifications for settings page, including product gating and reindex notifications"""
    # Check for product gating notification
    product_notif = get_notifications(
        user=None,
        notif_type=NotificationType.TRIAL_ENDS_TWO_DAYS,
        db_session=db_session,
    )
    notifications = [Notification.from_model(product_notif[0])] if product_notif else []

    # Only show reindex notifications to admins
    if not is_user_admin(user):
        return notifications

    # Check if reindexing is needed
    kv_store = get_kv_store()
    try:
        needs_index = cast(bool, kv_store.load(KV_REINDEX_KEY))
        if not needs_index:
            dismiss_all_notifications(
                notif_type=NotificationType.REINDEX, db_session=db_session
            )
            return notifications
    except KvKeyNotFoundError:
        # If something goes wrong and the flag is gone, better to not start a reindexing
        # it's a heavyweight long running job and maybe this flag is cleaned up later
        logger.warning("Could not find reindex flag")
        return notifications

    try:
        # Need a transaction in order to prevent under-counting current notifications
        reindex_notifs = get_notifications(
            user=user, notif_type=NotificationType.REINDEX, db_session=db_session
        )

        if len(reindex_notifs) > 1:
            logger.error("User has multiple reindex notifications")
        elif not reindex_notifs:
            return notifications

        reindex_notif = reindex_notifs[0]
        update_notification_last_shown(
            notification=reindex_notif, db_session=db_session
        )

        db_session.commit()
        notifications.append(Notification.from_model(reindex_notif))
        return notifications
    except SQLAlchemyError:
        logger.exception("Error while processing notifications")
        db_session.rollback()
        return notifications
