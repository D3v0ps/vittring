"""Append-only audit log helper.

Used by every endpoint and job that performs a sensitive action — login,
password change, GDPR export/delete, plan change, etc. Centralizing here
keeps the action vocabulary consistent.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from vittring.models.audit import AuditLog


class AuditAction(StrEnum):
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    SIGNUP = "signup"
    EMAIL_VERIFIED = "email_verified"
    PASSWORD_CHANGE = "password_change"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"
    TWO_FACTOR_ENABLE = "2fa_enable"
    TWO_FACTOR_DISABLE = "2fa_disable"
    ACCOUNT_LOCKED = "account_locked"
    GDPR_EXPORT = "gdpr_export"
    GDPR_DELETE_REQUESTED = "gdpr_delete_requested"
    GDPR_DELETE_COMPLETED = "gdpr_delete_completed"
    PLAN_CHANGE = "plan_change"
    SUBSCRIPTION_CREATED = "subscription_created"
    SUBSCRIPTION_UPDATED = "subscription_updated"
    SUBSCRIPTION_DELETED = "subscription_deleted"
    DEPLOY = "deploy"

    # Admin / superadmin actions
    ADMIN_USER_CREATE = "admin_user_create"
    ADMIN_USER_EDIT = "admin_user_edit"
    ADMIN_USER_DELETE = "admin_user_delete"
    ADMIN_USER_PROMOTE = "admin_user_promote"
    ADMIN_USER_UNLOCK = "admin_user_unlock"
    ADMIN_USER_VERIFICATION_RESEND = "admin_user_verification_resend"
    ADMIN_USER_DELETE_REQUEST = "admin_user_delete_request"
    ADMIN_USER_DELETE_CANCEL = "admin_user_delete_cancel"
    ADMIN_PLAN_CHANGE = "admin_plan_change"
    ADMIN_SUBSCRIPTION_TOGGLE = "admin_subscription_toggle"
    ADMIN_TRIGGER_INGEST = "admin_trigger_ingest"
    ADMIN_TRIGGER_DIGEST = "admin_trigger_digest"
    ADMIN_TRIGGER_GDPR_SCRUB = "admin_trigger_gdpr_scrub"


async def audit(
    session: AsyncSession,
    *,
    action: AuditAction | str,
    user_id: int | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert an audit row. Caller's transaction owns the commit."""
    row = AuditLog(
        user_id=user_id,
        action=str(action),
        ip=ip,
        user_agent=user_agent,
        audit_metadata=metadata,
    )
    session.add(row)
