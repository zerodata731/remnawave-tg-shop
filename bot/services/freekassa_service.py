import hashlib
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from aiohttp import web
from aiogram import Bot
from sqlalchemy.orm import sessionmaker

from config.settings import Settings
from bot.middlewares.i18n import JsonI18n
from bot.services.subscription_service import SubscriptionService
from bot.services.referral_service import ReferralService
from bot.keyboards.inline.user_keyboards import get_connect_and_main_keyboard
from bot.services.notification_service import NotificationService
from db.dal import payment_dal, user_dal
from bot.utils.text_sanitizer import sanitize_display_name, username_for_display


class FreeKassaService:
    def __init__(
        self,
        *,
        bot: Bot,
        settings: Settings,
        i18n: JsonI18n,
        async_session_factory: sessionmaker,
        subscription_service: SubscriptionService,
        referral_service: ReferralService,
    ):
        self.bot = bot
        self.settings = settings
        self.i18n = i18n
        self.async_session_factory = async_session_factory
        self.subscription_service = subscription_service
        self.referral_service = referral_service

        self.merchant_id: Optional[str] = settings.FREEKASSA_MERCHANT_ID
        self.first_secret: Optional[str] = settings.FREEKASSA_FIRST_SECRET
        self.second_secret: Optional[str] = settings.FREEKASSA_SECOND_SECRET
        self.payment_url: str = settings.FREEKASSA_PAYMENT_URL.rstrip("/")
        self.currency: str = settings.FREEKASSA_CURRENCY.upper() if settings.FREEKASSA_CURRENCY else "RUB"

        self.configured: bool = bool(
            settings.FREEKASSA_ENABLED
            and self.merchant_id
            and self.first_secret
            and self.second_secret
        )
        if not self.configured:
            logging.warning("FreeKassaService initialized but not fully configured. Payments disabled.")

    @staticmethod
    def _format_amount(amount: float) -> str:
        """Format amount for signatures with two decimal places."""
        quantized = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{quantized:.2f}"

    def build_payment_link(
        self,
        *,
        payment_db_id: int,
        user_id: int,
        months: int,
        amount: float,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not self.configured:
            logging.error("FreeKassaService is not configured. Cannot build payment link.")
            return None

        amount_str = self._format_amount(amount)
        signature_source = f"{self.merchant_id}:{amount_str}:{self.first_secret}:{payment_db_id}"
        signature = hashlib.md5(signature_source.encode("utf-8")).hexdigest()

        params: Dict[str, Any] = {
            "m": self.merchant_id,
            "oa": amount_str,
            "o": str(payment_db_id),
            "currency": self.currency,
            "s": signature,
            "us_user_id": str(user_id),
            "us_months": str(months),
        }
        if extra_params:
            for key, value in extra_params.items():
                if value is None:
                    continue
                params[f"us_{key}"] = value

        query_string = urlencode(params, doseq=False, safe=":")
        return f"{self.payment_url}?{query_string}"

    def _validate_signature(self, merchant_order_id: str, amount: str, provided_signature: str) -> bool:
        if not self.configured:
            return False
        signature_source = f"{self.merchant_id}:{amount}:{self.second_secret}:{merchant_order_id}"
        expected_signature = hashlib.md5(signature_source.encode("utf-8")).hexdigest()
        return expected_signature.lower() == provided_signature.lower()

    async def webhook_route(self, request: web.Request) -> web.Response:
        if not self.configured:
            return web.Response(status=503, text="freekassa_disabled")

        try:
            data = await request.post()
        except Exception as e:
            logging.error(f"FreeKassa webhook: failed to read POST data: {e}")
            return web.Response(status=400, text="bad_request")

        if not data:
            try:
                data = await request.json()
            except Exception:
                data = {}

        def _get(key: str, default: Optional[str] = None) -> Optional[str]:
            return data.get(key) or data.get(key.lower()) or default

        merchant_id = _get("MERCHANT_ID")
        if merchant_id != self.merchant_id:
            logging.error(f"FreeKassa webhook: merchant mismatch (got {merchant_id})")
            return web.Response(status=403, text="merchant_mismatch")

        signature = _get("SIGN")
        if not signature:
            logging.error("FreeKassa webhook: missing signature")
            return web.Response(status=400, text="missing_signature")

        order_id_str = _get("MERCHANT_ORDER_ID") or _get("ORDER_ID") or _get("o")
        amount_str = _get("AMOUNT") or _get("OA") or _get("amount")
        provider_payment_id = _get("intid") or _get("payment_id") or _get("transaction_id")

        if not order_id_str or not amount_str:
            logging.error("FreeKassa webhook: missing order_id or amount")
            return web.Response(status=400, text="missing_data")

        if not self._validate_signature(order_id_str, amount_str, signature):
            logging.error("FreeKassa webhook: invalid signature")
            return web.Response(status=403, text="invalid_signature")

        try:
            payment_db_id = int(order_id_str)
        except (TypeError, ValueError):
            logging.error(f"FreeKassa webhook: invalid order_id value '{order_id_str}'")
            return web.Response(status=400, text="invalid_order_id")

        async with self.async_session_factory() as session:
            payment = await payment_dal.get_payment_by_db_id(session, payment_db_id)
            if not payment:
                logging.error(f"FreeKassa webhook: payment {payment_db_id} not found")
                return web.Response(status=404, text="payment_not_found")

            if payment.status == "succeeded":
                logging.info(f"FreeKassa webhook: payment {payment_db_id} already succeeded")
                return web.Response(text="YES")

            # Optional amount verification
            try:
                amount_decimal = Decimal(amount_str)
                expected_amount = Decimal(str(payment.amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if amount_decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != expected_amount:
                    logging.warning(
                        f"FreeKassa webhook: amount mismatch for payment {payment_db_id} "
                        f"(expected {expected_amount}, got {amount_decimal})"
                    )
            except Exception as e:
                logging.warning(f"FreeKassa webhook: failed to compare amount for payment {payment_db_id}: {e}")

            activation = None
            referral_bonus = None
            try:
                await payment_dal.update_provider_payment_and_status(
                    session=session,
                    payment_db_id=payment.payment_id,
                    provider_payment_id=str(provider_payment_id or f"freekassa:{order_id_str}"),
                    new_status="succeeded",
                )

                months = payment.subscription_duration_months or 1

                activation = await self.subscription_service.activate_subscription(
                    session,
                    payment.user_id,
                    months,
                    float(payment.amount),
                    payment.payment_id,
                    provider="freekassa",
                )

                referral_bonus = await self.referral_service.apply_referral_bonuses_for_payment(
                    session,
                    payment.user_id,
                    months,
                    current_payment_db_id=payment.payment_id,
                    skip_if_active_before_payment=False,
                )

                await session.commit()
            except Exception as e:
                await session.rollback()
                logging.error(f"FreeKassa webhook: failed to process payment {payment_db_id}: {e}", exc_info=True)
                return web.Response(status=500, text="processing_error")

            db_user = payment.user or await user_dal.get_user_by_id(session, payment.user_id)
            lang = db_user.language_code if db_user and db_user.language_code else self.settings.DEFAULT_LANGUAGE
            _ = lambda k, **kw: self.i18n.gettext(lang, k, **kw) if self.i18n else k

            config_link = None
            final_end = None
            months = payment.subscription_duration_months or 1
            if activation:
                config_link = activation.get("subscription_url")
                final_end = activation.get("end_date")

            applied_days = 0
            if referral_bonus and referral_bonus.get("referee_new_end_date"):
                final_end = referral_bonus["referee_new_end_date"]
                applied_days = referral_bonus.get("referee_bonus_applied_days", 0)

            if not final_end and activation and activation.get("end_date"):
                final_end = activation["end_date"]

            if not config_link:
                config_link = _("config_link_not_available")
            if final_end:
                end_date_str = final_end.strftime("%Y-%m-%d")
            else:
                end_date_str = _("config_link_not_available")

            if applied_days:
                inviter_name_display = _("friend_placeholder")
                if db_user and db_user.referred_by_id:
                    inviter = await user_dal.get_user_by_id(session, db_user.referred_by_id)
                    if inviter:
                        safe_name = sanitize_display_name(inviter.first_name) if inviter.first_name else None
                        if safe_name:
                            inviter_name_display = safe_name
                        elif inviter.username:
                            inviter_name_display = username_for_display(inviter.username, with_at=False)
                text = _(
                    "payment_successful_with_referral_bonus_full",
                    months=months,
                    base_end_date=activation["end_date"].strftime("%Y-%m-%d") if activation and activation.get("end_date") else end_date_str,
                    bonus_days=applied_days,
                    final_end_date=end_date_str,
                    inviter_name=inviter_name_display,
                    config_link=config_link,
                )
            else:
                text = _(
                    "payment_successful_full",
                    months=months,
                    end_date=end_date_str,
                    config_link=config_link,
                )

            markup = get_connect_and_main_keyboard(lang, self.i18n, self.settings, config_link)
            try:
                await self.bot.send_message(
                    payment.user_id,
                    text,
                    reply_markup=markup,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logging.error(f"FreeKassa notification: failed to send message to user {payment.user_id}: {e}")

            try:
                notification_service = NotificationService(self.bot, self.settings, self.i18n)
                await notification_service.notify_payment_received(
                    user_id=payment.user_id,
                    amount=float(payment.amount),
                    currency=self.currency or self.settings.DEFAULT_CURRENCY_SYMBOL,
                    months=months,
                    payment_provider="freekassa",
                    username=db_user.username if db_user else None,
                )
            except Exception as e:
                logging.error(f"FreeKassa notification: failed to notify admins: {e}")

        return web.Response(text="YES")


async def freekassa_webhook_route(request: web.Request) -> web.Response:
    service: FreeKassaService = request.app["freekassa_service"]
    return await service.webhook_route(request)
