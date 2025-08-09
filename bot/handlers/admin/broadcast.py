import logging
import asyncio
from aiogram import Router, F, types, Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

from aiogram.fsm.context import FSMContext
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings

from db.dal import user_dal, message_log_dal

from bot.states.admin_states import AdminStates
from bot.keyboards.inline.admin_keyboards import (
    get_broadcast_confirmation_keyboard,
    get_back_to_admin_panel_keyboard,
    get_admin_panel_keyboard,
)
from bot.middlewares.i18n import JsonI18n
from bot.utils.message_queue import get_queue_manager

router = Router(name="admin_broadcast_router")


async def broadcast_message_prompt_handler(
    callback: types.CallbackQuery,
    state: FSMContext,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in broadcast_message_prompt_handler")
        await callback.answer("Language service error.", show_alert=True)
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    prompt_text = _("admin_broadcast_enter_message")

    if callback.message:
        try:
            await callback.message.edit_text(
                prompt_text,
                reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            )
        except Exception as e:
            logging.warning(
                f"Could not edit message for broadcast prompt: {e}. Sending new."
            )
            await callback.message.answer(
                prompt_text,
                reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            )
    await callback.answer()
    await state.set_state(AdminStates.waiting_for_broadcast_message)


@router.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast_message_handler(
    message: types.Message,
    state: FSMContext,
    i18n_data: dict,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in process_broadcast_message_handler")
        await message.reply("Language service error.")
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    # Сохраняем в state исходный текст и entities
    text = (message.text or message.caption or "").strip()
    entities = message.entities or message.caption_entities or []

    # Если текст пустой (например, прислали стикер/фото без подписи) — просим ввести текст
    if not text:
        await message.answer(_("admin_broadcast_error_no_message"))
        return

    # Предварительная проверка HTML: попробуем отправить и сразу удалить
    # Если HTML некорректный, Telegram вернёт ошибку парсинга
    try:
        test_msg = await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            disable_notification=True,
        )
        # Удалим тестовое сообщение
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=test_msg.message_id)
        except Exception:
            pass
    except TelegramBadRequest as e:
        await message.answer(
            _(
                "admin_broadcast_invalid_html",
                default="❌ Некорректный HTML в сообщении. Пожалуйста, отправьте корректный HTML (поддерживаются теги Telegram) или уберите теги.\nОшибка: {error}",
                error=str(e),
            )
        )
        return

    await state.update_data(
        broadcast_text=text,
        broadcast_entities=entities,
    )

    confirmation_prompt = _("admin_broadcast_confirm_prompt", message_preview=text)

    await message.answer(
        confirmation_prompt,
        reply_markup=get_broadcast_confirmation_keyboard(current_lang, i18n),
    )
    await state.set_state(AdminStates.confirming_broadcast)


@router.callback_query(
    F.data == "admin_action:main", AdminStates.waiting_for_broadcast_message
)
async def cancel_broadcast_at_prompt_stage(
    callback: types.CallbackQuery,
    state: FSMContext,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error cancelling.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        await callback.message.edit_text(
            _("admin_broadcast_cancelled_nav_back"), reply_markup=None
        )
    except Exception:
        await callback.message.answer(_("admin_broadcast_cancelled_nav_back"))

    await callback.answer(_("admin_broadcast_cancelled_alert"))
    await state.clear()

    await callback.message.answer(
        _(key="admin_panel_title"),
        reply_markup=get_admin_panel_keyboard(i18n, current_lang, settings),
    )


@router.callback_query(
    F.data.startswith("broadcast_final_action:"),
    AdminStates.confirming_broadcast,
)
async def confirm_broadcast_callback_handler(
    callback: types.CallbackQuery,
    state: FSMContext,
    i18n_data: dict,
    bot: Bot,
    settings: Settings,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error processing broadcast confirmation.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    action = callback.data.split(":")[1]
    user_fsm_data = await state.get_data()

    if action == "send":
        text = user_fsm_data.get("broadcast_text")
        entities = user_fsm_data.get("broadcast_entities", [])

        if not text:
            await callback.message.edit_text(_("admin_broadcast_error_no_message"))
            await state.clear()
            await callback.answer(
                _("admin_broadcast_error_no_message_alert"), show_alert=True
            )
            return

        await callback.message.edit_text(_("admin_broadcast_sending_started"), reply_markup=None)
        await callback.answer()

        user_ids = await user_dal.get_all_active_user_ids_for_broadcast(session)

        sent_count = 0
        failed_count = 0
        admin_user = callback.from_user
        logging.info(
            f"Admin {admin_user.id} broadcasting '{text[:50]}...' to {len(user_ids)} users."
        )

        # Get message queue manager
        queue_manager = get_queue_manager()
        if not queue_manager:
            await callback.message.edit_text("❌ Ошибка: система очередей не инициализирована", reply_markup=None)
            return

        # Queue all messages for sending
        for uid in user_ids:
            try:
                await queue_manager.send_message(
                    chat_id=uid,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                sent_count += 1
                
                # Log successful queuing
                await message_log_dal.create_message_log(
                    session,
                    {
                        "user_id": admin_user.id,
                        "telegram_username": admin_user.username,
                        "telegram_first_name": admin_user.first_name,
                        "event_type": "admin_broadcast_queued",
                        "content": f"To user {uid}: {text[:70]}...",
                        "is_admin_event": True,
                        "target_user_id": uid,
                    },
                )
            except Exception as e:
                failed_count += 1
                logging.warning(
                    f"Failed to queue broadcast to {uid}: {type(e).__name__} – {e}"
                )
                await message_log_dal.create_message_log(
                    session,
                    {
                        "user_id": admin_user.id,
                        "telegram_username": admin_user.username,
                        "telegram_first_name": admin_user.first_name,
                        "event_type": "admin_broadcast_failed",
                        "content": f"For user {uid}: {type(e).__name__} – {str(e)[:70]}...",
                        "is_admin_event": True,
                        "target_user_id": uid,
                    },
                )

        try:
            await session.commit()
        except Exception as e_commit:
            await session.rollback()
            logging.error(f"Error committing broadcast logs: {e_commit}")

        # Get queue stats for detailed report
        queue_stats = queue_manager.get_queue_stats()
        
        result_message = f"""🚀 Рассылка поставлена в очередь!
📤 В очередь добавлено: {sent_count}
❌ Ошибок: {failed_count}

📊 Статус очередей:
👥 Очередь пользователей: {queue_stats['user_queue_size']} сообщений
📢 Очередь групп: {queue_stats['group_queue_size']} сообщений

ℹ️ Сообщения будут отправлены автоматически с соблюдением лимитов Telegram."""
        await callback.message.answer(
            result_message,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
        )

    elif action == "cancel":
        await callback.message.edit_text(
            _("admin_broadcast_cancelled"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
        )
        await callback.answer()

    await state.clear()
