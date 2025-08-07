import logging
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import update, delete, func, and_
from datetime import datetime

from ..models import User, Subscription


async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    stmt = select(User).where(User.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    clean_username = username.lstrip("@").lower()
    stmt = select(User).where(func.lower(User.username) == clean_username)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_panel_uuid(
    session: AsyncSession, panel_uuid: str
) -> Optional[User]:
    stmt = select(User).where(User.panel_user_uuid == panel_uuid)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


## Removed unused generic get_user helper to keep DAL explicit and simple


async def create_user(session: AsyncSession, user_data: Dict[str, Any]) -> User:

    if "registration_date" not in user_data:
        user_data["registration_date"] = datetime.now()

    new_user = User(**user_data)
    session.add(new_user)
    await session.flush()
    await session.refresh(new_user)
    logging.info(
        f"New user {new_user.user_id} created in DAL. Referred by: {new_user.referred_by_id or 'N/A'}."
    )
    return new_user


async def update_user(
    session: AsyncSession, user_id: int, update_data: Dict[str, Any]
) -> Optional[User]:
    user = await get_user_by_id(session, user_id)
    if user:
        for key, value in update_data.items():
            setattr(user, key, value)
        await session.flush()
        await session.refresh(user)
    return user


async def update_user_language(
    session: AsyncSession, user_id: int, lang_code: str
) -> bool:
    stmt = update(User).where(User.user_id == user_id).values(language_code=lang_code)
    result = await session.execute(stmt)
    return result.rowcount > 0


async def get_banned_users(session: AsyncSession) -> List[User]:
    """Get all banned users"""
    stmt = (
        select(User)
        .where(User.is_banned == True)
        .order_by(User.registration_date.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_all_active_user_ids_for_broadcast(session: AsyncSession) -> List[int]:
    stmt = select(User.user_id).where(User.is_banned == False)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_all_users_with_panel_uuid(session: AsyncSession) -> List[User]:
    stmt = select(User).where(User.panel_user_uuid.is_not(None))
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_enhanced_user_statistics(session: AsyncSession) -> Dict[str, Any]:
    """Get comprehensive user statistics including active users, trial users, etc."""
    from datetime import datetime, timedelta
    
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Total users
    total_users_stmt = select(func.count(User.user_id))
    total_users = (await session.execute(total_users_stmt)).scalar() or 0
    
    # Banned users
    banned_users_stmt = select(func.count(User.user_id)).where(User.is_banned == True)
    banned_users = (await session.execute(banned_users_stmt)).scalar() or 0
    
    # Active users today (users with login activity - for now using registration as proxy)
    active_today_stmt = select(func.count(User.user_id)).where(
        User.registration_date >= today_start
    )
    active_today = (await session.execute(active_today_stmt)).scalar() or 0
    
    # Users with active paid subscriptions
    paid_subs_stmt = (
        select(func.count(func.distinct(Subscription.user_id)))
        .join(User, Subscription.user_id == User.user_id)
        .where(
            and_(
                Subscription.is_active == True,
                Subscription.end_date > now,
                Subscription.provider.is_not(None)  # Not trial
            )
        )
    )
    paid_subs_users = (await session.execute(paid_subs_stmt)).scalar() or 0
    
    # Users on trial period
    trial_subs_stmt = (
        select(func.count(func.distinct(Subscription.user_id)))
        .join(User, Subscription.user_id == User.user_id)
        .where(
            and_(
                Subscription.is_active == True,
                Subscription.end_date > now,
                Subscription.provider.is_(None)  # Trial subscriptions
            )
        )
    )
    trial_users = (await session.execute(trial_subs_stmt)).scalar() or 0
    
    # Inactive users (no active subscription)
    inactive_users = total_users - paid_subs_users - trial_users - banned_users
    
    # Users attracted via referral
    referral_users_stmt = select(func.count(User.user_id)).where(User.referred_by_id.is_not(None))
    referral_users = (await session.execute(referral_users_stmt)).scalar() or 0
    
    return {
        "total_users": total_users,
        "banned_users": banned_users,
        "active_today": active_today,
        "paid_subscriptions": paid_subs_users,
        "trial_users": trial_users,
        "inactive_users": max(0, inactive_users),
        "referral_users": referral_users
    }
