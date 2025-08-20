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

    # Определяем тип содержимого и сохраняем данные в state
    text = (message.text or message.caption or "").strip()
    entities = message.entities or message.caption_entities or []

    content_type = "text"
    file_id = None

    if message.photo:
        content_type = "photo"
        # Берем самое большое фото
        file_id = message.photo[-1].file_id
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
    elif message.animation:
        content_type = "animation"
        file_id = message.animation.file_id
    elif message.document:
        content_type = "document"
        file_id = message.document.file_id
    elif message.audio:
        content_type = "audio"
        file_id = message.audio.file_id
    elif message.voice:
        content_type = "voice"
        file_id = message.voice.file_id
    elif message.sticker:
        content_type = "sticker"
        file_id = message.sticker.file_id
    elif message.video_note:
        content_type = "video_note"
        file_id = message.video_note.file_id

    # Если нет ни текста, ни медиа — ошибка
    if not text and not file_id:
        await message.answer(_("admin_broadcast_error_no_message"))
        return

    # Сохраняем данные для рассылки
    await state.update_data(
        broadcast_text=text,
        broadcast_entities=entities,
        broadcast_content_type=content_type,
        broadcast_file_id=file_id,
        broadcast_target="all",
    )

    # Отправляем превью-копию того, что будет разослано
    try:
        if content_type == "text":
            await bot.send_message(
                chat_id=message.chat.id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                disable_notification=True,
            )
        elif content_type == "photo":
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=file_id,
                caption=text or None,
                parse_mode="HTML",
                disable_notification=True,
            )
        elif content_type == "video":
            await bot.send_video(
                chat_id=message.chat.id,
                video=file_id,
                caption=text or None,
                parse_mode="HTML",
                disable_notification=True,
            )
        elif content_type == "animation":
            await bot.send_animation(
                chat_id=message.chat.id,
                animation=file_id,
                caption=text or None,
                parse_mode="HTML",
                disable_notification=True,
            )
        elif content_type == "document":
            await bot.send_document(
                chat_id=message.chat.id,
                document=file_id,
                caption=text or None,
                parse_mode="HTML",
                disable_notification=True,
            )
        elif content_type == "audio":
            await bot.send_audio(
                chat_id=message.chat.id,
                audio=file_id,
                caption=text or None,
                parse_mode="HTML",
                disable_notification=True,
            )
        elif content_type == "voice":
            await bot.send_voice(
                chat_id=message.chat.id,
                voice=file_id,
                caption=text or None,
                parse_mode="HTML",
                disable_notification=True,
            )
        elif content_type == "sticker":
            await bot.send_sticker(
                chat_id=message.chat.id,
                sticker=file_id,
                disable_notification=True,
            )
        elif content_type == "video_note":
            await bot.send_video_note(
                chat_id=message.chat.id,
                video_note=file_id,
                disable_notification=True,
            )
    except TelegramBadRequest as e:
        await message.answer(
            _(
                "admin_broadcast_invalid_html",
                default="❌ Некорректный HTML в сообщении. Пожалуйста, отправьте корректный HTML (поддерживаются теги Telegram) или уберите теги.\nОшибка: {error}",
                error=str(e),
            )
        )
        return

    # Показываем короткое подтверждение без дублирования текста — сообщение выше служит превью
    confirmation_prompt = _("admin_broadcast_confirm_prompt_short")

    await message.answer(
        confirmation_prompt,
        reply_markup=get_broadcast_confirmation_keyboard(current_lang, i18n, target="all"),
    )
    await state.set_state(AdminStates.confirming_broadcast)


@router.callback_query(
    F.data.startswith("broadcast_target:"),
    AdminStates.confirming_broadcast,
)
async def change_broadcast_target_handler(
    callback: types.CallbackQuery,
    state: FSMContext,
    i18n_data: dict,
    settings: Settings,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error updating selection.", show_alert=True)
        return

    new_target = callback.data.split(":")[1]
    if new_target not in {"all", "active", "inactive"}:
        await callback.answer("Unknown target.", show_alert=True)
        return

    await state.update_data(broadcast_target=new_target)
    user_fsm_data = await state.get_data()
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    confirmation_prompt = _(
        "admin_broadcast_confirm_prompt_short"
    )
    try:
        await callback.message.edit_text(
            confirmation_prompt,
            reply_markup=get_broadcast_confirmation_keyboard(
                current_lang, i18n, target=new_target
            ),
        )
    except Exception:
        pass
    await callback.answer()


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
        content_type = user_fsm_data.get("broadcast_content_type", "text")
        file_id = user_fsm_data.get("broadcast_file_id")
        if not text and content_type == "text":
            await callback.message.edit_text(_("admin_broadcast_error_no_message"))
            await state.clear()
            await callback.answer(
                _("admin_broadcast_error_no_message_alert"), show_alert=True
            )
            return

        await callback.message.edit_text(_("admin_broadcast_sending_started"), reply_markup=None)
        await callback.answer()

        target = user_fsm_data.get("broadcast_target", "all")
        if target == "active":
            user_ids = await user_dal.get_user_ids_with_active_subscription(session)
        elif target == "inactive":
            user_ids = await user_dal.get_user_ids_without_active_subscription(session)
        else:
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
                if content_type == "text":
                    await queue_manager.send_message(
                        chat_id=uid,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                elif content_type == "photo":
                    await queue_manager.send_photo(
                        chat_id=uid, photo=file_id, caption=text or None, parse_mode="HTML"
                    )
                elif content_type == "video":
                    await queue_manager.send_video(
                        chat_id=uid, video=file_id, caption=text or None, parse_mode="HTML"
                    )
                elif content_type == "animation":
                    await queue_manager.send_animation(
                        chat_id=uid, animation=file_id, caption=text or None, parse_mode="HTML"
                    )
                elif content_type == "document":
                    await queue_manager.send_document(
                        chat_id=uid, document=file_id, caption=text or None, parse_mode="HTML"
                    )
                elif content_type == "audio":
                    await queue_manager.send_audio(
                        chat_id=uid, audio=file_id, caption=text or None, parse_mode="HTML"
                    )
                elif content_type == "voice":
                    await queue_manager.send_voice(
                        chat_id=uid, voice=file_id, caption=text or None, parse_mode="HTML"
                    )
                elif content_type == "sticker":
                    await queue_manager.send_sticker(
                        chat_id=uid, sticker=file_id
                    )
                elif content_type == "video_note":
                    await queue_manager.send_video_note(
                        chat_id=uid, video_note=file_id
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
                        "content": f"To user {uid}: [{content_type}] {(text or '')[:70]}...",
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
