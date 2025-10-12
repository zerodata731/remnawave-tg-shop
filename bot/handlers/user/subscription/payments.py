import logging
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from bot.keyboards.inline.user_keyboards import get_payment_method_keyboard, get_payment_url_keyboard
from bot.services.yookassa_service import YooKassaService
from bot.services.freekassa_service import FreeKassaService
from bot.services.crypto_pay_service import CryptoPayService
from bot.services.stars_service import StarsService
from bot.middlewares.i18n import JsonI18n
from db.dal import payment_dal, user_billing_dal

router = Router(name="user_subscription_payments_router")


@router.callback_query(F.data.startswith("subscribe_period:"))
async def select_subscription_period_callback_handler(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, session: AsyncSession):
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
        months = int(callback.data.split(":")[-1])
    except (ValueError, IndexError):
        logging.error(f"Invalid subscription period in callback_data: {callback.data}")
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
        await callback.message.edit_text(text_content, reply_markup=reply_markup)
    except Exception as e_edit:
        logging.warning(
            f"Edit message for payment method selection failed: {e_edit}. Sending new one."
        )
        await callback.message.answer(text_content, reply_markup=reply_markup)
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay_yk:"))
async def pay_yk_callback_handler(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, yookassa_service: YooKassaService, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"), show_alert=True)
        except Exception:
            pass
        return

    if not yookassa_service or not yookassa_service.configured:
        logging.error("YooKassa service is not configured or unavailable.")
        target_msg_edit = callback.message
        await target_msg_edit.edit_text(get_text("payment_service_unavailable"))
        try:
            await callback.answer(get_text("payment_service_unavailable_alert"), show_alert=True)
        except Exception:
            pass
        return

    try:
        _, data_payload = callback.data.split(":", 1)
        months_str, price_str = data_payload.split(":")
        months = int(months_str)
        price_rub = float(price_str)
    except (ValueError, IndexError):
        logging.error(f"Invalid pay_yk data in callback: {callback.data}")
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    user_id = callback.from_user.id
    payment_description = get_text("payment_description_subscription", months=months)
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
        db_payment_record = await payment_dal.create_payment_record(session, payment_record_data)
        await session.commit()
        logging.info(
            f"Payment record {db_payment_record.payment_id} created for user {user_id} with status 'pending_yookassa'."
        )
    except Exception as e_db_payment:
        await session.rollback()
        logging.error(
            f"Failed to create payment record in DB for user {user_id}: {e_db_payment}",
            exc_info=True,
        )
        await callback.message.edit_text(get_text("error_creating_payment_record"))
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    if not db_payment_record:
        await callback.message.edit_text(get_text("error_creating_payment_record"))
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
        # Save method only when autopayments are enabled
        save_payment_method=bool(getattr(settings, 'YOOKASSA_AUTOPAYMENTS_ENABLED', False)),
    )

    if payment_response_yk and payment_response_yk.get("confirmation_url"):
        pm = payment_response_yk.get("payment_method")
        try:
            if pm and pm.get("id"):
                pm_type = pm.get("type")
                title = pm.get("title")
                card = pm.get("card") or {}
                account_number = pm.get("account_number") or pm.get("account")
                if isinstance(card, dict) and (pm_type or "").lower() in {"bank_card", "bank-card", "card"}:
                    display_network = card.get("card_type") or title or "Card"
                    display_last4 = card.get("last4")
                elif (pm_type or "").lower() in {"yoo_money", "yoomoney", "yoo-money", "wallet"}:
                    display_network = "YooMoney"
                    display_last4 = (
                        account_number[-4:]
                        if isinstance(account_number, str) and len(account_number) >= 4
                        else None
                    )
                else:
                    display_network = title or (pm_type.upper() if pm_type else "Payment method")
                    display_last4 = None
                await user_billing_dal.upsert_yk_payment_method(
                    session,
                    user_id=user_id,
                    payment_method_id=pm["id"],
                    card_last4=display_last4,
                    card_network=display_network,
                )
                try:
                    await user_billing_dal.upsert_user_payment_method(
                        session,
                        user_id=user_id,
                        provider_payment_method_id=pm["id"],
                        provider="yookassa",
                        card_last4=display_last4,
                        card_network=display_network,
                        set_default=True,
                    )
                except Exception:
                    pass
                await session.commit()
        except Exception:
            await session.rollback()
            logging.exception("Failed to save YooKassa payment method preliminarily")
        try:
            await payment_dal.update_payment_status_by_db_id(
                session,
                payment_db_id=db_payment_record.payment_id,
                new_status=payment_response_yk.get("status", "pending"),
                yk_payment_id=payment_response_yk.get("id"),
            )
            await session.commit()
        except Exception as e_db_update_ykid:
            await session.rollback()
            logging.error(
                f"Failed to update payment record {db_payment_record.payment_id} with YK ID: {e_db_update_ykid}",
                exc_info=True,
            )
            await callback.message.edit_text(get_text("error_payment_gateway_link_failed"))
            try:
                await callback.answer(get_text("error_try_again"), show_alert=True)
            except Exception:
                pass
            return

        await callback.message.edit_text(
            get_text(key="payment_link_message", months=months),
            reply_markup=get_payment_url_keyboard(payment_response_yk["confirmation_url"], current_lang, i18n),
            disable_web_page_preview=False,
        )
    else:
        try:
            await payment_dal.update_payment_status_by_db_id(session, db_payment_record.payment_id, "failed_creation")
            await session.commit()
        except Exception as e_db_fail_create:
            await session.rollback()
            logging.error(
                f"Additionally failed to update payment record to 'failed_creation': {e_db_fail_create}",
                exc_info=True,
            )
        logging.error(
            f"Failed to create payment in YooKassa for user {user_id}, payment_db_id {db_payment_record.payment_id}. Response: {payment_response_yk}"
        )
        await callback.message.edit_text(get_text("error_payment_gateway"))

    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay_fk:"))
async def pay_fk_callback_handler(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    freekassa_service: FreeKassaService,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"), show_alert=True)
        except Exception:
            pass
        return

    if not freekassa_service or not freekassa_service.configured:
        logging.error("FreeKassa service is not configured or unavailable.")
        try:
            await callback.answer(get_text("payment_service_unavailable_alert"), show_alert=True)
        except Exception:
            pass
        try:
            await callback.message.edit_text(get_text("payment_service_unavailable"))
        except Exception:
            pass
        return

    try:
        _, data_payload = callback.data.split(":", 1)
        months_str, price_str = data_payload.split(":")
        months = int(months_str)
        price_rub = float(price_str)
    except (ValueError, IndexError):
        logging.error(f"Invalid pay_fk data in callback: {callback.data}")
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    user_id = callback.from_user.id
    payment_description = get_text("payment_description_subscription", months=months)
    currency_code = getattr(freekassa_service, "default_currency", None) or settings.DEFAULT_CURRENCY_SYMBOL or "RUB"

    payment_record_payload = {
        "user_id": user_id,
        "amount": price_rub,
        "currency": currency_code,
        "status": "pending_freekassa",
        "description": payment_description,
        "subscription_duration_months": months,
        "provider": "freekassa",
    }

    try:
        payment_record = await payment_dal.create_payment_record(session, payment_record_payload)
        await session.commit()
    except Exception as e_db_create:
        await session.rollback()
        logging.error(
            f"FreeKassa: failed to create payment record for user {user_id}: {e_db_create}",
            exc_info=True,
        )
        try:
            await callback.message.edit_text(get_text("error_creating_payment_record"))
        except Exception:
            pass
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    method_keyboard = InlineKeyboardBuilder()
    method_keyboard.button(
        text=get_text("freekassa_method_qr"),
        callback_data=f"pay_fk_method:{payment_record.payment_id}:44",
    )
    method_keyboard.button(
        text=get_text("freekassa_method_card"),
        callback_data=f"pay_fk_method:{payment_record.payment_id}:36",
    )
    method_keyboard.button(
        text=get_text("freekassa_method_sberpay"),
        callback_data=f"pay_fk_method:{payment_record.payment_id}:43",
    )
    method_keyboard.button(
        text=get_text("back_to_main_menu_button"),
        callback_data="main_action:subscribe",
    )
    method_keyboard.adjust(1)

    try:
        await callback.message.edit_text(
            get_text("freekassa_choose_method"),
            reply_markup=method_keyboard.as_markup(),
        )
    except Exception as e_edit:
        logging.warning(f"FreeKassa: failed to show method selector ({e_edit}), sending new message.")
        try:
            await callback.message.answer(
                get_text("freekassa_choose_method"),
                reply_markup=method_keyboard.as_markup(),
            )
        except Exception:
            pass
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay_fk_method:"))
async def pay_fk_method_callback_handler(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    freekassa_service: FreeKassaService,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"), show_alert=True)
        except Exception:
            pass
        return

    if not freekassa_service or not freekassa_service.configured:
        try:
            await callback.answer(get_text("payment_service_unavailable_alert"), show_alert=True)
        except Exception:
            pass
        try:
            await callback.message.edit_text(get_text("payment_service_unavailable"))
        except Exception:
            pass
        return

    try:
        _, payload = callback.data.split(":", 1)
        payment_id_str, method_code = payload.split(":")
        payment_id = int(payment_id_str)
    except (ValueError, IndexError):
        logging.error(f"FreeKassa: invalid method payload {callback.data}")
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    try:
        payment_record = await payment_dal.get_payment_by_db_id(session, payment_id)
    except Exception as e_db:
        logging.error(f"FreeKassa: failed to load payment {payment_id}: {e_db}")
        payment_record = None

    if not payment_record:
        try:
            await callback.answer(get_text("error_payment_gateway"), show_alert=True)
        except Exception:
            pass
        return

    if payment_record.user_id != callback.from_user.id:
        logging.warning(
            f"FreeKassa: user {callback.from_user.id} attempted to access payment {payment_id} owned by {payment_record.user_id}"
        )
        try:
            await callback.answer(get_text("error_payment_gateway"), show_alert=True)
        except Exception:
            pass
        return

    months = payment_record.subscription_duration_months or 1
    amount = float(payment_record.amount)

    try:
        method_code_int = int(method_code)
    except (TypeError, ValueError):
        logging.error(f"FreeKassa: invalid method code {method_code} for payment {payment_record.payment_id}")
        try:
            await callback.answer(get_text("error_payment_gateway"), show_alert=True)
        except Exception:
            pass
        return

    success, response_data = await freekassa_service.create_order(
        payment_db_id=payment_record.payment_id,
        user_id=payment_record.user_id,
        months=months,
        amount=amount,
        currency=settings.DEFAULT_CURRENCY_SYMBOL or "RUB",
        method_code=method_code_int,
        ip_address=freekassa_service.server_ip,
        extra_params={
            "us_method": method_code_int,
        },
    )

    if success:
        location = response_data.get("location")
        provider_identifier = response_data.get("orderHash") or response_data.get("orderId")

        if provider_identifier:
            try:
                await payment_dal.update_provider_payment_and_status(
                    session,
                    payment_record.payment_id,
                    str(provider_identifier),
                    payment_record.status,
                )
                await session.commit()
            except Exception as e_status:
                await session.rollback()
                logging.error(
                    f"FreeKassa: failed to store provider order id for payment {payment_record.payment_id}: {e_status}",
                    exc_info=True,
                )

        if location:
            try:
                await callback.message.edit_text(
                    get_text(key="payment_link_message", months=months),
                    reply_markup=get_payment_url_keyboard(location, current_lang, i18n),
                    disable_web_page_preview=False,
                )
            except Exception as e_edit:
                logging.warning(f"FreeKassa: failed to display payment link ({e_edit}), sending new message.")
                try:
                    await callback.message.answer(
                        get_text(key="payment_link_message", months=months),
                        reply_markup=get_payment_url_keyboard(location, current_lang, i18n),
                        disable_web_page_preview=False,
                    )
                except Exception:
                    pass
            try:
                await callback.answer()
            except Exception:
                pass
            return

        logging.error(
            "FreeKassa: create_order succeeded but no payment link returned for payment %s. Response: %s",
            payment_record.payment_id,
            response_data,
        )
    else:
        logging.error(
            "FreeKassa: create_order failed for payment %s with response %s",
            payment_record.payment_id,
            response_data,
        )

    try:
        await payment_dal.update_payment_status_by_db_id(
            session,
            payment_record.payment_id,
            "failed_creation",
        )
        await session.commit()
    except Exception as e_status:
        await session.rollback()
        logging.error(f"FreeKassa: failed to mark payment {payment_record.payment_id} as failed_creation: {e_status}", exc_info=True)

    try:
        await callback.message.edit_text(get_text("error_payment_gateway"))
    except Exception:
        pass
    try:
        await callback.answer(get_text("error_payment_gateway"), show_alert=True)
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay_crypto:"))
async def pay_crypto_callback_handler(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
    cryptopay_service: CryptoPayService,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = (lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key)

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"), show_alert=True)
        except Exception:
            pass
        return

    if not cryptopay_service or not getattr(cryptopay_service, "configured", False):
        try:
            await callback.answer(get_text("payment_service_unavailable_alert"), show_alert=True)
        except Exception:
            pass
        return

    try:
        _, data_payload = callback.data.split(":", 1)
        months_str, price_str = data_payload.split(":")
        months = int(months_str)
        price_amount = float(price_str)
    except (ValueError, IndexError):
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    user_id = callback.from_user.id
    payment_description = get_text("payment_description_subscription", months=months)

    invoice_url = await cryptopay_service.create_invoice(
        session=session,
        user_id=user_id,
        months=months,
        amount=price_amount,
        description=payment_description,
    )

    if invoice_url:
        try:
            await callback.message.edit_text(
                get_text(key="payment_link_message", months=months),
                reply_markup=get_payment_url_keyboard(invoice_url, current_lang, i18n),
                disable_web_page_preview=False,
            )
        except Exception:
            try:
                await callback.message.answer(
                    get_text(key="payment_link_message", months=months),
                    reply_markup=get_payment_url_keyboard(invoice_url, current_lang, i18n),
                    disable_web_page_preview=False,
                )
            except Exception:
                pass
        try:
            await callback.answer()
        except Exception:
            pass
        return

    try:
        await callback.answer(get_text("error_payment_gateway"), show_alert=True)
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay_stars:"))
async def pay_stars_callback_handler(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
    stars_service: StarsService,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = (lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key)

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"), show_alert=True)
        except Exception:
            pass
        return

    if not settings.STARS_ENABLED:
        try:
            await callback.answer(get_text("payment_service_unavailable_alert"), show_alert=True)
        except Exception:
            pass
        return

    try:
        _, data_payload = callback.data.split(":", 1)
        months_str, stars_price_str = data_payload.split(":")
        months = int(months_str)
        stars_price = int(stars_price_str)
    except (ValueError, IndexError):
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception:
            pass
        return

    user_id = callback.from_user.id
    payment_description = get_text("payment_description_subscription", months=months)

    payment_db_id = await stars_service.create_invoice(
        session=session,
        user_id=user_id,
        months=months,
        stars_price=stars_price,
        description=payment_description,
    )

    if payment_db_id:
        try:
            await callback.answer()
        except Exception:
            pass
        return

    try:
        await callback.answer(get_text("error_payment_gateway"), show_alert=True)
    except Exception:
        pass


@router.pre_checkout_query()
async def handle_pre_checkout_query(query: types.PreCheckoutQuery):
    try:
        await query.answer(ok=True)
    except Exception:
        # Nothing else to do here; Telegram will show an error if not answered
        pass


@router.message(F.successful_payment)
async def handle_successful_stars_payment(
    message: types.Message,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
    stars_service: StarsService,
):
    payload = (message.successful_payment.invoice_payload
               if message and message.successful_payment else "")
    try:
        payment_db_id_str, months_str = (payload or "").split(":", 1)
        payment_db_id = int(payment_db_id_str)
        months = int(months_str)
    except Exception:
        return

    stars_amount = int(message.successful_payment.total_amount) if message.successful_payment else 0
    await stars_service.process_successful_payment(
        session=session,
        message=message,
        payment_db_id=payment_db_id,
        months=months,
        stars_amount=stars_amount,
        i18n_data=i18n_data,
    )
