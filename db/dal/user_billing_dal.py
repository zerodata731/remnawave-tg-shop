from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.sql import func

from db.models import UserBilling


async def get_user_billing(session: AsyncSession, user_id: int) -> Optional[UserBilling]:
    stmt = select(UserBilling).where(UserBilling.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_yk_payment_method(
    session: AsyncSession,
    *,
    user_id: int,
    payment_method_id: str,
    card_last4: Optional[str] = None,
    card_network: Optional[str] = None,
) -> UserBilling:
    existing = await get_user_billing(session, user_id)
    if existing:
        existing.yookassa_payment_method_id = payment_method_id
        existing.card_last4 = card_last4
        existing.card_network = card_network
        existing.updated_at = func.now()
        await session.flush()
        await session.refresh(existing)
        return existing
    record = UserBilling(
        user_id=user_id,
        yookassa_payment_method_id=payment_method_id,
        card_last4=card_last4,
        card_network=card_network,
    )
    session.add(record)
    await session.flush()
    await session.refresh(record)
    return record
