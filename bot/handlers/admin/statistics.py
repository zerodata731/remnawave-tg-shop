import logging
from aiogram import Router, F, types
from typing import Optional, Dict, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings

from db.dal import user_dal, payment_dal, panel_sync_dal
from db.models import Payment, PanelSyncStatus
from bot.services.panel_api_service import PanelApiService

from bot.keyboards.inline.admin_keyboards import get_back_to_admin_panel_keyboard
from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_statistics_router")


async def show_statistics_handler(callback: types.CallbackQuery,
                                  i18n_data: dict, settings: Settings,
                                  session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error displaying statistics.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    await callback.answer()

    stats_text_parts = [f"<b>{_('admin_stats_header')}</b>"]

    # Enhanced user statistics
    user_stats = await user_dal.get_enhanced_user_statistics(session)
    
    stats_text_parts.append(
        f"\n<b>👥 {_('admin_enhanced_users_stats_header', default='Пользователи')}</b>"
    )
    stats_text_parts.append(
        f"📊 Всего: <b>{user_stats['total_users']}</b>"
    )
    stats_text_parts.append(
        f"📈 Активных сегодня: <b>{user_stats['active_today']}</b>"
    )
    stats_text_parts.append(
        f"💳 С платной подпиской: <b>{user_stats['paid_subscriptions']}</b>"
    )
    stats_text_parts.append(
        f"🆓 На пробном периоде: <b>{user_stats['trial_users']}</b>"
    )
    stats_text_parts.append(
        f"😴 Неактивных: <b>{user_stats['inactive_users']}</b>"
    )
    stats_text_parts.append(
        f"🚫 Заблокированных: <b>{user_stats['banned_users']}</b>"
    )
    stats_text_parts.append(
        f"🎁 Привлечено по реферальной программе: <b>{user_stats['referral_users']}</b>"
    )
    
    # Financial statistics
    financial_stats = await payment_dal.get_financial_statistics(session)
    
    stats_text_parts.append(
        f"\n<b>💰 {_('admin_financial_stats_header', default='Финансовая статистика')}</b>"
    )
    stats_text_parts.append(
        f"📅 За сегодня: <b>{financial_stats['today_revenue']:.2f} RUB</b> ({financial_stats['today_payments_count']} платежей)"
    )
    stats_text_parts.append(
        f"📅 За неделю: <b>{financial_stats['week_revenue']:.2f} RUB</b>"
    )
    stats_text_parts.append(
        f"📅 За месяц: <b>{financial_stats['month_revenue']:.2f} RUB</b>"
    )
    stats_text_parts.append(
        f"🏆 За все время: <b>{financial_stats['all_time_revenue']:.2f} RUB</b>"
    )

    last_payments_models: List[
        Payment] = await payment_dal.get_recent_payment_logs_with_user(session,
                                                                       limit=5)
    if last_payments_models:
        stats_text_parts.append(
            f"\n<b>{_('admin_stats_recent_payments_header')}</b>")
        for payment in last_payments_models:
            status_emoji = "✅" if payment.status == 'succeeded' else (
                "⏳" if payment.status == 'pending'
                or payment.status == 'pending_yookassa' else "❌")

            user_info = f"User {payment.user_id}"
            if payment.user and payment.user.username:
                user_info += f" (@{payment.user.username})"
            elif payment.user and payment.user.first_name:
                user_info += f" ({payment.user.first_name})"

            payment_date_str = payment.created_at.strftime(
                '%Y-%m-%d') if payment.created_at else "N/A"

            stats_text_parts.append(
                _("admin_stats_payment_item",
                  status_emoji=status_emoji,
                  amount=payment.amount,
                  currency=payment.currency,
                  user_info=user_info,
                  p_status=payment.status,
                  p_date=payment_date_str))
    else:
        stats_text_parts.append(f"\n{_('admin_stats_no_payments_found')}")

    sync_status_model: Optional[
        PanelSyncStatus] = await panel_sync_dal.get_panel_sync_status(session)
    if sync_status_model and sync_status_model.status != "never_run":
        stats_text_parts.append(
            f"\n<b>{_('admin_stats_last_sync_header')}</b>")

        sync_time_val = sync_status_model.last_sync_time
        sync_time_str = sync_time_val.strftime(
            '%Y-%m-%d %H:%M:%S UTC') if sync_time_val else "N/A"

        details_val = sync_status_model.details
        details_str = (details_val[:100] +
                       "...") if details_val and len(details_val) > 100 else (
                           details_val or "N/A")

        stats_text_parts.append(
            f"  {_('admin_stats_sync_time')}: {sync_time_str}")
        stats_text_parts.append(
            f"  {_('admin_stats_sync_status')}: {sync_status_model.status}")
        stats_text_parts.append(
            f"  {_('admin_stats_sync_users_processed')}: {sync_status_model.users_processed_from_panel}"
        )
        stats_text_parts.append(
            f"  {_('admin_stats_sync_subs_synced')}: {sync_status_model.subscriptions_synced}"
        )
        stats_text_parts.append(
            f"  {_('admin_stats_sync_details_label')}: {details_str}")
    else:
        stats_text_parts.append(f"\n{_('admin_sync_status_never_run')}")

    # Panel Statistics
    stats_text_parts.append(f"\n<b>🖥 {_('admin_panel_stats_header', default='Статистика панели')}</b>")
    
    try:
        panel_service = PanelApiService(settings)
        
        # Get panel system statistics
        logging.info("Fetching panel statistics...")
        panel_stats = await panel_service.get_panel_statistics()
        nodes_stats = await panel_service.get_nodes_statistics()
        online_count = await panel_service.get_online_users_count()
        users_activity = await panel_service.get_users_activity_stats()
        
        logging.info(f"Panel stats response: panel_stats={panel_stats}, nodes_stats={nodes_stats}, online_count={online_count}, users_activity={users_activity}")
        
        # Online users
        if online_count is not None:
            stats_text_parts.append(f"🟢 Онлайн сейчас: <b>{online_count}</b>")
        else:
            stats_text_parts.append(f"🟢 Онлайн сейчас: <b>N/A</b>")
        
        # Users activity
        if users_activity:
            today_connected = users_activity.get('today_connected', 'N/A')
            week_connected = users_activity.get('week_connected', 'N/A')
            never_connected = users_activity.get('never_connected', 'N/A')
            stats_text_parts.append(f"📅 Подключались сегодня: <b>{today_connected}</b>")
            stats_text_parts.append(f"📅 Подключались за неделю: <b>{week_connected}</b>")
            stats_text_parts.append(f"❌ Никогда не подключались: <b>{never_connected}</b>")
        else:
            stats_text_parts.append(f"📅 Активность пользователей: <b>N/A</b>")
        
        # Nodes statistics
        if nodes_stats:
            active_nodes = len([node for node in nodes_stats if node.get('status') == 'active'])
            total_nodes = len(nodes_stats)
            stats_text_parts.append(f"🔗 Активных нод: <b>{active_nodes}/{total_nodes}</b>")
        else:
            stats_text_parts.append(f"🔗 Ноды: <b>N/A</b>")
        
        # System statistics
        if panel_stats:
            system_info = panel_stats.get('system', {})
            if system_info:
                memory_usage = system_info.get('memory_usage_percent', 'N/A')
                cpu_usage = system_info.get('cpu_usage_percent', 'N/A')
                stats_text_parts.append(f"💾 Использование RAM: <b>{memory_usage}%</b>")
                stats_text_parts.append(f"🔄 Загрузка CPU: <b>{cpu_usage}%</b>")
            else:
                stats_text_parts.append(f"💾 Системная информация: <b>N/A</b>")
        else:
            stats_text_parts.append(f"💾 Системная статистика: <b>N/A</b>")
        
        await panel_service.close()
        
    except Exception as e:
        logging.error(f"Failed to fetch panel statistics: {e}", exc_info=True)
        stats_text_parts.append("❌ Ошибка получения данных с панели")
        stats_text_parts.append(f"⚠️ Детали: {str(e)}")

    final_text = "\n".join(stats_text_parts)

    try:
        await callback.message.edit_text(
            final_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    except Exception as e_edit:
        logging.error(f"Error editing message for statistics: {e_edit}",
                      exc_info=True)

        max_chunk_size = 4000
        for i in range(0, len(final_text), max_chunk_size):
            chunk = final_text[i:i + max_chunk_size]
            is_last_chunk = (i + max_chunk_size) >= len(final_text)
            try:
                await callback.message.answer(
                    chunk,
                    reply_markup=get_back_to_admin_panel_keyboard(
                        current_lang, i18n) if is_last_chunk else None,
                    parse_mode="HTML")
            except Exception as e_chunk:
                logging.error(f"Failed to send statistics chunk: {e_chunk}")
                if i == 0:
                    await callback.message.answer(
                        _("error_displaying_statistics"),
                        reply_markup=get_back_to_admin_panel_keyboard(
                            current_lang, i18n))
                break
