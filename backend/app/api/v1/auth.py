"""Authentication endpoints.

Supports:
- Patient/Doctor/Admin login & register
- Guest mode token issuance
- Role switch with audit logging
- Platform-aware token issuance (X-Platform header)
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, CurrentUserContext, get_current_user
from app.core.config import get_settings
from app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_guest_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.models.user import GuestSession, RoleSwitchLog, User, UserAttachment, UserRole, UserStatus
from app.schemas.auth import (
    GuestSessionResponse,
    LoginResponse,
    PasswordChangeRequest,
    RoleSwitchRequest,
    RoleSwitchResponse,
    Token,
    UserRegister,
    UserResponse,
)

from app.services.config import DynamicConfigService

router = APIRouter()
settings = get_settings()


def _read_platform(request: Request, x_platform: str | None) -> str:
    """Read platform from header or User-Agent fallback."""
    if x_platform:
        return x_platform.strip().lower()
    # Fallback heuristic based on User-Agent
    ua = (request.headers.get("User-Agent") or "").lower()
    if "miniprogram" in ua or "wechat" in ua:
        return "miniapp"
    if "android" in ua:
        return "android"
    if "iphone" in ua or "ipad" in ua or "ios" in ua:
        return "ios"
    return "web"


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    data: UserRegister,
    request: Request,
    x_platform: Annotated[str | None, Header(alias="X-Platform")] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Register a new user.

    - patient → email verification required (email_verified=False, sends verification link)
    - doctor  → status=PENDING, admin approval required (is_verified=False)
    """
    platform = _read_platform(request, x_platform)

    result = await db.execute(
        select(User).where(User.email == data.email, User.role == data.role)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email {data.email} and role {data.role.value} already exists",
        )

    is_doctor = data.role == UserRole.DOCTOR

    user = User(
        email=data.email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name,
        phone=data.phone,
        role=data.role,
        status=UserStatus.ACTIVE,
        is_verified=False,
        email_verified=is_doctor,
        license_number=data.license_number,
        hospital=data.hospital,
        department=data.department,
        title=data.title,
        age_years=data.age_years,
        age_months=data.age_months,
        gender=data.gender,
        province=data.province,
        city=data.city,
        district=data.district,
        street=data.street,
        education=data.education,
        years_of_practice=data.years_of_practice,
        specialties=data.specialties,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    if is_doctor:
        return {"message": "注册成功，请等待管理员审核。审核通过后即可登录。"}

    # Patient: generate verification token and send email
    import secrets
    token = secrets.token_urlsafe(48)
    user.verification_token = token
    user.verification_token_expires = datetime.now(timezone.utc) + timedelta(hours=24)
    await db.commit()

    base_url = str(request.base_url).rstrip("/")
    verify_url = f"{base_url}/api/v1/auth/verify-email?token={token}"

    from app.services.email_service import email_service
    import logging
    _log = logging.getLogger(__name__)

    email_sent = False
    try:
        await email_service.send_email(
            db=db,
            to_email=user.email,
            subject="【MediCareAI-Agent】请验证您的邮箱",
            html_content=f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;line-height:1.6;color:#333;">
<div style="max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#667eea;">欢迎注册 MediCareAI-Agent</h2>
<p>尊敬的 {user.full_name}：</p>
<p>感谢您注册 MediCareAI-Agent 智能医疗助手。请点击下方按钮验证您的邮箱地址：</p>
<p style="text-align:center;margin:30px 0;">
  <a href="{verify_url}" style="background:#667eea;color:white;padding:12px 32px;border-radius:6px;text-decoration:none;font-size:16px;">验证邮箱</a>
</p>
<p>或复制以下链接到浏览器打开：</p>
<p style="word-break:break-all;color:#667eea;">{verify_url}</p>
<p style="color:#999;">此链接 24 小时内有效。如非本人操作，请忽略此邮件。</p>
<hr style="border:1px solid #eee;margin:20px 0;">
<p style="font-size:12px;color:#666;">MediCareAI-Agent 智能医疗助手</p>
</div></body></html>""",
            text_content=f"欢迎注册 MediCareAI-Agent\n\n请点击以下链接验证邮箱：\n{verify_url}\n\n此链接 24 小时内有效。",
        )
        email_sent = True
    except Exception as e:
        _log.error(f"Failed to send verification email to {user.email}: {e}")

    if email_sent:
        return {"message": "注册成功！验证邮件已发送到您的邮箱，请点击邮件中的链接完成验证。"}
    else:
        return {"message": "注册成功，但验证邮件发送失败。请稍后在登录页面点击「重新发送验证邮件」，或联系管理员。"}


@router.post("/register/doctor", status_code=status.HTTP_201_CREATED)
async def register_doctor(
    email: str = Form(...),
    password: str = Form(..., min_length=8, max_length=128),
    full_name: str = Form(...),
    hospital: str = Form(...),
    department: str = Form(...),
    license_number: str = Form(...),
    title: str = Form(...),
    province: str = Form(...),
    city: str = Form(...),
    district: str = Form(...),
    upload_files: list[UploadFile] = File(...),
    phone: str | None = Form(None),
    age_years: int | None = Form(None),
    age_months: int | None = Form(None),
    gender: str | None = Form(None),
    street: str | None = Form(None),
    education: str | None = Form(None),
    years_of_practice: int | None = Form(None),
    specialties: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Register a doctor with credential file uploads (local storage)."""
    existing = await db.scalar(
        select(User).where(User.email == email, User.role == UserRole.DOCTOR)
    )
    if existing:
        raise HTTPException(status_code=409, detail="该邮箱已注册医生账号")

    MAX_FILE = 5 * 1024 * 1024
    MAX_TOTAL = 20 * 1024 * 1024
    ALLOWED = {"image/jpeg", "image/png", "application/pdf"}
    total = 0
    for f in upload_files:
        content = await f.read()
        total += len(content)
        if len(content) > MAX_FILE:
            raise HTTPException(status_code=413, detail=f"文件 {f.filename} 超过 5MB")
        if f.content_type and f.content_type not in ALLOWED:
            raise HTTPException(status_code=400, detail=f"不支持格式: {f.content_type}")
        await f.seek(0)
    if total > MAX_TOTAL:
        raise HTTPException(status_code=413, detail="总量超过 20MB")

    user = User(
        email=email, hashed_password=get_password_hash(password),
        full_name=full_name, role=UserRole.DOCTOR,
        status=UserStatus.ACTIVE, is_verified=False, email_verified=True,
        hospital=hospital, department=department,
        license_number=license_number, title=title,
        province=province, city=city, district=district,
        phone=phone, street=street, education=education,
        age_years=age_years, age_months=age_months, gender=gender,
        years_of_practice=years_of_practice, specialties=specialties,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    import os
    upload_dir = f"backend/uploads/credentials/{user.id}"
    os.makedirs(upload_dir, exist_ok=True)

    for f in upload_files:
        await f.seek(0)
        content = await f.read()
        safe_name = os.path.basename(f.filename or "credential")
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as fh:
            fh.write(content)
        att = UserAttachment(
            user_id=user.id, file_name=safe_name,
            file_url=f"/uploads/credentials/{user.id}/{safe_name}",
            file_size=len(content), mime_type=f.content_type,
            category="doctor_license", label=f.filename,
        )
        db.add(att)
    await db.commit()

    return {"message": "注册申请已提交，请等待管理员审核。审核通过后请查收确认邮件。"}


@router.get("/doctor-confirm")
async def doctor_confirm(
    token: Annotated[str, Query(min_length=1)],
    db: AsyncSession = Depends(get_db),
):
    """Doctor clicks email confirmation link after admin approval."""
    result = await db.execute(
        select(User).where(User.doctor_confirmation_token == token)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="无效的确认链接")
    if user.doctor_confirmation_token_expires and user.doctor_confirmation_token_expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="确认链接已过期，请联系管理员重新发送")

    user.email_verified = True
    user.doctor_confirmation_token = None
    user.doctor_confirmation_token_expires = None
    await db.commit()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login?doctor_confirmed=true", status_code=302)


@router.get("/verify-email")
async def verify_email(
    token: Annotated[str, Query(min_length=1)],
    db: AsyncSession = Depends(get_db),
):
    """Verify email with token from registration email link."""
    result = await db.execute(
        select(User).where(User.verification_token == token)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="无效的验证链接")

    if user.verification_token_expires and user.verification_token_expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="验证链接已过期，请重新注册")

    user.email_verified = True
    user.verification_token = None
    user.verification_token_expires = None
    await db.commit()

    # Redirect to login page with success message
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login?verified=true", status_code=302)


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    x_platform: Annotated[str | None, Header(alias="X-Platform")] = None,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate and issue JWT (OAuth2 password flow)."""
    platform = _read_platform(request, x_platform)

    # OAuth2 form uses username field for email
    result = await db.execute(select(User).where(User.email == form_data.username))
    users = result.scalars().all()

    if not users:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Find user(s) with matching password
    matched_users = [
        u for u in users
        if u.hashed_password and verify_password(form_data.password, u.hashed_password)
    ]

    if not matched_users:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # If multiple identities share this email, deterministically pick one:
    # ADMIN > DOCTOR > PATIENT, then most-recently-updated as tie-breaker.
    role_priority = {UserRole.ADMIN: 0, UserRole.DOCTOR: 1, UserRole.PATIENT: 2}
    user = min(
        matched_users,
        key=lambda u: (
            role_priority.get(u.role, 99),
            -(u.updated_at.timestamp() if u.updated_at else 0),
        ),
    )

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)

    # Phase 1.5: block PENDING/INACTIVE doctors + unverified patients
    if user.role == UserRole.DOCTOR:
        if user.status == UserStatus.INACTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您的账户已被禁用，请联系管理员。",
            )
    if user.role == UserRole.PATIENT and not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="请先验证您的邮箱。验证邮件已发送至您的注册邮箱，请点击邮件中的链接完成验证。",
        )

    await db.commit()

    token = create_access_token(user.id, platform=platform)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
        password_change_required=user.password_change_required,
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: PasswordChangeRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Change current user's password.

    If password_change_required is set, old_password can be omitted
    for the initial password change after default login.
    """
    # Verify old password (skip if admin doing first-time change)
    if not current_user.password_change_required:
        if not data.old_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Old password is required",
            )
        if not verify_password(data.old_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect old password",
            )

    current_user.hashed_password = get_password_hash(data.new_password)
    current_user.password_change_required = False
    await db.commit()


@router.post("/guest", response_model=GuestSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_guest_session(
    request: Request,
    x_platform: Annotated[str | None, Header(alias="X-Platform")] = None,
    db: AsyncSession = Depends(get_db),
) -> GuestSessionResponse:
    """Create a time-limited guest session."""
    platform = _read_platform(request, x_platform)
    session_token = uuid.uuid4().hex
    fingerprint = request.headers.get("User-Agent", "")[:255] or None

    # Read dynamic business config from system_settings
    ttl_hours = await DynamicConfigService.guest_session_ttl_hours(db)
    max_messages = await DynamicConfigService.guest_max_messages(db)

    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    guest = GuestSession(
        session_token=session_token,
        fingerprint=fingerprint,
        max_messages=max_messages,
        expires_at=expires_at,
    )
    db.add(guest)
    await db.commit()
    await db.refresh(guest)

    # Embed token in response — client stores it in localStorage/sessionStorage
    token = create_guest_token(str(guest.id), fingerprint, platform=platform)

    # Return session with token included
    return GuestSessionResponse(
        id=guest.id,
        session_token=token,
        message_count=guest.message_count,
        max_messages=guest.max_messages,
        expires_at=guest.expires_at,
        created_at=guest.created_at,
    )


@router.post("/switch-role", response_model=RoleSwitchResponse)
async def switch_role(
    data: RoleSwitchRequest,
    request: Request,
    current_user: CurrentUser,
    x_platform: Annotated[str | None, Header(alias="X-Platform")] = None,
    db: AsyncSession = Depends(get_db),
) -> RoleSwitchResponse:
    """Switch between patient and doctor identities.

    Restrictions:
    - Cannot switch to the same role.
    - Only PATIENT <-> DOCTOR switches are allowed.
    - Requires both roles to be registered separately.
    """
    platform = _read_platform(request, x_platform)

    if current_user.role == data.target_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot switch to the same role",
        )

    if data.target_role not in (UserRole.PATIENT, UserRole.DOCTOR):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only switch between patient and doctor roles",
        )

    # Check if target role account exists for this email
    result = await db.execute(
        select(User).where(
            User.email == current_user.email,
            User.role == data.target_role,
        )
    )
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {data.target_role.value} account found for this email. Please register first.",
        )

    # Log the switch
    log = RoleSwitchLog(
        user_id=current_user.id,
        from_role=current_user.role,
        to_role=data.target_role,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    db.add(log)
    await db.commit()

    # Issue new token for the target identity
    new_token = create_access_token(target_user.id, platform=platform)

    return RoleSwitchResponse(
        new_token=new_token,
        previous_role=current_user.role,
        current_role=data.target_role,
        switched_at=datetime.now(timezone.utc),
    )


@router.get("/guest/status")
async def get_guest_status(
    x_guest_token: Annotated[str | None, Header(alias="X-Guest-Token")] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Query current guest session status and remaining quota."""
    if not x_guest_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No guest token provided",
        )

    try:
        payload = decode_token(x_guest_token)
        if payload.get("type") != "guest":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid guest token",
            )
        guest_id = payload.get("sub")
        if not guest_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid guest token",
            )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid guest token",
        )

    result = await db.execute(
        select(GuestSession).where(GuestSession.id == uuid.UUID(guest_id))
    )
    guest = result.scalar_one_or_none()

    if not guest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guest session not found",
        )

    if guest.expires_at and guest.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Guest session has expired",
        )

    remaining = max(0, guest.max_messages - guest.message_count)
    return {
        "interaction_count": guest.message_count,
        "max_interactions": guest.max_messages,
        "remaining": remaining,
        "can_interact": remaining > 0,
        "expires_at": guest.expires_at.isoformat() if guest.expires_at else None,
    }


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> UserResponse:
    """Return current authenticated user profile."""
    return UserResponse.model_validate(current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    current_user: CurrentUser,
) -> None:
    """Invalidate the current access token (logout).

    Supports Bearer header and Cookie(auth_token).
    Adds the token to a Redis blacklist with TTL equal to token remaining lifetime.
    """
    # Extract token from Authorization header or Cookie
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else None
    token = token or request.cookies.get("auth_token")

    if not token:
        return  # Nothing to revoke

    try:
        payload = decode_token(token)
        exp = payload.get("exp")
        if exp:
            ttl = int(exp - datetime.now(timezone.utc).timestamp())
            if ttl > 0:
                token_hash = hashlib.sha256(token.encode()).hexdigest()
                redis_client = get_redis()
                await redis_client.setex(
                    f"token_blacklist:{token_hash}",
                    ttl,
                    "1",
                )
    except jwt.ExpiredSignatureError:
        # Token already expired — nothing to blacklist
        pass
    except jwt.InvalidTokenError:
        # Invalid token — ignore
        pass
    except Exception:
        # Redis unavailable — ignore (token will expire naturally)
        pass


@router.delete("/guest", status_code=status.HTTP_204_NO_CONTENT)
async def cleanup_guest_session(
    ctx: CurrentUserContext,
    db: AsyncSession = Depends(get_db),
):
    """Delete guest session and all associated AgentSessions on page leave.

    Called via beforeunload from the frontend when a guest leaves the page.
    Cleans up both the guest_session and any agent_sessions linked to it.
    """
    if ctx.user is not None:
        # Not a guest — nothing to clean up
        return Response(status_code=204)

    guest_id = ctx.guest_id
    if not guest_id:
        return Response(status_code=204)

    from app.models.agent import AgentSession

    # Delete linked agent sessions first
    stmt = delete(AgentSession).where(AgentSession.guest_session_id == uuid.UUID(guest_id))
    await db.execute(stmt)

    # Delete the guest session
    stmt2 = delete(GuestSession).where(GuestSession.id == uuid.UUID(guest_id))
    await db.execute(stmt2)

    await db.commit()


@router.post("/guest/migrate", status_code=status.HTTP_200_OK)
async def migrate_guest_to_user(
    ctx: CurrentUserContext,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Migrate a guest's AgentSessions to a registered user account.

    Called after a guest registers or logs in. Transfers all agent_sessions
    from the guest_session_id to the user_id.
    """
    if ctx.user is None:
        raise HTTPException(status_code=400, detail="User account required for migration")

    guest_id = ctx.guest_id
    if not guest_id:
        return {"migrated": 0}

    from app.models.agent import AgentSession

    stmt = (
        update(AgentSession)
        .where(AgentSession.guest_session_id == uuid.UUID(guest_id))
        .values(guest_session_id=None, user_id=ctx.user.id)
    )
    result = await db.execute(stmt)
    await db.commit()

    return {"migrated": result.rowcount}


# ══════════════════════════════════════════════════════════════════════
# Phase 1.5: Profile edit + credential attachments
# ══════════════════════════════════════════════════════════════════════

class ResendVerificationRequest(BaseModel):
    """Resend verification email request."""
    email: str = Field(..., min_length=1, max_length=255)


@router.post("/resend-verification")
async def resend_verification(
    data: ResendVerificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resend verification email for unverified patients."""
    result = await db.execute(
        select(User).where(
            User.email == data.email,
            User.role == UserRole.PATIENT,
            User.email_verified == False,
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        return {"message": "如果该邮箱已注册且未验证，验证邮件已重新发送。"}

    import secrets
    token = secrets.token_urlsafe(48)
    user.verification_token = token
    user.verification_token_expires = datetime.now(timezone.utc) + timedelta(hours=24)
    await db.commit()

    base_url = str(request.base_url).rstrip("/")
    verify_url = f"{base_url}/api/v1/auth/verify-email?token={token}"

    from app.services.email_service import email_service
    import logging
    _log = logging.getLogger(__name__)

    try:
        await email_service.send_email(
            db=db,
            to_email=user.email,
            subject="【MediCareAI-Agent】请验证您的邮箱",
            html_content=f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;line-height:1.6;color:#333;">
<div style="max-width:600px;margin:0 auto;padding:20px;">
<h2 style="color:#667eea;">重新发送验证邮件</h2>
<p>尊敬的 {user.full_name}：</p>
<p>请点击下方按钮验证您的邮箱地址：</p>
<p style="text-align:center;margin:30px 0;">
  <a href="{verify_url}" style="background:#667eea;color:white;padding:12px 32px;border-radius:6px;text-decoration:none;font-size:16px;">验证邮箱</a>
</p>
<p>或复制以下链接到浏览器打开：</p>
<p style="word-break:break-all;color:#667eea;">{verify_url}</p>
<p style="color:#999;">此链接 24 小时内有效。</p>
</div></body></html>""",
        )
    except Exception as e:
        _log.error(f"Failed to resend verification email to {user.email}: {e}")
        return {"message": "验证邮件发送失败，请稍后再试或联系管理员。"}

    return {"message": "验证邮件已重新发送，请查收邮箱。"}


class ProfileUpdateRequest(BaseModel):
    """Profile edit request (Phase 1.5)."""
    full_name: str | None = Field(None, min_length=1, max_length=255)
    phone: str | None = Field(None, max_length=50)
    age_years: int | None = Field(None, ge=0, le=120)
    age_months: int | None = Field(None, ge=0, le=11)
    gender: str | None = Field(None, pattern=r'^(male|female)$')
    province: str | None = Field(None, max_length=50)
    city: str | None = Field(None, max_length=50)
    district: str | None = Field(None, max_length=50)
    street: str | None = Field(None, max_length=255)
    education: str | None = Field(None, max_length=20)
    specialties: str | None = Field(None, max_length=500)


@router.patch("/auth/me", response_model=UserResponse)
async def update_profile(
    data: ProfileUpdateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Update own profile (role/password/license_number not allowed)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/users/me/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachments(
    files: list[UploadFile] = File(...),
    category: str = Form(default="doctor_license"),
    label: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload doctor credential attachments (Phase 1.5)."""
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
    MAX_TOTAL_SIZE = 20 * 1024 * 1024  # 20 MB
    ALLOWED_MIMES = {"image/jpeg", "image/png", "application/pdf"}

    total_size = 0
    saved = []

    for file in files:
        content = await file.read()
        total_size += len(content)

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"文件 {file.filename} 超过 5MB 限制")
        if file.content_type and file.content_type not in ALLOWED_MIMES:
            raise HTTPException(status_code=400, detail=f"不支持的文件格式: {file.content_type}")

    if total_size > MAX_TOTAL_SIZE:
        raise HTTPException(status_code=413, detail="文件总量超过 20MB 限制")

    # Upload to OSS
    from app.services.oss_service import OssService
    oss = OssService()

    for file in files:
        await file.seek(0)
        content = await file.read()
        url = await oss.upload_bytes(content, file.filename or "attachment")

        att = UserAttachment(
            user_id=current_user.id,
            file_name=file.filename or "unknown",
            file_url=url,
            file_size=len(content),
            mime_type=file.content_type,
            category=category,
            label=label,
        )
        db.add(att)
        saved.append(att)

    await db.commit()

    return {
        "attachments": [
            {
                "id": str(a.id),
                "file_name": a.file_name,
                "file_url": a.file_url,
                "file_size": a.file_size,
                "mime_type": a.mime_type,
                "category": a.category,
                "label": a.label,
                "is_verified": a.is_verified,
                "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None,
            }
            for a in saved
        ],
    }


@router.get("/users/me/attachments")
async def get_attachments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List own credential attachments."""
    result = await db.execute(
        select(UserAttachment).where(UserAttachment.user_id == current_user.id)
    )
    return [
        {
            "id": str(a.id),
            "file_name": a.file_name,
            "file_url": a.file_url,
            "file_size": a.file_size,
            "mime_type": a.mime_type,
            "category": a.category,
            "label": a.label,
            "is_verified": a.is_verified,
            "verify_note": a.verify_note,
            "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None,
        }
        for a in result.scalars().all()
    ]
