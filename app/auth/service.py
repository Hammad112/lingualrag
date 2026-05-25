import json
from datetime import datetime, timedelta
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.config import settings
from app.auth.models import User, OTPRecord, UserSession
from app.auth.otp import generate_otp, send_otp_email
from app.auth.jwt_utils import create_access_token, create_refresh_token


def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.full_name or u.email.split("@")[0],
        "language": u.preferred_language or "en",
        "isAdmin": bool(u.is_admin),
        "createdAt": (u.created_at or datetime.utcnow()).isoformat(),
    }


class AuthService:
    async def initiate(self, email: str, full_name: str | None, purpose: str, db: AsyncSession):
        email = email.lower().strip()
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if purpose == "login" and not user:
            raise HTTPException(404, "No account found with this email")
        if purpose == "signup" and user:
            raise HTTPException(409, "An account already exists with this email")

        otp = generate_otp()
        record = OTPRecord(
            email=email,
            otp_code=otp,
            purpose=purpose,
            expires_at=datetime.utcnow() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
            metadata_json=json.dumps({"full_name": full_name}) if full_name else None,
        )
        db.add(record)
        await db.commit()

        await send_otp_email(email, otp, purpose)
        return {"message": "OTP sent", "email": email}

    async def verify_otp(self, email: str, otp: str, purpose: str, db: AsyncSession) -> dict:
        email = email.lower().strip()

        # Auto-detect: pick the latest unused OTP regardless of purpose, then
        # route by whether the user exists. This avoids signup/login mismatches
        # when the frontend can't know which purpose /send-otp used.
        result = await db.execute(
            select(OTPRecord)
            .where(
                OTPRecord.email == email,
                OTPRecord.is_used == False,  # noqa: E712
            )
            .order_by(OTPRecord.created_at.desc())
        )
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(404, "No active OTP — request a new one")

        purpose = record.purpose

        if record.expires_at < datetime.utcnow():
            raise HTTPException(410, "OTP has expired")

        if record.attempts >= 5:
            raise HTTPException(429, "Too many attempts")

        if record.otp_code != otp.strip():
            record.attempts += 1
            await db.commit()
            raise HTTPException(401, "Invalid OTP")

        record.is_used = True

        if purpose == "signup":
            meta = json.loads(record.metadata_json or "{}")
            user = User(email=email, full_name=meta.get("full_name") or email.split("@")[0])
            db.add(user)
            await db.flush()
        else:
            r = await db.execute(select(User).where(User.email == email))
            user = r.scalar_one_or_none()
            if not user:
                raise HTTPException(404, "User not found")

        if not user.is_active:
            raise HTTPException(403, "Account disabled")

        access = create_access_token(user.id, user.email)
        refresh, exp = create_refresh_token(user.id)

        db.add(UserSession(user_id=user.id, refresh_token=refresh, expires_at=exp))
        await db.commit()

        return {"user": _user_to_dict(user), "token": access, "refreshToken": refresh}

    async def refresh(self, refresh_token: str, db: AsyncSession) -> dict:
        from app.auth.jwt_utils import decode_token

        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(401, "Invalid refresh token")

        r = await db.execute(select(UserSession).where(UserSession.refresh_token == refresh_token))
        sess = r.scalar_one_or_none()
        if not sess or sess.is_revoked or sess.expires_at < datetime.utcnow():
            raise HTTPException(401, "Refresh token revoked or expired")

        u = await db.execute(select(User).where(User.id == payload["sub"]))
        user = u.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(401, "User not found or disabled")

        # Rotate
        sess.is_revoked = True
        access = create_access_token(user.id, user.email)
        new_refresh, exp = create_refresh_token(user.id)
        db.add(UserSession(user_id=user.id, refresh_token=new_refresh, expires_at=exp))
        await db.commit()

        return {"user": _user_to_dict(user), "token": access, "refreshToken": new_refresh}

    async def logout(self, refresh_token: str, db: AsyncSession) -> dict:
        await db.execute(
            update(UserSession)
            .where(UserSession.refresh_token == refresh_token)
            .values(is_revoked=True)
        )
        await db.commit()
        return {"message": "Logged out"}

    async def me(self, user_id: str, db: AsyncSession) -> dict:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found")
        return {"user": _user_to_dict(user)}


auth_service = AuthService()
