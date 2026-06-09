"""Authentication request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole, UserStatus


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    phone: str | None = Field(None, max_length=50)


class UserRegister(UserBase):
    """User registration request (Phase 1.5 expanded)."""

    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = UserRole.PATIENT

    # Patient + Doctor shared
    age_years: int | None = Field(None, ge=0, le=120)
    age_months: int | None = Field(None, ge=0, le=11)
    gender: str | None = Field(None, pattern=r'^(male|female)$')
    province: str | None = Field(None, max_length=50)
    city: str | None = Field(None, max_length=50)
    district: str | None = Field(None, max_length=50)
    street: str | None = Field(None, max_length=255)
    education: str | None = Field(None, max_length=20)

    # Doctor-specific
    license_number: str | None = Field(None, max_length=100)
    hospital: str | None = Field(None, max_length=255)
    department: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=50)
    years_of_practice: int | None = Field(None, ge=0, le=60)
    specialties: str | None = Field(None, max_length=500)


class UserLogin(BaseModel):
    """User login request."""

    email: EmailStr
    password: str


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str | None = None
    type: str = "access"
    exp: datetime | None = None


class Token(BaseModel):
    """Token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(UserBase):
    """User response schema (Phase 1.5 expanded)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: UserRole
    status: UserStatus
    is_verified: bool
    license_number: str | None
    hospital: str | None
    department: str | None
    title: str | None
    age_years: int | None
    age_months: int | None
    gender: str | None
    province: str | None
    city: str | None
    district: str | None
    street: str | None
    education: str | None
    years_of_practice: int | None
    specialties: str | None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
    password_change_required: bool


class PasswordChangeRequest(BaseModel):
    """Password change request."""

    old_password: str | None = Field(None, min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class LoginResponse(Token):
    """Login response with user data."""

    user: UserResponse
    password_change_required: bool = False


class GuestSessionResponse(BaseModel):
    """Guest session response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_token: str
    message_count: int
    max_messages: int
    expires_at: datetime
    created_at: datetime


class RoleSwitchRequest(BaseModel):
    """Role switch request."""

    target_role: UserRole


class RoleSwitchResponse(BaseModel):
    """Role switch response."""

    new_token: str
    previous_role: UserRole
    current_role: UserRole
    switched_at: datetime
