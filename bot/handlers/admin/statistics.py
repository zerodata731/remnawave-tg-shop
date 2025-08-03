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
        f"📊 {_('admin_user_stats_total_label', default='Всего')}: <b>{user_stats['total_users']}</b>"
    )
    # Removed: Active today moved to panel stats
    stats_text_parts.append(
        f"💳 {_('admin_user_stats_paid_subs_label', default='С платной подпиской')}: <b>{user_stats['paid_subscriptions']}</b>"
    )
    stats_text_parts.append(
        f"🆓 {_('admin_user_stats_trial_label', default='На пробном периоде')}: <b>{user_stats['trial_users']}</b>"
    )
    stats_text_parts.append(
        f"😴 {_('admin_user_stats_inactive_label', default='Неактивных')}: <b>{user_stats['inactive_users']}</b>"
    )
    stats_text_parts.append(
        f"🚫 {_('admin_user_stats_banned_label', default='Заблокированных')}: <b>{user_stats['banned_users']}</b>"
    )
    stats_text_parts.append(
        f"🎁 {_('admin_user_stats_referral_label', default='Привлечено по реферальной программе')}: <b>{user_stats['referral_users']}</b>"
    )
    
    # Panel Statistics - moved above financial
    stats_text_parts.append(f"\n<b>🖥 {_('admin_panel_stats_header', default='Статистика панели')}</b>")
    
    try:
        async with PanelApiService(settings) as panel_service:
            # Get system stats
            system_stats = await panel_service.get_system_stats()
            bandwidth_stats = await panel_service.get_bandwidth_stats()
            nodes_stats = await panel_service.get_nodes_statistics()
            
            logging.info(f"Panel stats response: system={system_stats}, bandwidth={bandwidth_stats}, nodes={nodes_stats}")
            
            if system_stats:
                users = system_stats.get('users', {})
                active_users = users.get('active', 0)
                disabled_users = users.get('disabled', 0) 
                expired_users = users.get('expired', 0)
                limited_users = users.get('limited', 0)
                total_users = users.get('total', 0)
                
                stats_text_parts.append(f"🟢 {_('admin_panel_online_label', default='Онлайн')}: <b>{active_users}</b>")
                stats_text_parts.append(f"🔴 {_('admin_panel_offline_label', default='Офлайн')}: <b>{disabled_users}</b>")
                stats_text_parts.append(f"⏰ {_('admin_panel_expired_label', default='Истекшие')}: <b>{expired_users}</b>")
                stats_text_parts.append(f"⚠️ {_('admin_panel_limited_label', default='Ограниченные')}: <b>{limited_users}</b>")
                stats_text_parts.append(f"👥 {_('admin_panel_total_users_label', default='Всего пользователей')}: <b>{total_users}</b>")
                
                # System resources
                cpu = system_stats.get('cpu', {})
                memory = system_stats.get('memory', {})
                if cpu:
                    cpu_usage = cpu.get('usage', 0)
                    stats_text_parts.append(f"🔄 {_('admin_panel_cpu_usage_label', default='Загрузка CPU')}: <b>{cpu_usage:.1f}%</b>")
                if memory:
                    memory_usage = memory.get('usage', 0)
                    stats_text_parts.append(f"💾 {_('admin_panel_memory_usage_label', default='Использование RAM')}: <b>{memory_usage:.1f}%</b>")
            else:
                stats_text_parts.append(f"⚠️ {_('admin_panel_system_stats_error', default='Ошибка получения системной статистики')}")
            
            # Bandwidth stats
            if bandwidth_stats:
                today_traffic = bandwidth_stats.get('bandwidthToday', {})
                week_traffic = bandwidth_stats.get('bandwidthLastSevenDays', {})
                month_traffic = bandwidth_stats.get('bandwidthLastThirtyDays', {})
                
                if today_traffic:
                    today_total = today_traffic.get('total', '0 B')
                    stats_text_parts.append(f"📊 {_('admin_panel_traffic_today_label', default='Трафик сегодня')}: <b>{today_total}</b>")
                
                if week_traffic:
                    week_total = week_traffic.get('total', '0 B')
                    stats_text_parts.append(f"📊 {_('admin_panel_traffic_week_label', default='Трафик за неделю')}: <b>{week_total}</b>")
                    
                if month_traffic:
                    month_total = month_traffic.get('total', '0 B')
                    stats_text_parts.append(f"📊 {_('admin_panel_traffic_month_label', default='Трафик за месяц')}: <b>{month_total}</b>")
            else:
                stats_text_parts.append(f"⚠️ {_('admin_panel_bandwidth_stats_error', default='Ошибка получения статистики трафика')}")
            
            # Nodes stats
            if nodes_stats:
                last_seven_days = nodes_stats.get('lastSevenDays', [])
                active_nodes_count = len([node for node in last_seven_days if node.get('status') == 'active'])
                total_nodes_count = len(last_seven_days)
                stats_text_parts.append(f"🔗 {_('admin_panel_nodes_label', default='Активных нод')}: <b>{active_nodes_count}/{total_nodes_count}</b>")
            else:
                stats_text_parts.append(f"⚠️ {_('admin_panel_nodes_stats_error', default='Ошибка получения статистики нод')}")
                
    except Exception as e:
        logging.error(f"Failed to fetch panel statistics: {e}", exc_info=True)
        stats_text_parts.append(f"❌ {_('admin_panel_stats_fetch_error', default='Ошибка получения данных с панели')}")
        stats_text_parts.append(f"⚠️ {_('admin_panel_stats_error_details', default='Детали')}: {str(e)}")

    # Financial statistics
    financial_stats = await payment_dal.get_financial_statistics(session)
    
    stats_text_parts.append(
        f"\n<b>💰 {_('admin_financial_stats_header', default='Финансовая статистика')}</b>"
    )
    stats_text_parts.append(
        f"📅 {_('admin_financial_today_label', default='За сегодня')}: <b>{financial_stats['today_revenue']:.2f} RUB</b> ({financial_stats['today_payments_count']} {_('admin_financial_payments_label', default='платежей')})"
    )
    stats_text_parts.append(
        f"📅 {_('admin_financial_week_label', default='За неделю')}: <b>{financial_stats['week_revenue']:.2f} RUB</b>"
    )
    stats_text_parts.append(
        f"📅 {_('admin_financial_month_label', default='За месяц')}: <b>{financial_stats['month_revenue']:.2f} RUB</b>"
    )
    stats_text_parts.append(
        f"🏆 {_('admin_financial_all_time_label', default='За все время')}: <b>{financial_stats['all_time_revenue']:.2f} RUB</b>"
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
