from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.auth.models import User

router = APIRouter()


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    language: Optional[str] = None


@router.get("/preferences")
async def get_preferences(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).where(User.id == current_user["user_id"]))
    u = r.scalar_one_or_none()
    if not u:
        raise HTTPException(404, "User not found")
    return {"language": u.preferred_language or "en"}


@router.put("/preferences")
async def update_preferences(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).where(User.id == current_user["user_id"]))
    u = r.scalar_one_or_none()
    if not u:
        raise HTTPException(404, "User not found")
    if "language" in payload:
        u.preferred_language = payload["language"]
    await db.commit()
    return {"message": "Saved"}


@router.put("/profile")
async def update_profile(
    payload: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).where(User.id == current_user["user_id"]))
    u = r.scalar_one_or_none()
    if not u:
        raise HTTPException(404, "User not found")
    if payload.name is not None:
        u.full_name = payload.name
    if payload.language is not None:
        u.preferred_language = payload.language
    await db.commit()
    return {"id": u.id, "name": u.full_name, "language": u.preferred_language}
