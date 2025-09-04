import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from typing import Optional, Dict, Any, Union, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from config.settings import Settings
from db.dal import payment_dal
from bot.keyboards.inline.user_keyboards import (
    get_subscription_options_keyboard, get_payment_method_keyboard,
    get_payment_url_keyboard, get_back_to_main_menu_markup,
    get_payment_methods_manage_keyboard, get_payment_method_delete_confirm_keyboard,
    get_payment_method_details_keyboard, get_bind_url_keyboard,
    get_payment_methods_list_keyboard, get_back_to_payment_methods_keyboard)
from bot.services.yookassa_service import YooKassaService
from db.dal import user_billing_dal
from bot.services.stars_service import StarsService
from bot.services.crypto_pay_service import CryptoPayService
from bot.services.subscription_service import SubscriptionService
from bot.services.panel_api_service import PanelApiService
from bot.services.referral_service import ReferralService
from bot.services.yookassa_service import YooKassaService
from bot.middlewares.i18n import JsonI18n
from db.dal import subscription_dal
from db.models import Subscription, Payment

router = Router(name="user_subscription_router")


async def display_subscription_options(event: Union[types.Message,
                                                    types.CallbackQuery],
                                       i18n_data: dict, settings: Settings,
                                       session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")

    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs
                                                  ) if i18n else key

    if not i18n:
        err_msg = "Language service error."
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer(err_msg, show_alert=True)
            except Exception:
                pass
        elif isinstance(event, types.Message):
            await event.answer(err_msg)
        return

    currency_symbol_val = settings.DEFAULT_CURRENCY_SYMBOL
    text_content = get_text("select_subscription_period"
                            ) if settings.subscription_options else get_text(
                                "no_subscription_options_available")

    reply_markup = get_subscription_options_keyboard(
        settings.subscription_options, currency_symbol_val, current_lang, i18n
    ) if settings.subscription_options else get_back_to_main_menu_markup(
        current_lang, i18n)

    target_message_obj = event.message if isinstance(
        event, types.CallbackQuery) else event
    if not target_message_obj:
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer(get_text("error_occurred_try_again"),
                                   show_alert=True)
            except Exception:
                pass
        return

    if isinstance(event, types.CallbackQuery):
        try:
            await target_message_obj.edit_text(text_content,
                                               reply_markup=reply_markup)
        except Exception:
            await target_message_obj.answer(text_content,
                                            reply_markup=reply_markup)
        try:
            await event.answer()
        except Exception:
            pass
    else:
        await target_message_obj.answer(text_content,
                                        reply_markup=reply_markup)


@router.callback_query(F.data.startswith("subscribe_period:"))
async def select_subscription_period_callback_handler(
        callback: types.CallbackQuery, settings: Settings, i18n_data: dict,
        session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs
                                                  ) if i18n else key

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"),
                                  show_alert=True)
        except Exception:
            pass
        return

    try:
        months = int(callback.data.split(":")[-1])
    except (ValueError, IndexError):
        logging.error(
            f"Invalid subscription period in callback_data: {callback.data}")
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    price_rub = settings.subscription_options.get(months)
    if price_rub is None:
        logging.error(
            f"Price not found for {months} months subscription period in settings.subscription_options."
        )
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    currency_symbol_val = settings.DEFAULT_CURRENCY_SYMBOL
    text_content = get_text("choose_payment_method")
    tribute_url = settings.tribute_payment_links.get(months)
    stars_price = settings.stars_subscription_options.get(months)
    reply_markup = get_payment_method_keyboard(
        months,
        price_rub,
        tribute_url,
        stars_price,
        currency_symbol_val,
        current_lang,
        i18n,
        settings,
    )

    try:
        await callback.message.edit_text(text_content,
                                         reply_markup=reply_markup)
    except Exception as e_edit:
        logging.warning(
            f"Edit message for payment method selection failed: {e_edit}. Sending new one."
        )
        await callback.message.answer(text_content,
                                      reply_markup=reply_markup)
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay_stars:"))
async def pay_stars_callback_handler(
        callback: types.CallbackQuery, settings: Settings, i18n_data: dict,
        session: AsyncSession, bot: Bot, stars_service: StarsService):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")

    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"), show_alert=True)
        except Exception:
            pass
        return

    try:
        _, data_payload = callback.data.split(":", 1)
        months_str, price_str = data_payload.split(":")
        months = int(months_str)
        stars_price = int(price_str)
    except (ValueError, IndexError):
        logging.error(f"Invalid pay_stars data in callback: {callback.data}")
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    user_id = callback.from_user.id
    payment_description = get_text("payment_description_subscription", months=months)

    payment_id = await stars_service.create_invoice(
        session, user_id, months, stars_price, payment_description)
    if payment_id is None:
        await callback.message.edit_text(get_text("error_payment_gateway"))
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay_yk:"))
async def pay_yk_callback_handler(
        callback: types.CallbackQuery, settings: Settings, i18n_data: dict,
        yookassa_service: YooKassaService, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")

    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs
                                                  ) if i18n else key

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"),
                                  show_alert=True)
        except Exception:
            pass
        return

    if not yookassa_service or not yookassa_service.configured:
        logging.error("YooKassa service is not configured or unavailable.")
        target_msg_edit = callback.message
        await target_msg_edit.edit_text(get_text("payment_service_unavailable")
                                        )
        try:
            await callback.answer(get_text("payment_service_unavailable_alert"),
                                  show_alert=True)
        except Exception:
            pass
        return

    try:
        _, data_payload = callback.data.split(":", 1)
        months_str, price_str = data_payload.split(":")
        months = int(months_str)
        price_rub = float(price_str)
    except (ValueError, IndexError):
        logging.error(
            f"Invalid pay_yk data in callback: {callback.data}")
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    user_id = callback.from_user.id

    payment_description = get_text("payment_description_subscription",
                                   months=months)
    currency_code_for_yk = "RUB"

    payment_record_data = {
        "user_id": user_id,
        "amount": price_rub,
        "currency": currency_code_for_yk,
        "status": "pending_yookassa",
        "description": payment_description,
        "subscription_duration_months": months,
    }
    db_payment_record = None
    try:
        db_payment_record = await payment_dal.create_payment_record(
            session, payment_record_data)
        await session.commit()
        logging.info(
            f"Payment record {db_payment_record.payment_id} created for user {user_id} with status 'pending_yookassa'."
        )
    except Exception as e_db_payment:
        await session.rollback()
        logging.error(
            f"Failed to create payment record in DB for user {user_id}: {e_db_payment}",
            exc_info=True)
        await callback.message.edit_text(
            get_text("error_creating_payment_record"))
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    if not db_payment_record:
        await callback.message.edit_text(
            get_text("error_creating_payment_record"))
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    yookassa_metadata = {
        "user_id": str(user_id),
        "subscription_months": str(months),
        "payment_db_id": str(db_payment_record.payment_id),
    }
    receipt_email_for_yk = settings.YOOKASSA_DEFAULT_RECEIPT_EMAIL

    payment_response_yk = await yookassa_service.create_payment(
        amount=price_rub,
        currency=currency_code_for_yk,
        description=payment_description,
        metadata=yookassa_metadata,
        receipt_email=receipt_email_for_yk,
        save_payment_method=True)

    if payment_response_yk and payment_response_yk.get("confirmation_url"):
        # If YooKassa already provided a payment_method (rare on redirect), store it
        pm = payment_response_yk.get("payment_method")
        try:
            if pm and pm.get('id'):
                await user_billing_dal.upsert_yk_payment_method(
                    session,
                    user_id=user_id,
                    payment_method_id=pm['id'],
                    card_last4=pm.get('last4'),
                    card_network=pm.get('card', {}).get('card_type') if isinstance(pm.get('card'), dict) else None,
                )
                await session.commit()
        except Exception:
            await session.rollback()
            logging.exception("Failed to save YooKassa payment method preliminarily")
        try:
            await payment_dal.update_payment_status_by_db_id(
                session,
                payment_db_id=db_payment_record.payment_id,
                new_status=payment_response_yk.get("status", "pending"),
                yk_payment_id=payment_response_yk.get("id"))
            await session.commit()
        except Exception as e_db_update_ykid:
            await session.rollback()
            logging.error(
                f"Failed to update payment record {db_payment_record.payment_id} with YK ID: {e_db_update_ykid}",
                exc_info=True)
            await callback.message.edit_text(
                get_text("error_payment_gateway_link_failed"))
            try:
                await callback.answer(get_text("error_try_again"), show_alert=True)
            except Exception:
                pass
            return

        await callback.message.edit_text(
            get_text(key="payment_link_message", months=months),
            reply_markup=get_payment_url_keyboard(
                payment_response_yk["confirmation_url"], current_lang, i18n),
            disable_web_page_preview=False)
    else:
        try:
            await payment_dal.update_payment_status_by_db_id(
                session, db_payment_record.payment_id, "failed_creation")
            await session.commit()
        except Exception as e_db_fail_create:
            await session.rollback()
            logging.error(
                f"Additionally failed to update payment record to 'failed_creation': {e_db_fail_create}",
                exc_info=True)

        logging.error(
            f"Failed to create payment in YooKassa for user {user_id}, payment_db_id {db_payment_record.payment_id}. Response: {payment_response_yk}"
        )
        await callback.message.edit_text(get_text("error_payment_gateway"))

    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay_crypto:"))
async def pay_crypto_callback_handler(
        callback: types.CallbackQuery, settings: Settings, i18n_data: dict,
        cryptopay_service: CryptoPayService, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"), show_alert=True)
        except Exception:
            pass
        return

    if not cryptopay_service or not cryptopay_service.configured:
        await callback.message.edit_text(get_text("payment_service_unavailable"))
        try:
            await callback.answer(get_text("payment_service_unavailable_alert"), show_alert=True)
        except Exception:
            pass
        return

    try:
        _, data_payload = callback.data.split(":", 1)
        months_str, amount_str = data_payload.split(":")
        months = int(months_str)
        amount_val = float(amount_str)
    except (ValueError, IndexError):
        logging.error(f"Invalid pay_crypto data in callback: {callback.data}")
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    user_id = callback.from_user.id
    description = get_text("payment_description_subscription", months=months)

    invoice_url = await cryptopay_service.create_invoice(
        session, user_id, months, amount_val, description)
    if invoice_url:
        await callback.message.edit_text(
            get_text("payment_link_message", months=months),
            reply_markup=get_payment_url_keyboard(invoice_url, current_lang, i18n),
            disable_web_page_preview=False,
        )
    else:
        await callback.message.edit_text(get_text("error_payment_gateway"))
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data == "main_action:subscribe")
async def reshow_subscription_options_callback(callback: types.CallbackQuery,
                                               i18n_data: dict,
                                               settings: Settings,
                                               session: AsyncSession):
    await display_subscription_options(callback, i18n_data, settings, session)


async def my_subscription_command_handler(
    event: Union[types.Message, types.CallbackQuery],
    i18n_data: dict,
    settings: Settings,
    panel_service: PanelApiService,
    subscription_service: SubscriptionService,
    session: AsyncSession,
    bot: Bot
):
    target = event.message if isinstance(event, types.CallbackQuery) else event
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: JsonI18n = i18n_data.get("i18n_instance")
    get_text = lambda key, **kw: i18n.gettext(current_lang, key, **kw)

    if not i18n or not target:
        if isinstance(event, types.Message):
            await event.answer(get_text("error_occurred_try_again"))
        return

    if not panel_service or not subscription_service:
        await target.answer(get_text("error_service_unavailable"))
        return

    active = await subscription_service.get_active_subscription_details(session, event.from_user.id)

    if not active:
        text = get_text("subscription_not_active")

        buy_button = InlineKeyboardButton(
            text=get_text("menu_subscribe_inline", default="Купить"),
            callback_data="main_action:subscribe"
        )
        back_markup = get_back_to_main_menu_markup(current_lang, i18n)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [buy_button],
                *back_markup.inline_keyboard
            ]
        )

        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer()
            except Exception:
                pass
            try:
                await event.message.edit_text(text, reply_markup=kb)
            except:
                await event.message.answer(text, reply_markup=kb)
        else:
            await event.answer(text, reply_markup=kb)
        return

    end_date = active.get("end_date")
    days_left = (
        (end_date.date() - datetime.now().date()).days
        if end_date else 0
    )
    # Auto-renew toggle hint and Tribute notice
    tribute_hint = ""
    if active.get("status_from_panel", "").lower() == "active":
        # Try to infer provider; fetch local sub for flags
        # NOTE: Lightweight lookup by user_id
        local_sub = await subscription_dal.get_active_subscription_by_user_id(session, event.from_user.id)
        auto_renew_state = None
        if local_sub:
            auto_renew_state = local_sub.auto_renew_enabled
            if local_sub.provider == "tribute":
                link = None
                link = (settings.tribute_payment_links.get(local_sub.duration_months or 1)
                        if hasattr(settings, 'tribute_payment_links') else None)
                if link:
                    tribute_hint = "\n\n" + get_text("subscription_tribute_notice_with_link", link=link)
                else:
                    tribute_hint = "\n\n" + get_text("subscription_tribute_notice")

    text = get_text(
        "my_subscription_details",
        end_date=end_date.strftime("%Y-%m-%d") if end_date else "N/A",
        days_left=max(0, days_left),
        status=active.get("status_from_panel", get_text("status_active")).capitalize(),
        config_link=active.get("config_link") or get_text("config_link_not_available"),
        traffic_limit=(
            f"{active['traffic_limit_bytes'] / 2**30:.2f} GB"
            if active.get("traffic_limit_bytes")
            else get_text("traffic_unlimited")
        ),
        traffic_used=(
            f"{active['traffic_used_bytes'] / 2**30:.2f} GB"
            if active.get("traffic_used_bytes") is not None
            else get_text("traffic_na")
        )
    )
    # Build markup with auto-renew toggle and payment methods if available
    base_markup = get_back_to_main_menu_markup(current_lang, i18n)
    kb = base_markup.inline_keyboard
    try:
        if 'local_sub' in locals() and local_sub and local_sub.provider != 'tribute':
            toggle_text = get_text("autorenew_disable_button") if local_sub.auto_renew_enabled else get_text("autorenew_enable_button")
            kb = [[InlineKeyboardButton(text=toggle_text, callback_data=f"toggle_autorenew:{local_sub.subscription_id}:{1 if not local_sub.auto_renew_enabled else 0}")]] + kb
        # Add payment methods manage entry point
        kb = [[InlineKeyboardButton(text=get_text("payment_methods_manage_button"), callback_data="pm:manage")]] + kb
    except Exception:
        pass
    markup = InlineKeyboardMarkup(inline_keyboard=kb)

    if isinstance(event, types.CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass
        try:
            await event.message.edit_text(text + tribute_hint, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
        except:
            await bot.send_message(chat_id=target.chat.id, text=text + tribute_hint, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await target.answer(text + tribute_hint, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data.startswith("toggle_autorenew:"))
async def toggle_autorenew_handler(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, session: AsyncSession, subscription_service: SubscriptionService, panel_service: PanelApiService, bot: Bot):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    try:
        _, payload = callback.data.split(":", 1)
        sub_id_str, enable_str = payload.split(":")
        sub_id = int(sub_id_str)
        enable = bool(int(enable_str))
    except Exception:
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    # Fetch subscription by ID directly
    sub = await session.get(Subscription, sub_id)
    if not sub or sub.user_id != callback.from_user.id:
        await callback.answer(get_text("error_try_again"), show_alert=True)
        return
    if sub.provider == 'tribute':
        await callback.answer(get_text("subscription_autorenew_not_supported_for_tribute"), show_alert=True)
        return

    await subscription_dal.update_subscription(session, sub.subscription_id, {"auto_renew_enabled": enable})
    await session.commit()

    try:
        await callback.answer(get_text("subscription_autorenew_updated"))
    except Exception:
        pass
    # Refresh panel info screen
    await my_subscription_command_handler(callback, i18n_data, settings, panel_service, subscription_service, session, bot)


@router.callback_query(F.data == "pm:manage")
async def payment_methods_manage(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    # New list view relies on multi-card; but keep has_card for legacy text
    billing = await user_billing_dal.get_user_billing(session, callback.from_user.id)
    has_card = bool(billing and billing.yookassa_payment_method_id)
    text = _("payment_methods_title")
    if not has_card:
        text += "\n\n" + _("payment_method_none")
    # Redirect users to the new paginated list
    await callback.message.edit_text(text, reply_markup=get_payment_methods_manage_keyboard(current_lang, i18n, has_card))
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data == "pm:bind")
async def payment_method_bind(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, session: AsyncSession, yookassa_service: YooKassaService):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    # Create a minimal binding payment (1 RUB) with save_payment_method
    metadata = {
        "user_id": str(callback.from_user.id),
        "bind_only": "1",
    }
    resp = await yookassa_service.create_payment(
        amount=1.00,
        currency="RUB",
        description="Bind card",
        metadata=metadata,
        receipt_email=settings.YOOKASSA_DEFAULT_RECEIPT_EMAIL,
        save_payment_method=True,
        capture=False,
        bind_only=True,
    )
    if not resp or not resp.get("confirmation_url"):
        await callback.answer(_("error_payment_gateway"), show_alert=True)
        return
    await callback.message.edit_text(_("payment_methods_title"), reply_markup=get_bind_url_keyboard(resp["confirmation_url"], current_lang, i18n))
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pm:delete_confirm"))
async def payment_method_delete_confirm(callback: types.CallbackQuery, settings: Settings, i18n_data: dict):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key
    pm_id = callback.data.split(":", 1)[-1] if ":" in callback.data else ""
    await callback.message.edit_text(_("payment_method_delete_confirm"), reply_markup=get_payment_method_delete_confirm_keyboard(pm_id, current_lang, i18n))
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pm:delete"))
async def payment_method_delete(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key
    # Single-card storage: ignore pm_id for now but retain for future multi-card
    deleted = await user_billing_dal.delete_yk_payment_method(session, callback.from_user.id)
    await session.commit()
    msg = _("payment_method_deleted_success") if deleted else _("error_try_again")
    await callback.message.edit_text(msg, reply_markup=get_payment_methods_manage_keyboard(current_lang, i18n, has_card=False))
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pm:view"))
async def payment_method_view(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    billing = await user_billing_dal.get_user_billing(session, callback.from_user.id)
    if not billing or not billing.yookassa_payment_method_id:
        # Try multi-card records
        from db.dal.user_billing_dal import list_user_payment_methods
        methods = await list_user_payment_methods(session, callback.from_user.id)
        if not methods:
            await callback.answer(_("payment_method_none"), show_alert=True)
            return
        pm_id = callback.data.split(":", 1)[-1] if ":" in callback.data else str(methods[0].method_id)
        # Map:
        sel = next((m for m in methods if str(m.method_id) == pm_id or m.provider_payment_method_id == pm_id), methods[0])
        title = _("payment_method_card_title", network=sel.card_network or "Card", last4=sel.card_last4 or "????")
        added_at = sel.created_at.strftime('%Y-%m-%d') if getattr(sel, 'created_at', None) else "—"
        # Last tx
        last_tx = "—"
        try:
            stmt = (
                select(Payment)
                .where(
                    Payment.user_id == callback.from_user.id,
                    Payment.status == 'succeeded',
                    Payment.provider == 'yookassa',
                )
                .order_by(Payment.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            lp = result.scalar_one_or_none()
            if lp and lp.created_at:
                last_tx = lp.created_at.strftime('%Y-%m-%d')
        except Exception:
            pass
        details = f"{title}\n{_('payment_method_added_at', date=added_at)}\n{_('payment_method_last_tx', date=last_tx)}"
        await callback.message.edit_text(details, reply_markup=get_payment_method_details_keyboard(str(sel.method_id), current_lang, i18n))
        try:
            await callback.answer()
        except Exception:
            pass
        return
    added_at = billing.created_at.strftime('%Y-%m-%d') if getattr(billing, 'created_at', None) else "—"
    # Last transaction lookup (latest succeeded YooKassa payment by user)
    last_tx = "—"
    try:
        stmt = (
            select(Payment)
            .where(
                Payment.user_id == callback.from_user.id,
                Payment.status == 'succeeded',
                Payment.provider == 'yookassa',
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        last_payment = result.scalar_one_or_none()
        if last_payment and last_payment.created_at:
            last_tx = last_payment.created_at.strftime('%Y-%m-%d')
    except Exception:
        pass
    title = _("payment_method_card_title", network=billing.card_network or "Card", last4=billing.card_last4 or "????")
    details = f"{title}\n{_('payment_method_added_at', date=added_at)}\n{_('payment_method_last_tx', date=last_tx)}"
    await callback.message.edit_text(details, reply_markup=get_payment_method_details_keyboard(billing.yookassa_payment_method_id, current_lang, i18n))
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pm:history"))
async def payment_method_history(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    # Simple history from payments table filtered by user
    from db.dal import payment_dal
    payments = await payment_dal.get_recent_payment_logs_with_user(session, limit=10, offset=0)
    user_payments = [p for p in payments if p.user_id == callback.from_user.id]
    if not user_payments:
        await callback.message.edit_text(_("payment_method_no_history"), reply_markup=get_payment_methods_manage_keyboard(current_lang, i18n, has_card=True))
        return
    # Show subscription purchase titles instead of raw provider/status
    def _format_item(p):
        title = p.description or _("subscription_purchase_title", months=p.subscription_duration_months or 1)
        date_str = p.created_at.strftime('%Y-%m-%d') if p.created_at else "N/A"
        return f"{date_str} — {title} — {p.amount:.2f} {p.currency}"

    lines = [_format_item(p) for p in user_payments]
    text = _("payment_method_tx_history_title") + "\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=get_payment_methods_manage_keyboard(current_lang, i18n, has_card=True))


@router.callback_query(F.data.startswith("pm:list:"))
async def payment_methods_list(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    # For now we only support single saved YK method; format as list API-ready
    from db.dal.user_billing_dal import list_user_payment_methods
    cards: List[tuple] = []
    methods = await list_user_payment_methods(session, callback.from_user.id)
    for m in methods:
        title = get_text("payment_method_card_title", network=m.card_network or "Card", last4=m.card_last4 or "????")
        cards.append((str(m.method_id), title if not m.is_default else f"⭐ {title}"))

    # Parse page
    try:
        _, _, page_str = callback.data.split(":", 2)
        page = int(page_str)
    except Exception:
        page = 0

    text = get_text("payment_methods_title")
    if not cards:
        text += "\n\n" + get_text("payment_method_none")
    await callback.message.edit_text(text, reply_markup=get_payment_methods_list_keyboard(cards, page, current_lang, i18n))
    try:
        await callback.answer()
    except Exception:
        pass


@router.pre_checkout_query()
async def stars_pre_checkout_handler(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def stars_successful_payment_handler(
        message: types.Message, settings: Settings, i18n_data: dict,
        session: AsyncSession, stars_service: StarsService):
    sp = message.successful_payment
    if not sp or sp.currency != "XTR":
        return

    payload = sp.invoice_payload or ""
    try:
        payment_id_str, months_str = payload.split(":")
        payment_db_id = int(payment_id_str)
        months = int(months_str)
    except (ValueError, IndexError):
        logging.error(f"Invalid invoice payload for stars payment: {payload}")
        return

    stars_amount = sp.total_amount
    await stars_service.process_successful_payment(
        session, message, payment_db_id, months, stars_amount, i18n_data)


@router.message(Command("connect"))
async def connect_command_handler(message: types.Message, i18n_data: dict,
                                  settings: Settings,
                                  panel_service: PanelApiService,
                                  subscription_service: SubscriptionService,
                                  session: AsyncSession, bot: Bot):
    logging.info(f"User {message.from_user.id} used /connect command.")
    await my_subscription_command_handler(message, i18n_data, settings,
                                          panel_service, subscription_service,
                                          session, bot)
