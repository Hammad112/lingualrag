from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import datetime, timedelta

from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.auth.models import User
from app.documents.models import Document
from app.chat.models import Message

router = APIRouter()


async def require_admin(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = r.scalar_one_or_none()
    if not user or not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return current_user


@router.get("/analytics")
async def analytics(
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total_users = await db.scalar(select(func.count(User.id)))
    total_docs = await db.scalar(select(func.count(Document.id)))
    total_queries = await db.scalar(
        select(func.count(Message.id)).where(Message.role == "user")
    )
    avg_latency = await db.scalar(
        select(func.avg(Message.latency_ms)).where(Message.role == "assistant")
    )

    lang_rows = (await db.execute(
        select(Message.language, func.count(Message.id))
        .where(Message.role == "user")
        .group_by(Message.language)
    )).all()
    language_distribution = {row[0] or "unknown": int(row[1]) for row in lang_rows}

    thirty = datetime.utcnow() - timedelta(days=30)
    daily_rows = (await db.execute(
        select(Message.created_at, Message.id)
        .where(Message.role == "user", Message.created_at >= thirty)
    )).all()
    daily_map: dict[str, int] = {}
    for created_at, _id in daily_rows:
        if created_at:
            key = created_at.strftime("%Y-%m-%d")
            daily_map[key] = daily_map.get(key, 0) + 1
    daily_queries = [{"date": d, "count": c} for d, c in sorted(daily_map.items())]

    return {
        "totalUsers": total_users or 0,
        "totalQueries": total_queries or 0,
        "totalDocuments": total_docs or 0,
        "averageResponseTime": float(avg_latency or 0) / 1000.0,  # seconds
        "languageDistribution": language_distribution,
        "dailyQueries": daily_queries,
    }


@router.get("/users")
async def list_users(
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).order_by(desc(User.created_at)))
    users = [
        {
            "id": u.id,
            "email": u.email,
            "name": u.full_name,
            "isActive": u.is_active,
            "isAdmin": u.is_admin,
            "createdAt": u.created_at.isoformat() if u.created_at else None,
        }
        for u in r.scalars().all()
    ]
    return {"users": users}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Not found")
    await db.delete(user)
    await db.commit()
    return {"message": "Deleted"}
