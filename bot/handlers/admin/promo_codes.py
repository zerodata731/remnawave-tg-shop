import logging
import random
import string
from aiogram import Router, F, types, Bot
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings

from db.dal import promo_code_dal

from bot.states.admin_states import AdminStates
from bot.keyboards.inline.admin_keyboards import get_back_to_admin_panel_keyboard, get_admin_panel_keyboard
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_promo_codes_router")


async def create_promo_prompt_handler(callback: types.CallbackQuery,
                                      state: FSMContext, i18n_data: dict,
                                      settings: Settings,
                                      session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error preparing promo creation.",
                              show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    # Step 1: Ask for promo code
    prompt_text = _(
        "admin_promo_step1_code",
        default="🎟 <b>Создание промокода</b>\n\n<b>Шаг 1 из 4:</b> Код промокода\n\nВведите код промокода (3-30 символов, только буквы и цифры):"
    )

    try:
        await callback.message.edit_text(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    except Exception as e:
        logging.warning(
            f"Could not edit message for promo prompt: {e}. Sending new.")
        await callback.message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    await callback.answer()
    await state.set_state(AdminStates.waiting_for_promo_code)


# Step 1: Process promo code
@router.message(AdminStates.waiting_for_promo_code, F.text)
async def process_promo_code_handler(message: types.Message,
                                    state: FSMContext,
                                    i18n_data: dict,
                                    settings: Settings,
                                    session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        code_str = message.text.strip().upper()
        if not (3 <= len(code_str) <= 30 and code_str.isalnum()):
            await message.answer(_(
                "admin_promo_invalid_code_format",
                default="❌ Код промокода должен содержать 3-30 символов (только буквы и цифры)"
            ))
            return
        
        # Check if code already exists
        existing_promo = await promo_code_dal.get_promo_code_by_code(session, code_str)
        if existing_promo:
            await message.answer(_(
                "admin_promo_code_already_exists",
                default="❌ Промокод с таким кодом уже существует"
            ))
            return
        
        await state.update_data(promo_code=code_str)
        
        # Step 2: Ask for bonus days
        prompt_text = _(
            "admin_promo_step2_bonus_days",
            default="🎟 <b>Создание промокода</b>\n\n<b>Шаг 2 из 4:</b> Бонусные дни\n\nКод: <b>{code}</b>\n\nВведите количество бонусных дней (1-365):",
            code=code_str
        )
        
        await message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_for_promo_bonus_days)
        
    except Exception as e:
        logging.error(f"Error processing promo code: {e}")
        await message.answer(_(
            "admin_promo_processing_error",
            default="❌ Ошибка обработки промокода"
        ))

# Step 2: Process bonus days
@router.message(AdminStates.waiting_for_promo_bonus_days, F.text)
async def process_promo_bonus_days_handler(message: types.Message,
                                          state: FSMContext,
                                          i18n_data: dict,
                                          settings: Settings):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        bonus_days = int(message.text.strip())
        if bonus_days <= 0 or bonus_days > 365:
            await message.answer(_(
                "admin_promo_invalid_bonus_days",
                default="❌ Бонусные дни должны быть от 1 до 365"
            ))
            return
        
        data = await state.get_data()
        await state.update_data(bonus_days=bonus_days)
        
        # Step 3: Ask for max activations
        prompt_text = _(
            "admin_promo_step3_max_activations",
            default="🎟 <b>Создание промокода</b>\n\n<b>Шаг 3 из 4:</b> Максимальные активации\n\nКод: <b>{code}</b>\nБонусные дни: <b>{bonus_days}</b>\n\nВведите максимальное количество активаций (1-10000):",
            code=data['promo_code'],
            bonus_days=bonus_days
        )
        
        await message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_for_promo_max_activations)
        
    except ValueError:
        await message.answer(_(
            "admin_promo_invalid_bonus_days",
            default="❌ Бонусные дни должны быть от 1 до 365"
        ))

# Step 3: Process max activations
@router.message(AdminStates.waiting_for_promo_max_activations, F.text)
async def process_promo_max_activations_handler(message: types.Message,
                                               state: FSMContext,
                                               i18n_data: dict,
                                               settings: Settings):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        max_activations = int(message.text.strip())
        if max_activations <= 0 or max_activations > 10000:
            await message.answer(_(
                "admin_promo_invalid_max_activations",
                default="❌ Максимальные активации должны быть от 1 до 10000"
            ))
            return
        
        data = await state.get_data()
        await state.update_data(max_activations=max_activations)
        
        # Step 4: Ask for validity days (with buttons)
        keyboard = InlineKeyboardBuilder()
        keyboard.row(
            InlineKeyboardButton(
                text=_("admin_promo_unlimited_validity", default="♾️ Неограниченно"),
                callback_data="promo_unlimited_validity"
            )
        )
        keyboard.row(
            InlineKeyboardButton(
                text=_("admin_promo_set_validity", default="⏰ Установить срок"),
                callback_data="promo_set_validity"
            )
        )
        keyboard.row(
            InlineKeyboardButton(
                text=_("admin_panel_back_button", default="⬅️ Назад"),
                callback_data="admin_panel_back"
            )
        )
        
        prompt_text = _(
            "admin_promo_step4_validity",
            default="🎟 <b>Создание промокода</b>\n\n<b>Шаг 4 из 4:</b> Срок действия\n\nКод: <b>{code}</b>\nБонусные дни: <b>{bonus_days}</b>\nМакс. активации: <b>{max_activations}</b>\n\nВыберите срок действия промокода:",
            code=data['promo_code'],
            bonus_days=data['bonus_days'],
            max_activations=max_activations
        )
        
        await message.answer(
            prompt_text,
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_for_promo_validity_days)
        
    except ValueError:
        await message.answer(_(
            "admin_promo_invalid_max_activations",
            default="❌ Максимальные активации должны быть от 1 до 10000"
        ))

# Handle validity choice buttons
@router.callback_query(F.data == "promo_unlimited_validity", StateFilter(AdminStates.waiting_for_promo_validity_days))
async def process_promo_unlimited_validity(callback: types.CallbackQuery,
                                          state: FSMContext,
                                          i18n_data: dict,
                                          settings: Settings,
                                          session: AsyncSession):
    await state.update_data(validity_days=None)
    await create_promo_code_final(callback, state, i18n_data, settings, session)

@router.callback_query(F.data == "promo_set_validity", StateFilter(AdminStates.waiting_for_promo_validity_days))
async def process_promo_set_validity(callback: types.CallbackQuery,
                                    state: FSMContext,
                                    i18n_data: dict,
                                    settings: Settings):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await callback.answer("Language service error.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    prompt_text = _(
        "admin_promo_enter_validity_days",
        default="⏰ Введите количество дней действия промокода (1-365):"
    )
    
    try:
        await callback.message.edit_text(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n)
        )
    except Exception as e:
        await callback.message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n)
        )
    await callback.answer()

# Step 4: Process validity days (when user chooses to set)
@router.message(AdminStates.waiting_for_promo_validity_days, F.text)
async def process_promo_validity_days_handler(message: types.Message,
                                             state: FSMContext,
                                             i18n_data: dict,
                                             settings: Settings,
                                             session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        validity_days = int(message.text.strip())
        if validity_days <= 0 or validity_days > 365:
            await message.answer(_(
                "admin_promo_invalid_validity_days",
                default="❌ Дни действия должны быть от 1 до 365"
            ))
            return
        
        await state.update_data(validity_days=validity_days)
        
        # Create a fake callback for consistency
        fake_callback = types.CallbackQuery(
            id="fake",
            from_user=message.from_user,
            chat_instance="fake",
            message=message,
            data="fake"
        )
        
        await create_promo_code_final(fake_callback, state, i18n_data, settings, session)
        
    except ValueError:
        await message.answer(_(
            "admin_promo_invalid_validity_days",
            default="❌ Дни действия должны быть от 1 до 365"
        ))

# Description handlers removed - not needed for this model

async def create_promo_code_final(callback_or_message,
                                 state: FSMContext,
                                 i18n_data: dict,
                                 settings: Settings,
                                 session: AsyncSession):
    """Final step to create the promo code"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        if hasattr(callback_or_message, 'answer'):
            await callback_or_message.answer("Language service error.", show_alert=True)
        else:
            await callback_or_message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    data = await state.get_data()
    promo_code = data['promo_code']
    bonus_days = data['bonus_days']
    max_activations = data['max_activations']
    validity_days = data.get('validity_days')
    
    # Create validity date
    valid_until_date: Optional[datetime] = None
    valid_until_str_display = _("admin_promo_valid_indefinitely", default="Неограниченно")
    
    if validity_days:
        valid_until_date = datetime.now(timezone.utc) + timedelta(days=validity_days)
        valid_until_str_display = valid_until_date.strftime('%Y-%m-%d')

    # Show creating message
    creating_text = _(
        "admin_promo_creating",
        default="⏳ Создаю промокод..."
    )
    
    if hasattr(callback_or_message, 'message'):
        try:
            await callback_or_message.message.edit_text(creating_text)
        except:
            await callback_or_message.message.answer(creating_text)
        if hasattr(callback_or_message, 'answer'):
            await callback_or_message.answer()
    else:
        await callback_or_message.answer(creating_text)

    # Create promo code
    try:
        promo_data = {
            "code": promo_code,
            "bonus_days": bonus_days,
            "max_activations": max_activations,
            "current_activations": 0,
            "is_active": True,
            "valid_until": valid_until_date,
            "created_by_admin_id": callback_or_message.from_user.id if hasattr(callback_or_message, 'from_user') and callback_or_message.from_user else 0
        }
        
        await promo_code_dal.create_promo_code(session, promo_data)
        await session.commit()
        
        # Send success message
        success_text = _(
            "admin_promo_created_success",
            default="✅ Промокод создан!\n\n🎟 Код: <b>{code}</b>\n🎁 Бонусные дни: <b>{days}</b>\n🔢 Максимальные активации: <b>{max_act}</b>\n⏰ Действует до: <b>{validity}</b>",
            code=promo_code,
            days=bonus_days,
            max_act=max_activations,
            validity=valid_until_str_display
        )
        
        if hasattr(callback_or_message, 'message'):
            target_message = callback_or_message.message
        else:
            target_message = callback_or_message
            
        await target_message.answer(
            success_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logging.error(f"Error creating promo code: {e}")
        await session.rollback()
        error_text = _(
            "admin_promo_creation_failed",
            default="❌ Ошибка создания промокода: {error}",
            error=str(e)
        )
        
        if hasattr(callback_or_message, 'message'):
            target_message = callback_or_message.message
        else:
            target_message = callback_or_message
            
        await target_message.answer(
            error_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n)
        )
    
    await state.clear()

# Legacy handler removed - using step-by-step creation now


async def view_promo_codes_handler(callback: types.CallbackQuery,
                                   i18n_data: dict, settings: Settings,
                                   session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error displaying promo codes.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    promo_models = await promo_code_dal.get_all_active_promo_codes(session,
                                                                   limit=20,
                                                                   offset=0)

    if not promo_models:
        await callback.message.edit_text(
            _("admin_no_active_promos"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
        await callback.answer()
        return

    response_text_parts = [f"<b>{_('admin_active_promos_list_header')}</b>\n"]
    for promo in promo_models:
        valid_until_display_text = _("admin_promo_valid_indefinitely")
        if promo.valid_until:

            valid_until_display_text = promo.valid_until.strftime('%Y-%m-%d')

        response_text_parts.append(
            _("admin_promo_list_item",
              code=promo.code,
              bonus=promo.bonus_days,
              current=promo.current_activations,
              max=promo.max_activations,
              valid_until=valid_until_display_text))

    final_text = "\n".join(response_text_parts)
    try:
        await callback.message.edit_text(
            final_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    except Exception as e:
        logging.warning(
            f"Failed to edit message for promo list: {e}. Sending new.")
        if callback.message:
            await callback.message.answer(
                final_text,
                reply_markup=get_back_to_admin_panel_keyboard(
                    current_lang, i18n),
                parse_mode="HTML")
    await callback.answer()


# New unified promo management system
@router.callback_query(F.data == "admin_action:promo_management")
async def promo_management_handler(callback: types.CallbackQuery,
                                 i18n_data: dict, settings: Settings,
                                 session: AsyncSession):
    """Show list of all promo codes for management"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error displaying promo codes.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    # Get ALL promo codes (including inactive)
    promo_models = await promo_code_dal.get_all_promo_codes_with_details(session, limit=50, offset=0)
    if not promo_models:
        await callback.message.edit_text(
            _("admin_promo_management_empty", default="📭 Промокоды отсутствуют"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for promo in promo_models:
        # Show promo code with status indicator
        status_emoji = "✅" if promo.is_active else "🚫"
        if promo.valid_until and promo.valid_until < datetime.now(timezone.utc):
            status_emoji = "⏰"  # Expired
        elif promo.current_activations >= promo.max_activations:
            status_emoji = "🔄"  # Used up
            
        button_text = f"{status_emoji} {promo.code} ({promo.current_activations}/{promo.max_activations})"
        kb.row(
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"promo_detail:{promo.promo_code_id}")
        )
    
    kb.row(
        InlineKeyboardButton(text=_("back_to_admin_panel_button", default="⬅️ Назад"),
                             callback_data="admin_action:main"))

    await callback.message.edit_text(
        _("admin_promo_management_title", default="🎟 <b>Управление промокодами</b>\n\nВыберите промокод для детального просмотра:"),
        reply_markup=kb.as_markup(),
        parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("promo_detail:"))
async def promo_detail_handler(callback: types.CallbackQuery,
                             i18n_data: dict, settings: Settings,
                             session: AsyncSession):
    """Show detailed promo code information with management options"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error displaying promo details.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    promo_id = int(callback.data.split(":")[1])
    promo = await promo_code_dal.get_promo_code_by_id(session, promo_id)
    if not promo:
        await callback.answer(_("admin_promo_not_found", default="Промокод не найден"), show_alert=True)
        return

    # Determine status
    status = _("admin_promo_status_active", default="✅ Активен")
    if not promo.is_active:
        status = _("admin_promo_status_inactive", default="🚫 Неактивен")
    elif promo.valid_until and promo.valid_until < datetime.now(timezone.utc):
        status = _("admin_promo_status_expired", default="⏰ Истек")
    elif promo.current_activations >= promo.max_activations:
        status = _("admin_promo_status_used_up", default="🔄 Исчерпан")

    # Format validity
    validity = _("admin_promo_valid_indefinitely", default="Неограниченно")
    if promo.valid_until:
        validity = promo.valid_until.strftime('%Y-%m-%d %H:%M')

    # Format created date
    created_date = promo.created_at.strftime('%Y-%m-%d %H:%M') if promo.created_at else "N/A"
    creator = f"Admin {promo.created_by_admin_id}" if promo.created_by_admin_id else "N/A"

    # Build card text
    card_text = _(
        "admin_promo_card_title",
        default="🎟 <b>Промокод: {code}</b>",
        code=promo.code
    ) + "\n\n"
    
    card_text += _(
        "admin_promo_card_bonus_days",
        default="🎁 Бонусные дни: <b>{days}</b>",
        days=promo.bonus_days
    ) + "\n"
    
    card_text += _(
        "admin_promo_card_activations", 
        default="🔢 Активации: <b>{current}/{max}</b>",
        current=promo.current_activations,
        max=promo.max_activations
    ) + "\n"
    
    card_text += _(
        "admin_promo_card_validity",
        default="⏰ Действует до: <b>{validity}</b>",
        validity=validity
    ) + "\n"
    
    card_text += _(
        "admin_promo_card_status",
        default="📊 Статус: <b>{status}</b>",
        status=status
    ) + "\n"
    
    card_text += _(
        "admin_promo_card_created",
        default="📅 Создан: <b>{created}</b>",
        created=created_date
    ) + "\n"
    
    card_text += _(
        "admin_promo_card_created_by",
        default="👤 Создал: <b>{creator}</b>",
        creator=creator
    )

    # Build keyboard
    kb = InlineKeyboardBuilder()
    
    # Row 1: Edit and Toggle status
    kb.row(
        InlineKeyboardButton(
            text=_("admin_promo_edit_button", default="✏️ Редактировать"),
            callback_data=f"promo_edit:{promo_id}"),
        InlineKeyboardButton(
            text=_("admin_promo_toggle_status_button", default="🔄 Вкл/Выкл"),
            callback_data=f"promo_toggle:{promo_id}")
    )
    
    # Row 2: View activations and Delete
    kb.row(
        InlineKeyboardButton(
            text=_("admin_promo_view_activations_button", default="📋 Активации"),
            callback_data=f"promo_activations:{promo_id}"),
        InlineKeyboardButton(
            text=_("admin_promo_delete_button", default="🗑 Удалить"),
            callback_data=f"promo_delete:{promo_id}")
    )
    
    # Row 3: Back to list
    kb.row(
        InlineKeyboardButton(
            text=_("admin_promo_back_to_list_button", default="⬅️ К списку"),
            callback_data="admin_action:promo_management")
    )

    await callback.message.edit_text(
        card_text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML")
    await callback.answer()


# Legacy manage_promo_codes_handler - keeping for compatibility
@router.callback_query(F.data == "admin_action:manage_promos")
async def manage_promo_codes_handler(callback: types.CallbackQuery,
                                     i18n_data: dict, settings: Settings,
                                     session: AsyncSession):
    # Redirect to new unified handler
    await promo_management_handler(callback, i18n_data, settings, session)


@router.callback_query(F.data.startswith("promo_edit:"))
async def promo_edit_select_handler(callback: types.CallbackQuery, state: FSMContext,
                                    i18n_data: dict, settings: Settings,
                                    session: AsyncSession):
    promo_id = int(callback.data.split(":")[1])
    promo = await promo_code_dal.get_promo_code_by_id(session, promo_id)
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not promo or not callback.message:
        await callback.answer("Error", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    await state.update_data(edit_promo_id=promo_id)
    await state.set_state(AdminStates.waiting_for_promo_edit_details)
    await callback.message.edit_text(
        _("admin_promo_edit_prompt", code=promo.code),
        reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
        parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.waiting_for_promo_edit_details, F.text)
async def process_promo_edit_details(message: types.Message, state: FSMContext,
                                     i18n_data: dict, settings: Settings,
                                     session: AsyncSession):
    data = await state.get_data()
    promo_id = data.get("edit_promo_id")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not promo_id:
        await message.answer("Error")
        await state.clear()
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    parts = message.text.strip().split()
    if not (3 <= len(parts) <= 4):
        await message.answer(_("admin_promo_invalid_format"))
        return
    try:
        code_str = parts[0].upper()
        bonus = int(parts[1])
        max_act = int(parts[2])
        valid_until = None
        if len(parts) == 4:
            days = int(parts[3])
            valid_until = datetime.now(timezone.utc) + timedelta(days=days)
    except Exception:
        await message.answer(_("admin_promo_invalid_format_general"))
        return

    update_data = {
        "code": code_str,
        "bonus_days": bonus,
        "max_activations": max_act,
        "valid_until": valid_until,
    }
    updated = await promo_code_dal.update_promo_code(session, promo_id, update_data)
    if updated:
        await session.commit()
        await message.answer(
            _("admin_promo_updated_success", code=code_str),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML",
        )
    else:
        await session.rollback()
        await message.answer(_("admin_promo_not_found"))
    await state.clear()


@router.callback_query(F.data.startswith("promo_delete:"))
async def promo_delete_handler(callback: types.CallbackQuery, i18n_data: dict,
                               settings: Settings, session: AsyncSession):
    promo_id = int(callback.data.split(":")[1])
    promo = await promo_code_dal.delete_promo_code(session, promo_id)
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    if promo:
        await session.commit()
        await callback.message.edit_text(
            _("admin_promo_deleted_success", code=promo.code),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    else:
        await session.rollback()
        await callback.message.edit_text(
            _("admin_promo_not_found"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
    await callback.answer()


@router.callback_query(
    F.data == "admin_action:main",
    StateFilter(
        AdminStates.waiting_for_promo_details,
        AdminStates.waiting_for_promo_code,
        AdminStates.waiting_for_promo_bonus_days,
        AdminStates.waiting_for_promo_max_activations,
        AdminStates.waiting_for_promo_validity_days,
        AdminStates.waiting_for_promo_edit_details,
        AdminStates.waiting_for_bulk_promo_quantity,
        AdminStates.waiting_for_bulk_promo_bonus_days,
        AdminStates.waiting_for_bulk_promo_max_activations,
        AdminStates.waiting_for_bulk_promo_validity_days,
    ),
)
async def cancel_promo_creation_state_to_menu(callback: types.CallbackQuery,
                                              state: FSMContext,
                                              settings: Settings,
                                              i18n_data: dict,
                                              session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error cancelling.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        await callback.message.edit_text(_("admin_action_cancelled_default"),
                                         reply_markup=get_admin_panel_keyboard(
                                             i18n, current_lang, settings))
    except Exception:
        await callback.message.answer(_("admin_action_cancelled_default"),
                                      reply_markup=get_admin_panel_keyboard(
                                          i18n, current_lang, settings))

    await callback.answer(_("admin_action_cancelled_default_alert"))
    await state.clear()


async def create_bulk_promo_prompt_handler(callback: types.CallbackQuery,
                                          state: FSMContext, i18n_data: dict,
                                          settings: Settings,
                                          session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error preparing bulk promo creation.",
                              show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    # Step 1: Ask for quantity
    prompt_text = _(
        "admin_bulk_promo_step1_quantity",
        default="📦 <b>Массовое создание промокодов</b>\n\n<b>Шаг 1 из 4:</b> Количество промокодов\n\nВведите количество промокодов для создания (1-1000):"
    )

    try:
        await callback.message.edit_text(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    except Exception as e:
        logging.warning(
            f"Could not edit message for bulk promo prompt: {e}. Sending new.")
        await callback.message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    await callback.answer()
    await state.set_state(AdminStates.waiting_for_bulk_promo_quantity)


def generate_unique_promo_code(length: int = 8) -> str:
    """Generate a unique promotional code"""
    characters = string.ascii_uppercase + string.digits
    # Exclude confusing characters
    characters = characters.replace('0', '').replace('O', '').replace('1', '').replace('I', '').replace('L', '')
    return ''.join(random.choice(characters) for _ in range(length))


# Step 1: Process quantity
@router.message(AdminStates.waiting_for_bulk_promo_quantity, F.text)
async def process_bulk_promo_quantity_handler(message: types.Message,
                                             state: FSMContext,
                                             i18n_data: dict,
                                             settings: Settings):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        quantity = int(message.text.strip())
        if quantity <= 0 or quantity > 1000:
            await message.answer(_(
                "admin_bulk_promo_invalid_quantity",
                default="❌ Количество должно быть от 1 до 1000"
            ))
            return
        
        await state.update_data(quantity=quantity)
        
        # Step 2: Ask for bonus days
        prompt_text = _(
            "admin_bulk_promo_step2_bonus_days",
            default="📦 <b>Массовое создание промокодов</b>\n\n<b>Шаг 2 из 4:</b> Бонусные дни\n\nКоличество: <b>{quantity}</b>\n\nВведите количество бонусных дней (1-365):",
            quantity=quantity
        )
        
        await message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_for_bulk_promo_bonus_days)
        
    except ValueError:
        await message.answer(_(
            "admin_bulk_promo_invalid_quantity",
            default="❌ Количество должно быть от 1 до 1000"
        ))

# Step 2: Process bonus days
@router.message(AdminStates.waiting_for_bulk_promo_bonus_days, F.text)
async def process_bulk_promo_bonus_days_handler(message: types.Message,
                                               state: FSMContext,
                                               i18n_data: dict,
                                               settings: Settings):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        bonus_days = int(message.text.strip())
        if bonus_days <= 0 or bonus_days > 365:
            await message.answer(_(
                "admin_bulk_promo_invalid_bonus_days", 
                default="❌ Бонусные дни должны быть от 1 до 365"
            ))
            return
        
        data = await state.get_data()
        await state.update_data(bonus_days=bonus_days)
        
        # Step 3: Ask for max activations
        prompt_text = _(
            "admin_bulk_promo_step3_max_activations",
            default="📦 <b>Массовое создание промокодов</b>\n\n<b>Шаг 3 из 4:</b> Максимальные активации\n\nКоличество: <b>{quantity}</b>\nБонусные дни: <b>{bonus_days}</b>\n\nВведите максимальное количество активаций для каждого промокода (1-10000):",
            quantity=data['quantity'],
            bonus_days=bonus_days
        )
        
        await message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_for_bulk_promo_max_activations)
        
    except ValueError:
        await message.answer(_(
            "admin_bulk_promo_invalid_bonus_days",
            default="❌ Бонусные дни должны быть от 1 до 365"
        ))

# Step 3: Process max activations
@router.message(AdminStates.waiting_for_bulk_promo_max_activations, F.text)
async def process_bulk_promo_max_activations_handler(message: types.Message,
                                                    state: FSMContext,
                                                    i18n_data: dict,
                                                    settings: Settings):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        max_activations = int(message.text.strip())
        if max_activations <= 0 or max_activations > 10000:
            await message.answer(_(
                "admin_bulk_promo_invalid_max_activations",
                default="❌ Максимальные активации должны быть от 1 до 10000"
            ))
            return
        
        data = await state.get_data()
        await state.update_data(max_activations=max_activations)
        
        # Step 4: Ask for validity days (optional)
        keyboard = InlineKeyboardBuilder()
        keyboard.row(
            InlineKeyboardButton(
                text=_("admin_bulk_promo_unlimited_validity", default="♾️ Неограниченно"),
                callback_data="bulk_promo_unlimited_validity"
            )
        )
        keyboard.row(
            InlineKeyboardButton(
                text=_("admin_bulk_promo_set_validity", default="⏰ Установить срок"),
                callback_data="bulk_promo_set_validity"
            )
        )
        keyboard.row(
            InlineKeyboardButton(
                text=_("admin_panel_back_button", default="⬅️ Назад"),
                callback_data="admin_panel_back"
            )
        )
        
        prompt_text = _(
            "admin_bulk_promo_step4_validity",
            default="📦 <b>Массовое создание промокодов</b>\n\n<b>Шаг 4 из 4:</b> Срок действия\n\nКоличество: <b>{quantity}</b>\nБонусные дни: <b>{bonus_days}</b>\nМакс. активации: <b>{max_activations}</b>\n\nВыберите срок действия промокодов:",
            quantity=data['quantity'],
            bonus_days=data['bonus_days'],
            max_activations=max_activations
        )
        
        await message.answer(
            prompt_text,
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_for_bulk_promo_validity_days)
        
    except ValueError:
        await message.answer(_(
            "admin_bulk_promo_invalid_max_activations",
            default="❌ Максимальные активации должны быть от 1 до 10000"
        ))

# Handle validity choice buttons
@router.callback_query(F.data == "bulk_promo_unlimited_validity", StateFilter(AdminStates.waiting_for_bulk_promo_validity_days))
async def process_bulk_promo_unlimited_validity(callback: types.CallbackQuery,
                                               state: FSMContext,
                                               i18n_data: dict,
                                               settings: Settings,
                                               session: AsyncSession):
    await state.update_data(validity_days=None)
    await create_bulk_promo_codes_final(callback, state, i18n_data, settings, session)

@router.callback_query(F.data == "bulk_promo_set_validity", StateFilter(AdminStates.waiting_for_bulk_promo_validity_days))
async def process_bulk_promo_set_validity(callback: types.CallbackQuery,
                                         state: FSMContext,
                                         i18n_data: dict,
                                         settings: Settings):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await callback.answer("Language service error.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    prompt_text = _(
        "admin_bulk_promo_enter_validity_days",
        default="⏰ Введите количество дней действия промокодов (1-365):"
    )
    
    try:
        await callback.message.edit_text(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n)
        )
    except Exception as e:
        await callback.message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n)
        )
    await callback.answer()

# Step 4: Process validity days (when user chooses to set)
@router.message(AdminStates.waiting_for_bulk_promo_validity_days, F.text)
async def process_bulk_promo_validity_days_handler(message: types.Message,
                                                  state: FSMContext,
                                                  i18n_data: dict,
                                                  settings: Settings,
                                                  session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        validity_days = int(message.text.strip())
        if validity_days <= 0 or validity_days > 365:
            await message.answer(_(
                "admin_bulk_promo_invalid_validity_days",
                default="❌ Дни действия должны быть от 1 до 365"
            ))
            return
        
        await state.update_data(validity_days=validity_days)
        
        # Create a fake callback for consistency
        fake_callback = types.CallbackQuery(
            id="fake",
            from_user=message.from_user,
            chat_instance="fake",
            message=message,
            data="fake"
        )
        
        await create_bulk_promo_codes_final(fake_callback, state, i18n_data, settings, session)
        
    except ValueError:
        await message.answer(_(
            "admin_bulk_promo_invalid_validity_days",
            default="❌ Дни действия должны быть от 1 до 365"
        ))

async def create_bulk_promo_codes_final(callback_or_message,
                                       state: FSMContext,
                                       i18n_data: dict,
                                       settings: Settings,
                                       session: AsyncSession):
    """Final step to create all promo codes"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        if hasattr(callback_or_message, 'answer'):
            await callback_or_message.answer("Language service error.", show_alert=True)
        else:
            await callback_or_message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    data = await state.get_data()
    quantity = data['quantity']
    bonus_days = data['bonus_days']
    max_activations = data['max_activations']
    validity_days = data.get('validity_days')
    
    # Create validity date
    valid_until_date: Optional[datetime] = None
    valid_until_str_display = _("admin_promo_valid_indefinitely", default="Неограниченно")
    
    if validity_days:
        valid_until_date = datetime.now(timezone.utc) + timedelta(days=validity_days)
        valid_until_str_display = valid_until_date.strftime('%Y-%m-%d')

    # Show creating message
    creating_text = _(
        "admin_bulk_promo_creating",
        default="⏳ Создаю {quantity} промокодов...",
        quantity=quantity
    )
    
    if hasattr(callback_or_message, 'message'):
        try:
            await callback_or_message.message.edit_text(creating_text)
        except:
            await callback_or_message.message.answer(creating_text)
        if hasattr(callback_or_message, 'answer'):
            await callback_or_message.answer()
    else:
        await callback_or_message.answer(creating_text)

    # Generate and create promo codes
    created_codes = []
    try:
        for i in range(quantity):
            # Generate unique code
            promo_code = generate_unique_promo_code()
            
            # Ensure uniqueness
            existing_promo = await promo_code_dal.get_promo_code_by_code(session, promo_code)
            retries = 0
            while existing_promo and retries < 10:
                promo_code = generate_unique_promo_code()
                existing_promo = await promo_code_dal.get_promo_code_by_code(session, promo_code)
                retries += 1
            
            if retries >= 10:
                raise Exception("Не удалось создать уникальный промокод")
            
            # Create promo code
            promo_data = {
                "code": promo_code,
                "bonus_days": bonus_days,
                "max_activations": max_activations,
                "current_activations": 0,
                "is_active": True,
                "valid_until": valid_until_date,
                "created_by_admin_id": callback_or_message.from_user.id if hasattr(callback_or_message, 'from_user') and callback_or_message.from_user else 0
            }
            
            await promo_code_dal.create_promo_code(session, promo_data)
            created_codes.append(promo_code)
        
        await session.commit()
        
        # Send success message
        success_text = _(
            "admin_bulk_promo_created_success",
            default="✅ Создано {count} промокодов на {days} дней!\n\nДействуют до: {validity}\nМакс. активации: {max_act}",
            count=quantity,
            days=bonus_days,
            validity=valid_until_str_display,
            max_act=max_activations
        )
        
        if hasattr(callback_or_message, 'message'):
            target_message = callback_or_message.message
        else:
            target_message = callback_or_message
            
        await target_message.answer(
            success_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML"
        )
        
        # Always send codes as file
        codes_file_content = "\n".join(created_codes)
        codes_file = types.BufferedInputFile(
            codes_file_content.encode('utf-8'),
            filename=f"bulk_promo_codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        
        await target_message.answer_document(
            codes_file,
            caption=_(
                "admin_bulk_promo_codes_file",
                default="📄 Все созданные промокоды в файле ({count} шт.)",
                count=quantity
            )
        )
        
    except Exception as e:
        logging.error(f"Error creating bulk promo codes: {e}")
        await session.rollback()
        error_text = _(
            "admin_bulk_promo_creation_failed",
            default="❌ Ошибка создания промокодов: {error}",
            error=str(e)
        )
        
        if hasattr(callback_or_message, 'message'):
            target_message = callback_or_message.message
        else:
            target_message = callback_or_message
            
        await target_message.answer(
            error_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n)
        )
    
    await state.clear()

# Old bulk promo handler removed - now using step-by-step process



