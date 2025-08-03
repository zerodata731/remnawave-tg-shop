import logging
import asyncio
from aiogram import Bot
from aiogram.utils.text_decorations import html_decoration as hd
from datetime import datetime, timezone
from typing import Optional, Union, Dict, Any

from config.settings import Settings
from sqlalchemy.orm import sessionmaker
from bot.middlewares.i18n import JsonI18n


class NotificationService:
    """Enhanced notification service for sending messages to admins and log channels"""
    
    def __init__(self, bot: Bot, settings: Settings, i18n: Optional[JsonI18n] = None):
        self.bot = bot
        self.settings = settings
        self.i18n = i18n
    
    async def _send_to_log_channel(self, message: str, thread_id: Optional[int] = None):
        """Send message to configured log channel/group"""
        if not self.settings.LOG_CHAT_ID:
            return
        
        try:
            # Use thread_id if provided, otherwise use from settings
            final_thread_id = thread_id or self.settings.LOG_THREAD_ID
            
            kwargs = {
                "chat_id": self.settings.LOG_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            # Add thread ID for supergroups if specified
            if final_thread_id:
                kwargs["message_thread_id"] = final_thread_id
            
            await self.bot.send_message(**kwargs)
            
        except Exception as e:
            logging.error(f"Failed to send notification to log channel {self.settings.LOG_CHAT_ID}: {e}")
    
    async def _send_to_admins(self, message: str):
        """Send message to all admin users"""
        if not self.settings.ADMIN_IDS:
            return
        
        for admin_id in self.settings.ADMIN_IDS:
            try:
                await self.bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception as e:
                logging.error(f"Failed to send notification to admin {admin_id}: {e}")
    
    async def notify_new_user_registration(self, user_id: int, username: Optional[str] = None, 
                                         first_name: Optional[str] = None, 
                                         referred_by_id: Optional[int] = None):
        """Send notification about new user registration"""
        if not self.settings.LOG_NEW_USERS:
            return
        
        admin_lang = self.settings.DEFAULT_LANGUAGE
        _ = lambda k, **kw: self.i18n.gettext(admin_lang, k, **kw) if self.i18n else k
        
        user_display = first_name or f"ID {user_id}"
        if username:
            user_display += f" (@{username})"
        
        referral_text = ""
        if referred_by_id:
            referral_text = _("log_referral_suffix", default=" (реферал от {referrer_id})", referrer_id=referred_by_id)
        
        message = _(
            "log_new_user_registration",
            default="👤 <b>Новый пользователь</b>\n\n"
                   "🆔 ID: <code>{user_id}</code>\n"
                   "👤 Имя: {user_display}{referral_text}\n"
                   "📅 Время: {timestamp}",
            user_id=user_id,
            user_display=user_display,
            referral_text=referral_text,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        # Send to log channel
        await self._send_to_log_channel(message)
    
    async def notify_payment_received(self, user_id: int, amount: float, currency: str,
                                    months: int, payment_provider: str, 
                                    username: Optional[str] = None):
        """Send notification about successful payment"""
        if not self.settings.LOG_PAYMENTS:
            return
        
        admin_lang = self.settings.DEFAULT_LANGUAGE
        _ = lambda k, **kw: self.i18n.gettext(admin_lang, k, **kw) if self.i18n else k
        
        user_display = f"ID {user_id}"
        if username:
            user_display += f" (@{username})"
        
        provider_emoji = {
            "yookassa": "💳",
            "cryptopay": "₿",
            "stars": "⭐",
            "tribute": "💎"
        }.get(payment_provider.lower(), "💰")
        
        message = _(
            "log_payment_received",
            default="{provider_emoji} <b>Получен платеж</b>\n\n"
                   "👤 Пользователь: {user_display}\n"
                   "💰 Сумма: <b>{amount} {currency}</b>\n"
                   "📅 Период: <b>{months} мес.</b>\n"
                   "🏦 Провайдер: {payment_provider}\n"
                   "🕐 Время: {timestamp}",
            provider_emoji=provider_emoji,
            user_display=user_display,
            amount=amount,
            currency=currency,
            months=months,
            payment_provider=payment_provider,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        # Send to log channel
        await self._send_to_log_channel(message)
    
    async def notify_promo_activation(self, user_id: int, promo_code: str, bonus_days: int,
                                    username: Optional[str] = None):
        """Send notification about promo code activation"""
        if not self.settings.LOG_PROMO_ACTIVATIONS:
            return
        
        admin_lang = self.settings.DEFAULT_LANGUAGE
        _ = lambda k, **kw: self.i18n.gettext(admin_lang, k, **kw) if self.i18n else k
        
        user_display = f"ID {user_id}"
        if username:
            user_display += f" (@{username})"
        
        message = _(
            "log_promo_activation",
            default="🎁 <b>Активирован промокод</b>\n\n"
                   "👤 Пользователь: {user_display}\n"
                   "🏷 Код: <code>{promo_code}</code>\n"
                   "🎯 Бонус: <b>+{bonus_days} дн.</b>\n"
                   "🕐 Время: {timestamp}",
            user_display=user_display,
            promo_code=promo_code,
            bonus_days=bonus_days,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        # Send to log channel
        await self._send_to_log_channel(message)
    
    async def notify_trial_activation(self, user_id: int, end_date: datetime,
                                    username: Optional[str] = None):
        """Send notification about trial activation"""
        if not self.settings.LOG_TRIAL_ACTIVATIONS:
            return
        
        admin_lang = self.settings.DEFAULT_LANGUAGE
        _ = lambda k, **kw: self.i18n.gettext(admin_lang, k, **kw) if self.i18n else k
        
        user_display = f"ID {user_id}"
        if username:
            user_display += f" (@{username})"
        
        message = _(
            "log_trial_activation",
            default="🆓 <b>Активирован триал</b>\n\n"
                   "👤 Пользователь: {user_display}\n"
                   "⏰ Действует до: <b>{end_date}</b>\n"
                   "🕐 Время: {timestamp}",
            user_display=user_display,
            end_date=end_date.strftime("%Y-%m-%d %H:%M"),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        # Send to log channel
        await self._send_to_log_channel(message)
    
    async def send_custom_notification(self, message: str, to_admins: bool = False, 
                                     to_log_channel: bool = True, thread_id: Optional[int] = None):
        """Send custom notification message"""
        if to_log_channel:
            await self._send_to_log_channel(message, thread_id)
        if to_admins:
            await self._send_to_admins(message)


# Legacy functions for backward compatibility
async def notify_admins(bot: Bot, settings: Settings, i18n: JsonI18n,
                        message_key: str, parse_mode: str | None = None,
                        **kwargs) -> None:
    if not settings.ADMIN_IDS:
        return
    admin_lang = settings.DEFAULT_LANGUAGE
    msg = i18n.gettext(admin_lang, message_key, **kwargs)
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, msg, parse_mode=parse_mode)
        except Exception as e:
            logging.error(f"Failed to send admin notification to {admin_id}: {e}")


async def notify_admin_new_trial(bot: Bot, settings: Settings, i18n: JsonI18n,
                                 user_id: int, end_date: datetime) -> None:
    """Send notification to admins about new trial activation (legacy)"""
    notification_service = NotificationService(bot, settings, i18n)
    await notification_service.notify_trial_activation(user_id, end_date)


async def notify_admin_new_payment(bot: Bot, settings: Settings, i18n: JsonI18n,
                                   user_id: int, months: int, amount: float,
                                   currency: str | None = None) -> None:
    currency_symbol = currency or settings.DEFAULT_CURRENCY_SYMBOL
    await notify_admins(
        bot,
        settings,
        i18n,
        "admin_new_payment_notification",
        user_id=user_id,
        months=months,
        amount=f"{amount:.2f}",
        currency=currency_symbol,
    )


async def notify_admin_promo_activation(bot: Bot, settings: Settings,
                                        i18n: JsonI18n, user_id: int,
                                        code: str,
                                        bonus_days: int) -> None:
    await notify_admins(
        bot,
        settings,
        i18n,
        "admin_promo_activation_notification",
        user_id=user_id,
        code=code,
        bonus_days=bonus_days,
    )