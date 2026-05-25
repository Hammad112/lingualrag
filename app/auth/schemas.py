from pydantic import BaseModel, EmailStr
from typing import Optional, Literal


class InitiateRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str
    purpose: Literal["login", "signup"]


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    language: str
    isAdmin: bool
    createdAt: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    user: UserOut
    token: str
    refreshToken: str
