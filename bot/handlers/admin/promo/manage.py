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
            text = f"{_('admin_active_promos_list_header')}\n\n{_('admin_no_active_promos')}"
        else:
            lines = [_("admin_active_promos_list_header"), ""]
            
            for promo in promo_models:
                validity_str = _("admin_promo_valid_indefinitely")
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
            text = _("admin_promo_management_empty")
            await callback.message.edit_text(
                text,
                reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        builder = InlineKeyboardBuilder()
        text = _("admin_promo_management_title")
        
        for promo in promo_models:
            builder.row(
                InlineKeyboardButton(
                    text=f"📝 {promo.code}",
                    callback_data=f"promo_detail:{promo.promo_code_id}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(
                text=_("back_to_admin_panel_button"),
                callback_data="admin_action:main"
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
            await callback.answer(_("admin_promo_not_found"), show_alert=True)
            return
        
        status = _("admin_promo_status_active") if promo.is_active else _("admin_promo_status_inactive")
        if promo.valid_until and promo.valid_until < datetime.now(timezone.utc):
            status = _("admin_promo_status_expired")
        elif promo.current_activations >= promo.max_activations:
            status = _("admin_promo_status_used_up")

        validity = _("admin_promo_valid_indefinitely")
        if promo.valid_until:
            validity = promo.valid_until.strftime("%d.%m.%Y %H:%M")
        
        created = promo.created_at.strftime("%d.%m.%Y %H:%M") if promo.created_at else "N/A"
        
        text = "\n".join([
            _("admin_promo_card_title", code=promo.code),
            _("admin_promo_card_bonus_days", days=promo.bonus_days),
            _("admin_promo_card_activations", current=promo.current_activations, max=promo.max_activations),
            _("admin_promo_card_validity", validity=validity),
            _("admin_promo_card_status", status=status),
            _("admin_promo_card_created", created=created),
            _("admin_promo_card_created_by", creator=promo.created_by_admin_id)
        ])
        
        # Create management buttons
        builder = InlineKeyboardBuilder()
        
        builder.row(
            InlineKeyboardButton(
                text=_("admin_promo_edit_button"),
                callback_data=f"promo_edit:{promo_id}"
            )
        )
        
        builder.row(
            InlineKeyboardButton(
                text=_("admin_promo_toggle_status_button"),
                callback_data=f"promo_toggle:{promo_id}"
            )
        )
        
        builder.row(
            InlineKeyboardButton(
                text=_("admin_promo_view_activations_button"),
                callback_data=f"promo_activations:{promo_id}"
            )
        )
        
        builder.row(
            InlineKeyboardButton(
                text=_("admin_promo_delete_button"),
                callback_data=f"promo_delete:{promo_id}"
            )
        )
        
        builder.row(
            InlineKeyboardButton(
                text=_("admin_promo_back_to_list_button"),
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
        await callback.answer(_("admin_promo_not_found"), show_alert=True)
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
            await callback.answer(_("admin_promo_not_found"), show_alert=True)
            return
        
        new_status = not promo.is_active
        update_data = {"is_active": new_status}
        
        updated = await promo_code_dal.update_promo_code(session, promo_id, update_data)
        if updated:
            await session.commit()
            status_text = _("admin_promo_status_activated") if new_status else _("admin_promo_status_deactivated")
            await callback.answer(
                _("admin_promo_toggle_success", code=promo.code, status=status_text)
            )
            # Refresh the detail view
            callback.data = f"promo_detail:{promo_id}"
            await promo_detail_handler(callback, i18n_data, settings, session)
        else:
            await callback.answer(_("error_occurred_try_again"), show_alert=True)
            
    except ValueError:
        await callback.answer(_("admin_promo_not_found"), show_alert=True)
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
            await callback.answer(_("admin_promo_not_found"), show_alert=True)
            return
        
        activations = await promo_code_dal.get_promo_activations_by_code_id(session, promo_id)
        
        if not activations:
            text = _("admin_promo_no_activations", code=promo.code)
        else:
            text_lines = [
                _("admin_promo_activations_header", code=promo.code)
            ]
            for activation in activations[:20]:
                text_lines.append(
                    _("admin_promo_activation_item",
                      user_id=activation.user_id,
                      date=activation.activated_at.strftime("%d.%m.%Y %H:%M"))
                )
            if len(activations) > 20:
                text_lines.append(f"\n... (еще {len(activations) - 20})")
            text = "\n".join(text_lines)
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text=_("admin_promo_back_to_detail_button"),
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
        await callback.answer(_("admin_promo_not_found"), show_alert=True)
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
                _("admin_promo_deleted_success", code=promo.code)
            )
            # Go back to management
            callback.data = "admin_action:promo_management"
            await promo_management_handler(callback, i18n_data, settings, session)
        else:
            await callback.answer(_("admin_promo_not_found"), show_alert=True)
            
    except ValueError:
        await callback.answer(_("admin_promo_not_found"), show_alert=True)
    except Exception as e:
        logging.error(f"Error deleting promo: {e}")
        await callback.answer(_("error_occurred_try_again"), show_alert=True)


# Legacy handlers that redirect to new system
async def manage_promo_codes_handler(callback: types.CallbackQuery,
                                     i18n_data: dict, settings: Settings,
                                     session: AsyncSession):
    """Redirect to new unified handler"""
    await promo_management_handler(callback, i18n_data, settings, session)
