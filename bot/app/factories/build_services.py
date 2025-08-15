from aiogram import Bot
from sqlalchemy.orm import sessionmaker
from typing import Tuple

from config.settings import Settings
from bot.services.yookassa_service import YooKassaService
from bot.services.panel_api_service import PanelApiService
from bot.services.subscription_service import SubscriptionService
from bot.services.referral_service import ReferralService
from bot.services.promo_code_service import PromoCodeService
from bot.services.stars_service import StarsService
from bot.services.tribute_service import TributeService
from bot.services.crypto_pay_service import CryptoPayService
from bot.services.panel_webhook_service import PanelWebhookService


def build_core_services(settings: Settings, bot: Bot, async_session_factory: sessionmaker):
    panel_service = PanelApiService(settings)
    subscription_service = SubscriptionService(settings, panel_service, bot)
    referral_service = ReferralService(settings, subscription_service, bot)
    promo_code_service = PromoCodeService(settings, subscription_service, bot)
    stars_service = StarsService(bot, settings, None, subscription_service, referral_service)
    cryptopay_service = CryptoPayService(
        settings.CRYPTOPAY_TOKEN,
        settings.CRYPTOPAY_NETWORK,
        bot,
        settings,
        None,
        async_session_factory,
        subscription_service,
        referral_service,
    )
    tribute_service = TributeService(
        bot,
        settings,
        None,
        async_session_factory,
        panel_service,
        subscription_service,
        referral_service,
    )
    panel_webhook_service = PanelWebhookService(bot, settings, None, async_session_factory)

    return {
        "panel_service": panel_service,
        "subscription_service": subscription_service,
        "referral_service": referral_service,
        "promo_code_service": promo_code_service,
        "stars_service": stars_service,
        "cryptopay_service": cryptopay_service,
        "tribute_service": tribute_service,
        "panel_webhook_service": panel_webhook_service,
    }


