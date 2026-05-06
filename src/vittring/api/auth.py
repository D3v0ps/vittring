"""Auth endpoints: signup, login, logout, verify, password reset, 2FA."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import EmailStr
from sqlalchemy import select

from vittring.api.deps import (
    ACCESS_TOKEN_COOKIE,
    CurrentUser,
    OptionalUser,
    request_meta,
)
from vittring.api.templates import templates
from vittring.audit.log import AuditAction, audit
from vittring.db import SessionDep
from vittring.delivery.email import render, send_email
from vittring.models.user import (
    EmailVerificationToken,
    PasswordResetToken,
    User,
)
from vittring.security.passwords import (
    assert_strong_password,
    hash_password,
    verify_password,
)
from vittring.security.ratelimit import (
    DEFAULT_BY_IP,
    LOGIN_BY_EMAIL,
    LOGIN_BY_IP,
    PASSWORD_RESET_BY_EMAIL,
    SIGNUP_BY_IP,
    client_ip,
    rate_limit,
)
from vittring.security.tokens import (
    create_access_token,
    hash_url_token,
    new_url_token,
)
from vittring.security.totp import generate_secret, provisioning_uri, verify_code
from vittring.utils.errors import WeakPasswordError
from vittring.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

ACCOUNT_LOCK_THRESHOLD = 5
ACCOUNT_LOCK_DURATION = timedelta(minutes=15)
EMAIL_VERIFICATION_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(hours=1)
TRIAL_DAYS = 14


def _set_session_cookie(response: HTMLResponse | RedirectResponse, user_id: int) -> None:
    token = create_access_token(sub=str(user_id))
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=15 * 60,
    )


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------

@router.get("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_page(request: Request, user: OptionalUser) -> HTMLResponse:
    if user:
        return RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request, "auth/signup.html.j2", {"title": "Skapa konto", "error": None}
    )


@router.post(
    "/signup",
    dependencies=[Depends(rate_limit(SIGNUP_BY_IP, client_ip))],
    include_in_schema=False,
    response_model=None,
)
async def signup(
    request: Request,
    session: SessionDep,
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form()],
    full_name: Annotated[str, Form()] = "",
    company_name: Annotated[str, Form()] = "",
) -> RedirectResponse | HTMLResponse:
    try:
        assert_strong_password(password)
    except WeakPasswordError as exc:
        return templates.TemplateResponse(
            request,
            "auth/signup.html.j2",
            {"title": "Skapa konto", "error": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "auth/signup.html.j2",
            {"title": "Skapa konto", "error": "En användare med den e-postadressen finns redan."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = User(
        email=str(email),
        password_hash=hash_password(password),
        full_name=full_name or None,
        company_name=company_name or None,
        plan="trial",
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS),
    )
    session.add(user)
    await session.flush()

    plain, hashed = new_url_token()
    session.add(
        EmailVerificationToken(
            token_hash=hashed,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + EMAIL_VERIFICATION_TTL,
        )
    )

    meta = request_meta(request)
    await audit(
        session, action=AuditAction.SIGNUP, user_id=user.id, ip=meta["ip"], user_agent=meta["user_agent"]
    )

    settings = get_settings()
    base = str(settings.app_base_url).rstrip("/")
    verify_url = f"{base}/auth/verify?t={plain}"
    html = render("verify.html.j2", subject="Bekräfta din e-postadress", from_address=settings.email_from_address, email=user.email, verify_url=verify_url)
    text = f"Bekräfta din e-post genom att besöka: {verify_url}"
    try:
        await send_email(
            to=user.email,
            subject="Bekräfta din e-postadress hos Vittring",
            html=html,
            text=text,
            tags={"kind": "verify"},
        )
    except Exception as exc:
        # Domain not yet verified at Resend, transient API error, etc. We
        # still keep the account so the operator can finish setup later
        # (and so the user isn't stuck with a half-created row).
        import structlog

        structlog.get_logger(__name__).warning(
            "signup_verify_email_failed",
            user_id=user.id,
            email=user.email,
            error=str(exc),
        )

    response = RedirectResponse("/auth/check-email", status_code=status.HTTP_303_SEE_OTHER)
    return response


@router.get("/check-email", response_class=HTMLResponse, include_in_schema=False)
async def check_email(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth/check_email.html.j2",
        {"title": "Bekräfta din e-post"},
    )


# ---------------------------------------------------------------------------
# Verification-needed landing + resend
# ---------------------------------------------------------------------------

@router.get("/verification-needed", response_class=HTMLResponse, include_in_schema=False)
async def verification_needed(
    request: Request, email: str | None = None
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth/verification_needed.html.j2",
        {
            "title": "Bekräfta din e-post",
            "email": email,
            "submitted": False,
            "error": None,
        },
    )


@router.post(
    "/resend-verification",
    dependencies=[Depends(rate_limit(PASSWORD_RESET_BY_EMAIL, lambda r: "resend"))],
    include_in_schema=False,
    response_model=None,
)
async def resend_verification(
    request: Request,
    session: SessionDep,
    email: Annotated[EmailStr, Form()],
) -> HTMLResponse:
    """Generate a fresh verification token and re-send the bekräfta-mejl.

    Anti-enumeration: the rendered response is identical whether the email
    matches a real account or not; only on a hit do we actually mint a
    token + queue an email. The reused PASSWORD_RESET_BY_EMAIL bucket caps
    abuse (3 req/hour per email).
    """
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is not None and not user.is_verified:
        plain, hashed = new_url_token()
        session.add(
            EmailVerificationToken(
                token_hash=hashed,
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + EMAIL_VERIFICATION_TTL,
            )
        )
        meta = request_meta(request)
        await audit(
            session,
            action=AuditAction.VERIFICATION_RESENT,
            user_id=user.id,
            ip=meta["ip"],
            user_agent=meta["user_agent"],
        )
        settings = get_settings()
        base = str(settings.app_base_url).rstrip("/")
        verify_url = f"{base}/auth/verify?t={plain}"
        html = render(
            "verify.html.j2",
            subject="Bekräfta din e-postadress",
            from_address=settings.email_from_address,
            email=user.email,
            verify_url=verify_url,
        )
        text = f"Bekräfta din e-post genom att besöka: {verify_url}"
        try:
            await send_email(
                to=user.email,
                subject="Bekräfta din e-postadress hos Vittring",
                html=html,
                text=text,
                tags={"kind": "verify_resent"},
            )
        except Exception as exc:
            import structlog

            structlog.get_logger(__name__).warning(
                "resend_verification_email_failed",
                user_id=user.id,
                email=user.email,
                error=str(exc),
            )
    return templates.TemplateResponse(
        request,
        "auth/verification_needed.html.j2",
        {
            "title": "Bekräfta din e-post",
            "email": str(email),
            "submitted": True,
            "error": None,
        },
    )


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

@router.get("/verify", include_in_schema=False, response_model=None)
async def verify_email(t: str, session: SessionDep, request: Request) -> HTMLResponse:
    token_row = (
        await session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == hash_url_token(t)
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if (
        token_row is None
        or token_row.used_at is not None
        or token_row.expires_at < now
    ):
        return templates.TemplateResponse(
            request,
            "auth/verify_failed.html.j2",
            {"title": "Verifiering misslyckades"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = (
        await session.execute(select(User).where(User.id == token_row.user_id))
    ).scalar_one()
    user.is_verified = True
    token_row.used_at = now
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.EMAIL_VERIFIED,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    return templates.TemplateResponse(
        request,
        "auth/verify_ok.html.j2",
        {"title": "E-post bekräftad"},
    )


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, user: OptionalUser) -> HTMLResponse:
    if user:
        return RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request, "auth/login.html.j2", {"title": "Logga in", "error": None}
    )


@router.post(
    "/login",
    dependencies=[Depends(rate_limit(LOGIN_BY_IP, client_ip))],
    include_in_schema=False,
    response_model=None,
)
async def login(
    request: Request,
    session: SessionDep,
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form()],
    totp: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    LOGIN_BY_EMAIL.take(str(email))
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    meta = request_meta(request)
    now = datetime.now(timezone.utc)

    if user is None or not verify_password(password, user.password_hash):
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= ACCOUNT_LOCK_THRESHOLD:
                user.locked_until = now + ACCOUNT_LOCK_DURATION
                await audit(
                    session,
                    action=AuditAction.ACCOUNT_LOCKED,
                    user_id=user.id,
                    ip=meta["ip"],
                    user_agent=meta["user_agent"],
                )
        await audit(
            session,
            action=AuditAction.LOGIN_FAILED,
            user_id=user.id if user else None,
            ip=meta["ip"],
            user_agent=meta["user_agent"],
            metadata={"email": str(email)},
        )
        return templates.TemplateResponse(
            request,
            "auth/login.html.j2",
            {"title": "Logga in", "error": "Fel e-post eller lösenord."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if user.locked_until and user.locked_until > now:
        return templates.TemplateResponse(
            request,
            "auth/login.html.j2",
            {
                "title": "Logga in",
                "error": "Kontot är tillfälligt låst på grund av för många misslyckade försök.",
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if user.totp_secret and not (totp and verify_code(user.totp_secret, totp)):
        return templates.TemplateResponse(
            request,
            "auth/login.html.j2",
            {
                "title": "Logga in",
                "error": "Ange giltig 2FA-kod." if totp else None,
                "require_2fa": True,
                "email_value": email,
            },
            status_code=status.HTTP_401_UNAUTHORIZED if totp else status.HTTP_200_OK,
        )

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = meta["ip"]
    await audit(
        session,
        action=AuditAction.LOGIN,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )

    response = RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, user.id)
    return response


@router.post("/logout", include_in_schema=False)
async def logout(
    request: Request, session: SessionDep, user: CurrentUser
) -> RedirectResponse:
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.LOGOUT,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(ACCESS_TOKEN_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

@router.get("/password-reset", response_class=HTMLResponse, include_in_schema=False)
async def password_reset_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth/password_reset_request.html.j2",
        {"title": "Återställ lösenord", "submitted": False},
    )


@router.post(
    "/password-reset",
    dependencies=[Depends(rate_limit(DEFAULT_BY_IP, client_ip))],
    include_in_schema=False,
    response_model=None,
)
async def password_reset_request(
    request: Request,
    session: SessionDep,
    email: Annotated[EmailStr, Form()],
) -> HTMLResponse:
    # Spec §13: 3 password-reset requests/hour per email. The dependency
    # above can only see request headers, so the per-email bucket is taken
    # here once the form body has been parsed. This stops an attacker from
    # cycling through victim addresses to trigger reset emails — the
    # per-email bucket rejects the 4th attempt regardless of source IP.
    from vittring.utils.errors import RateLimitExceededError

    try:
        PASSWORD_RESET_BY_EMAIL.take(str(email))
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is not None:
        plain, hashed = new_url_token()
        session.add(
            PasswordResetToken(
                token_hash=hashed,
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + PASSWORD_RESET_TTL,
            )
        )
        meta = request_meta(request)
        await audit(
            session,
            action=AuditAction.PASSWORD_RESET_REQUESTED,
            user_id=user.id,
            ip=meta["ip"],
            user_agent=meta["user_agent"],
        )
        settings = get_settings()
        base = str(settings.app_base_url).rstrip("/")
        reset_url = f"{base}/auth/password-reset/confirm?t={plain}"
        html = render(
            "reset_password.html.j2",
            subject="Återställ ditt lösenord",
            from_address=settings.email_from_address,
            email=user.email,
            reset_url=reset_url,
        )
        text = f"Återställ ditt lösenord: {reset_url}"
        await send_email(
            to=user.email,
            subject="Återställ ditt lösenord hos Vittring",
            html=html,
            text=text,
            tags={"kind": "password_reset"},
        )

    return templates.TemplateResponse(
        request,
        "auth/password_reset_request.html.j2",
        {"title": "Återställ lösenord", "submitted": True},
    )


@router.get("/password-reset/confirm", response_class=HTMLResponse, include_in_schema=False)
async def password_reset_confirm_page(t: str, request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth/password_reset_confirm.html.j2",
        {"title": "Välj nytt lösenord", "token": t, "error": None},
    )


@router.post("/password-reset/confirm", include_in_schema=False, response_model=None)
async def password_reset_confirm(
    request: Request,
    session: SessionDep,
    t: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> HTMLResponse | RedirectResponse:
    token_row = (
        await session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == hash_url_token(t)
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if token_row is None or token_row.used_at is not None or token_row.expires_at < now:
        return templates.TemplateResponse(
            request,
            "auth/password_reset_confirm.html.j2",
            {"title": "Välj nytt lösenord", "token": t, "error": "Ogiltig eller utgången länk."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        assert_strong_password(password)
    except WeakPasswordError as exc:
        return templates.TemplateResponse(
            request,
            "auth/password_reset_confirm.html.j2",
            {"title": "Välj nytt lösenord", "token": t, "error": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = (
        await session.execute(select(User).where(User.id == token_row.user_id))
    ).scalar_one()
    user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    token_row.used_at = now
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.PASSWORD_RESET_COMPLETED,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    return RedirectResponse("/auth/login", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# 2FA enrollment
# ---------------------------------------------------------------------------

@router.get("/2fa/enable", response_class=HTMLResponse, include_in_schema=False)
async def two_factor_setup_page(request: Request, user: CurrentUser) -> HTMLResponse:
    """Show the QR / secret for setting up 2FA.

    The pending secret is persisted on ``user.totp_secret`` *immediately* but
    the ``totp_enabled_at`` flag remains null until the user confirms with a
    valid 6-digit code. That way the POST handler does not have to trust a
    client-supplied ``secret`` field — it reads the freshly stored value
    server-side. Until ``totp_enabled_at`` is set, login still allows access
    without TOTP, so a half-finished setup does not lock the user out.
    """
    if not user.totp_secret or user.totp_enabled_at is not None:
        # Either no setup in progress, or 2FA already activated and the
        # operator wants to re-pair (rotate). Issue a fresh secret either way.
        user.totp_secret = generate_secret()
        user.totp_enabled_at = None
    secret = user.totp_secret
    uri = provisioning_uri(secret, account_name=user.email)
    return templates.TemplateResponse(
        request,
        "auth/2fa_enable.html.j2",
        {"title": "Aktivera 2FA", "secret": secret, "uri": uri, "error": None},
    )


@router.post("/2fa/enable", include_in_schema=False, response_model=None)
async def two_factor_enable(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    code: Annotated[str, Form()],
) -> HTMLResponse | RedirectResponse:
    """Confirm a pending 2FA setup by checking the user's authenticator code.

    The secret is read from ``user.totp_secret`` (set by the GET handler) —
    we never trust a hidden form field, so a malicious client cannot pin the
    server's OTP secret to one they control.
    """
    secret = user.totp_secret
    if not secret:
        return RedirectResponse(
            "/auth/2fa/enable", status_code=status.HTTP_303_SEE_OTHER
        )
    if not verify_code(secret, code):
        uri = provisioning_uri(secret, account_name=user.email)
        return templates.TemplateResponse(
            request,
            "auth/2fa_enable.html.j2",
            {"title": "Aktivera 2FA", "secret": secret, "uri": uri, "error": "Fel kod."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user.totp_enabled_at = datetime.now(timezone.utc)
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.TWO_FACTOR_ENABLE,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    return RedirectResponse("/app/account", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/2fa/disable", include_in_schema=False)
async def two_factor_disable(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> RedirectResponse:
    if user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2fa_required_for_superusers",
        )
    user.totp_secret = None
    user.totp_enabled_at = None
    meta = request_meta(request)
    await audit(
        session,
        action=AuditAction.TWO_FACTOR_DISABLE,
        user_id=user.id,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    return RedirectResponse("/app/account", status_code=status.HTTP_303_SEE_OTHER)
