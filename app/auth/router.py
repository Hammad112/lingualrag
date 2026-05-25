from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.schemas import InitiateRequest, VerifyOTPRequest, RefreshRequest, LogoutRequest
from app.auth.service import auth_service
from app.middleware.auth_middleware import get_current_user

router = APIRouter()


# Frontend uses /auth/send-otp (single endpoint).
# We support both /send-otp (auto-detect purpose) AND the explicit /initiate variants.
@router.post("/send-otp")
async def send_otp(req: InitiateRequest, db: AsyncSession = Depends(get_db)):
    # If email exists → login OTP; else → signup OTP. Frontend handles either.
    from sqlalchemy import select
    from app.auth.models import User

    r = await db.execute(select(User).where(User.email == req.email.lower().strip()))
    purpose = "login" if r.scalar_one_or_none() else "signup"
    return await auth_service.initiate(req.email, req.full_name, purpose, db)


@router.post("/login/initiate")
async def login_initiate(req: InitiateRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.initiate(req.email, None, "login", db)


@router.post("/signup/initiate")
async def signup_initiate(req: InitiateRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.initiate(req.email, req.full_name, "signup", db)


@router.post("/verify-otp")
async def verify_otp(req: VerifyOTPRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.verify_otp(req.email, req.otp, req.purpose, db)


# Frontend-friendly aliases
@router.post("/login")
async def login(req: VerifyOTPRequest, db: AsyncSession = Depends(get_db)):
    # Accept payload with or without explicit purpose
    return await auth_service.verify_otp(req.email, req.otp, "login", db)


class _SignupVerifyRequest(VerifyOTPRequest):
    name: str | None = None


@router.post("/signup")
async def signup(payload: dict, db: AsyncSession = Depends(get_db)):
    email = payload.get("email")
    otp = payload.get("otp")
    name = payload.get("name") or payload.get("full_name")
    # If signup record exists, verify; otherwise the initiate step should have stored the name
    return await auth_service.verify_otp(email, otp, "signup", db)


@router.post("/refresh")
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.refresh(req.refresh_token, db)


@router.post("/logout")
async def logout(req: LogoutRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.logout(req.refresh_token, db)


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await auth_service.me(current_user["user_id"], db)
