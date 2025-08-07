import json
import logging
import hmac
import hashlib
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.orm import sessionmaker
from typing import Optional
from config.settings import Settings
from bot.middlewares.i18n import JsonI18n
from bot.keyboards.inline.user_keyboards import get_subscribe_only_markup
from db.dal import user_dal

EVENT_MAP = {
    "user.expires_in_72_hours": (3, "subscription_72h_notification"),
    "user.expires_in_48_hours": (2, "subscription_48h_notification"),
    "user.expires_in_24_hours": (1, "subscription_24h_notification"),
}

class PanelWebhookService:
    def __init__(self, bot: Bot, settings: Settings, i18n: JsonI18n, async_session_factory: sessionmaker):
        self.bot = bot
        self.settings = settings
        self.i18n = i18n
        self.async_session_factory = async_session_factory

    async def _send_message(
        self,
        user_id: int,
        lang: str,
        message_key: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs,
    ):
        _ = lambda k, **kw: self.i18n.gettext(lang, k, **kw)
        try:
            await self.bot.send_message(
                user_id, _(message_key, **kwargs), reply_markup=reply_markup
            )
        except Exception as e:
            logging.error(f"Failed to send notification to {user_id}: {e}")

    async def _handle_expired_subscription(self, session, user_id: int, user_payload: dict, 
                                         lang: str, markup, first_name: str):
        """Handle expired subscription - auto-renew tribute users if no cancellation was received"""
        from db.dal import subscription_dal, payment_dal
        from datetime import datetime, timezone, timedelta
        
        try:
            # Check if user has tribute subscriptions that weren't cancelled
            user_subs = await subscription_dal.get_active_subscriptions_for_user(session, user_id)
            
            for sub in user_subs:
                # Check if this subscription was marked as cancelled (from tribute cancellation webhook)
                if sub.status_from_panel == 'CANCELLED':
                    logging.info(f"Subscription {sub.subscription_id} for user {user_id} was cancelled, skipping auto-renewal")
                    continue
                    
                # Check if this user has tribute payments
                last_tribute_duration = await payment_dal.get_last_tribute_payment_duration(session, user_id)
                
                if last_tribute_duration is not None:
                    # This user has tribute payments, auto-renew for the same duration
                    logging.info(f"Auto-renewing tribute subscription for user {user_id} for {last_tribute_duration} months")
                    
                    # Extend subscription by the last payment duration
                    new_end_date = datetime.now(timezone.utc) + timedelta(days=last_tribute_duration * 30)
                    
                    await subscription_dal.update_subscription(
                        session,
                        sub.subscription_id,
                        {
                            'end_date': new_end_date,
                            'status_from_panel': 'ACTIVE',
                            'is_active': True
                        }
                    )
                    
                    # Send auto-renewal notification
                    _ = lambda k, **kw: self.i18n.gettext(lang, k, **kw) if self.i18n else k
                    auto_renewal_msg = _(
                        "tribute_auto_renewal",
                        default="🔄 <b>Подписка автоматически продлена</b>\n\n"
                               "Ваша подписка Tribute была автоматически продлена на {months} мес.\n"
                               "Новая дата окончания: {end_date}",
                        user_name=first_name,
                        months=last_tribute_duration,
                        end_date=new_end_date.strftime('%Y-%m-%d')
                    )
                    
                    try:
                        await self.bot.send_message(
                            user_id,
                            auto_renewal_msg,
                            reply_markup=markup,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logging.error(f"Failed to send auto-renewal notification to user {user_id}: {e}")
                        
            await session.commit()
            
        except Exception as e:
            logging.error(f"Error handling expired subscription for user {user_id}: {e}")
            await session.rollback()

    async def handle_event(self, event_name: str, user_payload: dict):
        telegram_id = user_payload.get("telegramId")
        if not telegram_id:
            logging.warning("Panel webhook without telegramId received")
            return
        user_id = int(telegram_id)

        if not self.settings.SUBSCRIPTION_NOTIFICATIONS_ENABLED:
            return

        async with self.async_session_factory() as session:
            db_user = await user_dal.get_user_by_id(session, user_id)
            lang = db_user.language_code if db_user and db_user.language_code else self.settings.DEFAULT_LANGUAGE
            first_name = db_user.first_name or f"User {user_id}" if db_user else f"User {user_id}"

        markup = get_subscribe_only_markup(lang, self.i18n)

        if event_name in EVENT_MAP:
            days_left, msg_key = EVENT_MAP[event_name]
            if days_left <= self.settings.SUBSCRIPTION_NOTIFY_DAYS_BEFORE:
                await self._send_message(
                    user_id,
                    lang,
                    msg_key,
                    reply_markup=markup,
                    user_name=first_name,
                    end_date=user_payload.get("expireAt", "")[:10],
                )
        elif event_name == "user.expired":
            # Check if this is a tribute user that should be auto-renewed (regardless of notification settings)
            await self._handle_expired_subscription(session, user_id, user_payload, lang, markup, first_name)
            
            # Send notification only if enabled
            if self.settings.SUBSCRIPTION_NOTIFY_ON_EXPIRE:
                await self._send_message(
                    user_id,
                    lang,
                    "subscription_expired_notification",
                    reply_markup=markup,
                    user_name=first_name,
                    end_date=user_payload.get("expireAt", "")[:10],
                )
        elif event_name == "user.expired_24_hours_ago" and self.settings.SUBSCRIPTION_NOTIFY_AFTER_EXPIRE:
            await self._send_message(
                user_id,
                lang,
                "subscription_expired_yesterday_notification",
                reply_markup=markup,
                user_name=first_name,
                end_date=user_payload.get("expireAt", "")[:10],
            )

    async def handle_webhook(self, raw_body: bytes, signature_header: Optional[str]) -> web.Response:
        if self.settings.PANEL_WEBHOOK_SECRET:
            if not signature_header:
                return web.Response(status=403, text="no_signature")
            expected_sig = hmac.new(
                self.settings.PANEL_WEBHOOK_SECRET.encode(),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected_sig, signature_header):
                return web.Response(status=403, text="invalid_signature")

        try:
            payload = json.loads(raw_body.decode())
        except Exception:
            return web.Response(status=400, text="bad_request")

        event_name = payload.get("name") or payload.get("event")
        user_data = payload.get("payload") or payload.get("data", {})
        if isinstance(user_data, dict) and "user" in user_data:
            user_data = user_data.get("user") or user_data

        telegram_id = user_data.get("telegramId") if isinstance(user_data, dict) else None

        if not event_name:
            return web.Response(status=200, text="ok_no_event")

        logging.info(
            "Panel webhook event received: %s; telegramId=%s",
            event_name,
            telegram_id if telegram_id is not None else "N/A",
        )

        await self.handle_event(event_name, user_data)
        return web.Response(status=200, text="ok")

async def panel_webhook_route(request: web.Request):
    service: PanelWebhookService = request.app["panel_webhook_service"]
    raw = await request.read()
    signature_header = request.headers.get("X-Remnawave-Signature")
    return await service.handle_webhook(raw, signature_header)
