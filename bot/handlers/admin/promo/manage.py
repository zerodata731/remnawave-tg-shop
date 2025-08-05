import logging
from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from db.dal import promo_code_dal
from db.models import PromoCode, PromoCodeActivation
from bot.states.admin_states import AdminStates
from bot.keyboards.inline.admin_keyboards import get_back_to_admin_panel_keyboard, get_admin_panel_keyboard
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from bot.middlewares.i18n import JsonI18n

router = Router(name="promo_manage_router")


async def view_promo_codes_handler(callback: types.CallbackQuery,
                                   i18n_data: dict, settings: Settings,
                                   session: AsyncSession):
    """View all active promo codes"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error processing request.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        promo_models = await promo_code_dal.get_all_active_promo_codes(session,
                                                                       limit=20,
                                                                       offset=0)
        
        if not promo_models:
            text = _(
                "admin_no_promo_codes",
                default="📋 <b>Активные промокоды</b>\n\n❌ Нет активных промокодов"
            )
        else:
            lines = [_("admin_active_promo_codes_title",
                      default="📋 <b>Активные промокоды</b>\n")]
            
            for promo in promo_models:
                validity_str = _("admin_promo_unlimited", default="Без ограничений")
                if promo.valid_until:
                    validity_str = promo.valid_until.strftime("%d.%m.%Y")
                
                lines.append(
                    f"🎟 <code>{promo.code}</code> | "
                    f"🎁 {promo.bonus_days}д | "
                    f"📊 {promo.current_activations}/{promo.max_activations} | "
                    f"⏰ {validity_str}"
                )
            
            text = "\n".join(lines)
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
                parse_mode="HTML"
            )
        except Exception:
            await callback.message.answer(
                text,
                reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
                parse_mode="HTML"
            )
        await callback.answer()
        
    except Exception as e:
        logging.error(f"Error viewing promo codes: {e}")
        await callback.answer(_("error_occurred_try_again"), show_alert=True)


async def promo_management_handler(callback: types.CallbackQuery,
                                   i18n_data: dict, settings: Settings,
                                   session: AsyncSession):
    """Main promo management interface"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error processing request.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        promo_models = await promo_code_dal.get_all_promo_codes_with_details(session, limit=50, offset=0)
        
        if not promo_models:
            text = _(
                "admin_no_promo_codes_to_manage",
                default="🛠 <b>Управление промокодами</b>\n\n❌ Нет промокодов для управления"
            )
            await callback.message.edit_text(
                text,
                reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        builder = InlineKeyboardBuilder()
        text_lines = [_("admin_promo_management_title", default="🛠 <b>Управление промокодами</b>\n")]
        
        for promo in promo_models:
            status_emoji = "✅" if promo.is_active else "❌"
            validity_str = _("admin_promo_unlimited", default="∞")
            if promo.valid_until:
                validity_str = promo.valid_until.strftime("%d.%m")
            
            text_lines.append(
                f"{status_emoji} <code>{promo.code}</code> | "
                f"🎁{promo.bonus_days}д | "
                f"📊{promo.current_activations}/{promo.max_activations} | "
                f"⏰{validity_str}"
            )
            
            builder.row(
                InlineKeyboardButton(
                    text=f"📝 {promo.code}",
                    callback_data=f"promo_detail:{promo.promo_code_id}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(
                text=_("admin_back_to_panel", default="🔙 В админ панель"),
                callback_data="admin_action:main"
            )
        )
        
        text = "\n".join(text_lines)
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
        except Exception:
            await callback.message.answer(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
        await callback.answer()
        
    except Exception as e:
        logging.error(f"Error in promo management: {e}")
        await callback.answer(_("error_occurred_try_again"), show_alert=True)


@router.callback_query(F.data.startswith("promo_detail:"))
async def promo_detail_handler(callback: types.CallbackQuery,
                             i18n_data: dict, settings: Settings,
                             session: AsyncSession):
    """Show detailed promo code information with management options"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error processing request.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        promo_id = int(callback.data.split(":")[1])
        promo = await promo_code_dal.get_promo_code_by_id(session, promo_id)
        
        if not promo:
            await callback.answer(_("admin_promo_not_found", default="❌ Промокод не найден"), show_alert=True)
            return
        
        # Format promo details
        status_text = _("admin_promo_active", default="✅ Активен") if promo.is_active else _("admin_promo_inactive", default="❌ Неактивен")
        validity_text = _("admin_promo_unlimited", default="Без ограничений")
        if promo.valid_until:
            if promo.valid_until > datetime.now(timezone.utc):
                validity_text = promo.valid_until.strftime("%d.%m.%Y %H:%M")
            else:
                validity_text = f"{promo.valid_until.strftime('%d.%m.%Y %H:%M')} (истек)"
        
        created_at = promo.created_at.strftime("%d.%m.%Y %H:%M") if promo.created_at else "N/A"
        
        text = _(
            "admin_promo_detail_info",
            default="🎟 <b>Детали промокода</b>\n\n"
                   "📝 Код: <code>{code}</code>\n"
                   "🎁 Бонусные дни: <b>{bonus_days}</b>\n"
                   "📊 Использований: <b>{current}/{max}</b>\n"
                   "📋 Статус: {status}\n"
                   "⏰ Действует до: <b>{validity}</b>\n"
                   "👤 Создал: <code>{admin_id}</code>\n"
                   "🕐 Создан: <b>{created}</b>",
            code=promo.code,
            bonus_days=promo.bonus_days,
            current=promo.current_activations,
            max=promo.max_activations,
            status=status_text,
            validity=validity_text,
            admin_id=promo.created_by_admin_id,
            created=created_at
        )
        
        # Create management buttons
        builder = InlineKeyboardBuilder()
        
        # Edit button
        builder.row(
            InlineKeyboardButton(
                text=_("admin_promo_edit", default="✏️ Редактировать"),
                callback_data=f"promo_edit:{promo_id}"
            )
        )
        
        # Toggle active/inactive
        toggle_text = _("admin_promo_deactivate", default="❌ Деактивировать") if promo.is_active else _("admin_promo_activate", default="✅ Активировать")
        builder.row(
            InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"promo_toggle:{promo_id}"
            )
        )
        
        # View activations
        builder.row(
            InlineKeyboardButton(
                text=_("admin_promo_view_activations", default="📋 Активации"),
                callback_data=f"promo_activations:{promo_id}"
            )
        )
        
        # Delete button
        builder.row(
            InlineKeyboardButton(
                text=_("admin_promo_delete", default="🗑 Удалить"),
                callback_data=f"promo_delete:{promo_id}"
            )
        )
        
        # Back button
        builder.row(
            InlineKeyboardButton(
                text=_("admin_back_to_management", default="🔙 К управлению"),
                callback_data="admin_action:promo_management"
            )
        )
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
        except Exception:
            await callback.message.answer(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
        await callback.answer()
        
    except ValueError:
        await callback.answer(_("admin_invalid_promo_id", default="❌ Неверный ID промокода"), show_alert=True)
    except Exception as e:
        logging.error(f"Error in promo detail: {e}")
        await callback.answer(_("error_occurred_try_again"), show_alert=True)


@router.callback_query(F.data.startswith("promo_toggle:"))
async def promo_toggle_handler(callback: types.CallbackQuery, i18n_data: dict,
                               settings: Settings, session: AsyncSession):
    """Toggle promo code active status"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await callback.answer("Language service error.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        promo_id = int(callback.data.split(":")[1])
        promo = await promo_code_dal.get_promo_code_by_id(session, promo_id)
        
        if not promo:
            await callback.answer(_("admin_promo_not_found", default="❌ Промокод не найден"), show_alert=True)
            return
        
        new_status = not promo.is_active
        update_data = {"is_active": new_status}
        
        updated = await promo_code_dal.update_promo_code(session, promo_id, update_data)
        if updated:
            await session.commit()
            status_text = _("admin_promo_activated", default="активирован") if new_status else _("admin_promo_deactivated", default="деактивирован")
            await callback.answer(
                _("admin_promo_status_changed", default="✅ Промокод {status}", status=status_text)
            )
            # Refresh the detail view
            callback.data = f"promo_detail:{promo_id}"
            await promo_detail_handler(callback, i18n_data, settings, session)
        else:
            await callback.answer(_("error_occurred_try_again"), show_alert=True)
            
    except ValueError:
        await callback.answer(_("admin_invalid_promo_id", default="❌ Неверный ID промокода"), show_alert=True)
    except Exception as e:
        logging.error(f"Error toggling promo: {e}")
        await callback.answer(_("error_occurred_try_again"), show_alert=True)


@router.callback_query(F.data.startswith("promo_activations:"))
async def promo_activations_handler(callback: types.CallbackQuery, i18n_data: dict,
                                    settings: Settings, session: AsyncSession):
    """Show promo code activations"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error processing request.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        promo_id = int(callback.data.split(":")[1])
        promo = await promo_code_dal.get_promo_code_by_id(session, promo_id)
        
        if not promo:
            await callback.answer(_("admin_promo_not_found", default="❌ Промокод не найден"), show_alert=True)
            return
        
        activations = await promo_code_dal.get_promo_activations_by_code_id(session, promo_id)
        
        text_lines = [
            _("admin_promo_activations_title",
              default="📋 <b>Активации промокода {code}</b>\n",
              code=promo.code)
        ]
        
        if not activations:
            text_lines.append(_("admin_no_activations", default="❌ Нет активаций"))
        else:
            for activation in activations[:10]:  # Show last 10
                activated_at = activation.activated_at.strftime("%d.%m.%Y %H:%M") if activation.activated_at else "N/A"
                text_lines.append(
                    f"👤 <code>{activation.user_id}</code> | 🕐 {activated_at}"
                )
            
            if len(activations) > 10:
                text_lines.append(f"\n... и еще {len(activations) - 10}")
        
        text = "\n".join(text_lines)
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text=_("admin_back_to_promo", default="🔙 К промокоду"),
                callback_data=f"promo_detail:{promo_id}"
            )
        )
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
        except Exception:
            await callback.message.answer(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
        await callback.answer()
        
    except ValueError:
        await callback.answer(_("admin_invalid_promo_id", default="❌ Неверный ID промокода"), show_alert=True)
    except Exception as e:
        logging.error(f"Error viewing activations: {e}")
        await callback.answer(_("error_occurred_try_again"), show_alert=True)


@router.callback_query(F.data.startswith("promo_delete:"))
async def promo_delete_handler(callback: types.CallbackQuery, i18n_data: dict,
                               settings: Settings, session: AsyncSession):
    """Delete promo code"""
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await callback.answer("Language service error.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        promo_id = int(callback.data.split(":")[1])
        promo = await promo_code_dal.delete_promo_code(session, promo_id)
        
        if promo:
            await session.commit()
            await callback.answer(
                _("admin_promo_deleted", default="✅ Промокод удален", code=promo.code)
            )
            # Go back to management
            callback.data = "admin_action:promo_management"
            await promo_management_handler(callback, i18n_data, settings, session)
        else:
            await callback.answer(_("admin_promo_not_found", default="❌ Промокод не найден"), show_alert=True)
            
    except ValueError:
        await callback.answer(_("admin_invalid_promo_id", default="❌ Неверный ID промокода"), show_alert=True)
    except Exception as e:
        logging.error(f"Error deleting promo: {e}")
        await callback.answer(_("error_occurred_try_again"), show_alert=True)


# Legacy handlers that redirect to new system
async def manage_promo_codes_handler(callback: types.CallbackQuery,
                                     i18n_data: dict, settings: Settings,
                                     session: AsyncSession):
    """Redirect to new unified handler"""
    await promo_management_handler(callback, i18n_data, settings, session)