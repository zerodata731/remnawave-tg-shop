import logging
from aiogram import Router, types, Bot
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from db.dal import user_dal, payment_dal
from bot.services.referral_service import ReferralService
from bot.middlewares.i18n import JsonI18n

router = Router(name="inline_mode_router")


@router.inline_query()
async def inline_query_handler(inline_query: InlineQuery,
                               settings: Settings,
                               i18n_data: dict,
                               referral_service: ReferralService,
                               bot: Bot,
                               session: AsyncSession):
    """Handle inline queries for referral links and admin statistics"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    user_id = inline_query.from_user.id
    query = inline_query.query.lower().strip()
    
    results: List[InlineQueryResultArticle] = []
    
    # Check if user is admin
    is_admin = user_id in settings.ADMIN_IDS if settings.ADMIN_IDS else False
    
    try:
        # For all users: referral functionality
        if not query or "реф" in query or "ref" in query or "друг" in query or "friend" in query:
            referral_result = await create_referral_result(
                inline_query, bot, referral_service, i18n, current_lang, settings
            )
            if referral_result:
                results.append(referral_result)
        
        # For admins: statistics
        if is_admin and (not query or "стат" in query or "stat" in query or "админ" in query or "admin" in query):
            stats_results = await create_admin_stats_results(
                session, i18n, current_lang, settings
            )
            results.extend(stats_results)
        

        
        # Limit results to 50 (Telegram limit)
        results = results[:50]
        
        await inline_query.answer(
            results=results,
            cache_time=30,  # Cache for 30 seconds
            is_personal=True  # Results are personalized
        )
        
    except Exception as e:
        logging.error(f"Error handling inline query from user {user_id}: {e}")
        # Send empty results in case of error
        await inline_query.answer(results=[], cache_time=10)


async def create_referral_result(inline_query: InlineQuery, bot: Bot,
                                referral_service: ReferralService,
                                i18n_instance, lang: str, settings: Settings) -> Optional[InlineQueryResultArticle]:
    """Create referral link result for inline query"""
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        if not bot_username:
            return None
        
        user_id = inline_query.from_user.id
        referral_link = referral_service.generate_referral_link(bot_username, user_id)
        
        # Create message content
        message_text = _(
            "inline_referral_message",
            default="🚀 Привет! Попробуй этот крутой VPN сервис!\n\n"
                   "✨ Быстрый и надежный\n"
                   "🔒 Полная анонимность\n"
                   "🌍 Серверы по всему миру\n"
                   "💎 Бесплатный пробный период\n\n{referral_link}",
            referral_link=referral_link
        )
        
        return InlineQueryResultArticle(
            id="referral_link",
            title=_(
                "inline_referral_title",
                default="🎁 Пригласить друга"
            ),
            description=_(
                "inline_referral_description", 
                default="Поделиться реферальной ссылкой для получения бонусов"
            ),
            input_message_content=InputTextMessageContent(
                message_text=message_text,
                disable_web_page_preview=True
            ),
            thumbnail_url=settings.INLINE_REFERRAL_THUMBNAIL_URL
        )
        
    except Exception as e:
        logging.error(f"Error creating referral result: {e}")
        return None


async def create_admin_stats_results(session: AsyncSession, i18n_instance, lang: str, settings: Settings) -> List[InlineQueryResultArticle]:
    """Create admin statistics results for inline query"""
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    results = []
    
    try:
        # Quick user stats
        user_stats_result = await create_user_stats_result(session, i18n_instance, lang, settings)
        if user_stats_result:
            results.append(user_stats_result)
        
        # Quick financial stats
        financial_stats_result = await create_financial_stats_result(session, i18n_instance, lang, settings)
        if financial_stats_result:
            results.append(financial_stats_result)
        
        # Quick system stats
        system_stats_result = await create_system_stats_result(session, i18n_instance, lang, settings)
        if system_stats_result:
            results.append(system_stats_result)
            
    except Exception as e:
        logging.error(f"Error creating admin stats results: {e}")
    
    return results


async def create_user_stats_result(session: AsyncSession, i18n_instance, lang: str, settings: Settings) -> Optional[InlineQueryResultArticle]:
    """Create user statistics result"""
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    
    try:
        from db.dal.user_dal import get_enhanced_user_statistics
        user_stats = await get_enhanced_user_statistics(session)
        
        stats_text = _(
            "inline_user_stats_message",
            default="👥 <b>Статистика пользователей</b>\n\n"
                   "📊 Всего: <b>{total}</b>\n"
                   "📈 Активных сегодня: <b>{active_today}</b>\n"
                   "💳 С платной подпиской: <b>{paid}</b>\n"
                   "🆓 На пробном периоде: <b>{trial}</b>\n"
                   "😴 Неактивных: <b>{inactive}</b>\n"
                   "🚫 Заблокированных: <b>{banned}</b>\n"
                   "🎁 По реферальной программе: <b>{referral}</b>",
            total=user_stats['total_users'],
            active_today=user_stats['active_today'],
            paid=user_stats['paid_subscriptions'],
            trial=user_stats['trial_users'],
            inactive=user_stats['inactive_users'],
            banned=user_stats['banned_users'],
            referral=user_stats['referral_users']
        )
        
        return InlineQueryResultArticle(
            id="admin_user_stats",
            title=_(
                "inline_admin_user_stats_title",
                default="👥 Статистика пользователей"
            ),
            description=_(
                "inline_stats_description",
                default="Всего: {total}, Активных: {active}",
                total=user_stats['total_users'],
                active=user_stats['paid_subscriptions']
            ),
            input_message_content=InputTextMessageContent(
                message_text=stats_text,
                parse_mode="HTML"
            ),
            thumbnail_url=settings.INLINE_USER_STATS_THUMBNAIL_URL
        )
        
    except Exception as e:
        logging.error(f"Error creating user stats result: {e}")
        return None


async def create_financial_stats_result(session: AsyncSession, i18n_instance, lang: str, settings: Settings) -> Optional[InlineQueryResultArticle]:
    """Create financial statistics result"""
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    
    try:
        from db.dal.payment_dal import get_financial_statistics
        financial_stats = await get_financial_statistics(session)
        
        stats_text = _(
            "inline_financial_stats_message",
            default="💰 <b>Финансовая статистика</b>\n\n"
                   "📅 За сегодня: <b>{today:.2f} RUB</b>\n"
                   "   ({today_count} платежей)\n"
                   "📅 За неделю: <b>{week:.2f} RUB</b>\n"
                   "📅 За месяц: <b>{month:.2f} RUB</b>\n"
                   "🏆 За все время: <b>{all_time:.2f} RUB</b>",
            today=financial_stats['today_revenue'],
            today_count=financial_stats['today_payments_count'],
            week=financial_stats['week_revenue'],
            month=financial_stats['month_revenue'],
            all_time=financial_stats['all_time_revenue']
        )
        
        return InlineQueryResultArticle(
            id="admin_financial_stats",
            title=_(
                "inline_admin_financial_stats_title",
                default="💰 Финансовая статистика"
            ),
            description=_(
                "inline_financial_description",
                default="Сегодня: {today} RUB",
                today=f"{financial_stats['today_revenue']:.2f}"
            ),
            input_message_content=InputTextMessageContent(
                message_text=stats_text,
                parse_mode="HTML"
            ),
            thumbnail_url=settings.INLINE_FINANCIAL_STATS_THUMBNAIL_URL
        )
        
    except Exception as e:
        logging.error(f"Error creating financial stats result: {e}")
        return None


async def create_system_stats_result(session: AsyncSession, i18n_instance, lang: str, settings: Settings) -> Optional[InlineQueryResultArticle]:
    """Create system statistics result with online/offline/expired/limited info"""
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    
    try:
        from datetime import datetime, timezone
        from sqlalchemy import select, func, and_
        from db.models import User, Subscription
        
        now = datetime.now(timezone.utc)
        
        # Count active subscriptions (online)
        active_subs_stmt = select(func.count(Subscription.subscription_id)).where(
            and_(
                Subscription.is_active == True,
                Subscription.end_date > now
            )
        )
        active_subs = (await session.execute(active_subs_stmt)).scalar() or 0
        
        # Count expired subscriptions
        expired_subs_stmt = select(func.count(Subscription.subscription_id)).where(
            and_(
                Subscription.is_active == True,
                Subscription.end_date <= now
            )
        )
        expired_subs = (await session.execute(expired_subs_stmt)).scalar() or 0
        
        # Count total users (approximation for "total")
        total_users_stmt = select(func.count(User.user_id))
        total_users = (await session.execute(total_users_stmt)).scalar() or 0
        
        # Offline = users without active subscriptions
        offline_users = total_users - active_subs
        
        stats_text = _(
            "inline_system_stats_message",
            default="🖥 <b>Системная статистика</b>\n\n"
                   "🟢 Онлайн: <b>{online}</b>\n"
                   "🔴 Офлайн: <b>{offline}</b>\n"
                   "⏰ Истекшие: <b>{expired}</b>\n"
                   "👥 Всего пользователей: <b>{total}</b>",
            online=active_subs,
            offline=max(0, offline_users),
            expired=expired_subs,
            total=total_users
        )
        
        return InlineQueryResultArticle(
            id="admin_system_stats",
            title=_(
                "inline_admin_system_stats_title",
                default="🖥 Системная статистика"
            ),
            description=_(
                "inline_system_description",
                default="Онлайн: {online}, Офлайн: {offline}",
                online=active_subs,
                offline=max(0, offline_users)
            ),
            input_message_content=InputTextMessageContent(
                message_text=stats_text,
                parse_mode="HTML"
            ),
            thumbnail_url=settings.INLINE_SYSTEM_STATS_THUMBNAIL_URL
        )
        
    except Exception as e:
        logging.error(f"Error creating system stats result: {e}")
        return None


