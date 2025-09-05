import logging
from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from bot.middlewares.i18n import JsonI18n
from db.dal import ad_dal
from bot.states.admin_states import AdminStates

router = Router(name="admin_ads_router")


@router.callback_query(F.data == "admin_action:ads")
async def show_ads_menu(callback: types.CallbackQuery, settings: Settings, i18n_data: dict, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if not i18n or not callback.message:
        await callback.answer("Language error.", show_alert=True)
        return

    campaigns = await ad_dal.list_campaigns(session)
    if not campaigns:
        text = _("admin_ads_empty")
    else:
        text_lines = [_("admin_ads_header")]
        for camp in campaigns:
            try:
                stats = await ad_dal.get_campaign_stats(session, camp.ad_campaign_id)
            except Exception as e_stats:
                logging.error(f"Failed to calc stats for campaign {camp.ad_campaign_id}: {e_stats}")
                stats = {"starts": 0, "trials": 0, "payers": 0, "revenue": 0.0}
            text_lines.append(
                _(
                    "admin_ads_item",
                    id=camp.ad_campaign_id,
                    source=camp.source,
                    start_param=camp.start_param,
                    cost=f"{camp.cost:.2f}",
                    active=_("csv_yes") if camp.is_active else _("csv_no"),
                    starts=stats["starts"],
                    trials=stats["trials"],
                    payers=stats["payers"],
                    revenue=f"{stats['revenue']:.2f}",
                )
            )
        text = "\n\n".join(text_lines)

    from bot.keyboards.inline.admin_keyboards import get_ads_menu_keyboard
    reply_markup = get_ads_menu_keyboard(i18n, current_lang)
    await callback.message.edit_text(text, reply_markup=reply_markup)
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data == "admin_action:ads_create")
async def ads_create_start(callback: types.CallbackQuery, state: FSMContext, settings: Settings, i18n_data: dict):
    from bot.states.admin_states import AdminStates
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if not i18n or not callback.message:
        await callback.answer("Language error.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_ad_source)
    await callback.message.edit_text(_("admin_ads_create_source_prompt"))
    try:
        await callback.answer()
    except Exception:
        pass


@router.message(
    StateFilter(
        AdminStates.waiting_for_ad_source,
        AdminStates.waiting_for_ad_start_param,
        AdminStates.waiting_for_ad_cost,
    ),
    F.text,
)
async def ads_create_flow(message: types.Message, state: FSMContext, settings: Settings, i18n_data: dict, session: AsyncSession):
    current_state = await state.get_state()
    if current_state not in (
        AdminStates.waiting_for_ad_source.state,
        AdminStates.waiting_for_ad_start_param.state,
        AdminStates.waiting_for_ad_cost.state,
    ):
        return

    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if current_state == AdminStates.waiting_for_ad_source.state:
        source = message.text.strip()
        if not source or len(source) > 64:
            await message.answer(_("admin_ads_invalid_source"))
            return
        await state.update_data(ad_source=source)
        await state.set_state(AdminStates.waiting_for_ad_start_param)
        await message.answer(_("admin_ads_create_start_param_prompt"))
        return

    if current_state == AdminStates.waiting_for_ad_start_param.state:
        start_param = message.text.strip()
        # Allow alnum underscore dash only
        import re as _re
        if not _re.match(r"^[A-Za-z0-9_\-]{2,64}$", start_param):
            await message.answer(_("admin_ads_invalid_start_param"))
            return
        await state.update_data(ad_start_param=start_param)
        await state.set_state(AdminStates.waiting_for_ad_cost)
        await message.answer(_("admin_ads_create_cost_prompt"))
        return

    if current_state == AdminStates.waiting_for_ad_cost.state:
        text = message.text.replace(",", ".").strip()
        try:
            cost = float(text)
            if cost < 0 or cost > 1e8:
                raise ValueError()
        except Exception:
            await message.answer(_("admin_ads_invalid_cost"))
            return

        data = await state.get_data()
        try:
            campaign = await ad_dal.create_campaign(
                session,
                source=data.get("ad_source", "unknown"),
                start_param=data.get("ad_start_param", "NA"),
                cost=cost,
            )
            await session.commit()
        except ValueError as ve:
            await session.rollback()
            if str(ve) == "ad_campaign_start_param_exists":
                await message.answer(_("admin_ads_start_param_exists"))
            else:
                await message.answer(_("error_occurred_try_again"))
            return
        except Exception as e:
            await session.rollback()
            logging.error(f"Failed to create ad campaign: {e}", exc_info=True)
            await message.answer(_("error_occurred_try_again"))
            return

        await state.clear()
        _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key
        await message.answer(
            _(
                "admin_ads_created_success",
                id=campaign.ad_campaign_id,
                source=campaign.source,
                start_param=campaign.start_param,
                cost=f"{campaign.cost:.2f}",
            )
        )
        # Offer back to ads menu
        from bot.keyboards.inline.admin_keyboards import get_ads_menu_keyboard
        await message.answer(_("admin_ads_back_to_menu_hint"), reply_markup=get_ads_menu_keyboard(i18n, current_lang))


