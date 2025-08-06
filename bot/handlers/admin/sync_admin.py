import logging
from aiogram import Router, types, Bot
from aiogram.filters import Command
from typing import Optional, Union
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from config.settings import Settings
from bot.services.panel_api_service import PanelApiService

from db.dal import user_dal, subscription_dal, panel_sync_dal

from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_sync_router")


async def perform_sync(panel_service: PanelApiService, session: AsyncSession, 
                      settings: Settings, i18n_instance: JsonI18n) -> dict:
    """
    Perform panel synchronization and return results
    Returns dict with status, details, and sync statistics
    """
    panel_records_checked = 0
    users_found_in_db = 0
    users_updated = 0
    subscriptions_synced_count = 0
    sync_errors = []
    
    # Additional counters for detailed logging
    users_without_telegram_id = 0
    users_not_found_in_db = 0
    users_uuid_updated = 0
    subscriptions_created = 0
    subscriptions_updated = 0

    try:
        panel_users_data = await panel_service.get_all_panel_users()

        if panel_users_data is None:
            error_msg = "Failed to fetch users from panel or panel API issue."
            sync_errors.append(error_msg)
            await panel_sync_dal.update_panel_sync_status(session, "failed", error_msg)
            await session.commit()
            return {"status": "failed", "details": error_msg, "errors": sync_errors}

        if not panel_users_data:
            status_msg = "No users found in the panel to sync."
            await panel_sync_dal.update_panel_sync_status(
                session, "success", status_msg, 0, 0
            )
            await session.commit()
            return {"status": "success", "details": status_msg, "users_synced": 0, "subs_synced": 0}

        total_panel_users = len(panel_users_data)
        logging.info(f"Starting sync for {total_panel_users} panel users.")

        for panel_user_dict in panel_users_data:
            try:
                panel_records_checked += 1
                panel_uuid = panel_user_dict.get("uuid")
                panel_subscription_uuid = panel_user_dict.get("subscriptionUuid") or panel_user_dict.get("shortUuid")
                telegram_id_from_panel = panel_user_dict.get("telegramId")

                if not panel_uuid:
                    sync_errors.append(f"Panel user missing UUID: {panel_user_dict}")
                    logging.warning(f"Skipping panel user without UUID: {panel_user_dict}")
                    continue

                # Track users without telegram ID
                if not telegram_id_from_panel:
                    users_without_telegram_id += 1

                # Try to find existing user in local DB
                existing_user = None
                
                # First, try to find by telegram ID if available
                if telegram_id_from_panel:
                    existing_user = await user_dal.get_user_by_id(session, telegram_id_from_panel)
                    if existing_user:
                        logging.debug(f"Found user by telegramId {telegram_id_from_panel}")
                
                # If not found by telegram ID, try to find by panel UUID
                if not existing_user:
                    existing_user = await user_dal.get_user_by_panel_uuid(session, panel_uuid)
                    if existing_user:
                        logging.info(f"Found user by panel UUID {panel_uuid}, telegramId: {existing_user.user_id}")
                        # Update telegram ID if it was missing in panel data but we have local user
                        if telegram_id_from_panel and existing_user.user_id != telegram_id_from_panel:
                            logging.warning(f"TelegramId mismatch: panel={telegram_id_from_panel}, local={existing_user.user_id}")
                
                if not existing_user:
                    users_not_found_in_db += 1
                    if telegram_id_from_panel:
                        logging.debug(f"Panel user with telegramId {telegram_id_from_panel} and UUID {panel_uuid} not found in local DB")
                    else:
                        logging.debug(f"Panel user with UUID {panel_uuid} (no telegramId) not found in local DB")
                    continue

                # User found in local DB
                users_found_in_db += 1
                user_was_updated = False

                # Get the actual user_id for subscription operations
                actual_user_id = existing_user.user_id

                # Update panel UUID if different
                if existing_user.panel_user_uuid != panel_uuid:
                    existing_user.panel_user_uuid = panel_uuid
                    user_was_updated = True
                    users_uuid_updated += 1
                    logging.info(f"Updated panel UUID for user {actual_user_id}: {panel_uuid}")

                # Sync subscription data
                panel_expire_at_iso = panel_user_dict.get("expireAt")
                panel_status = panel_user_dict.get("status", "UNKNOWN")
                
                if panel_expire_at_iso:
                    try:
                        panel_expire_at = datetime.fromisoformat(
                            panel_expire_at_iso.replace("Z", "+00:00")
                        )
                        
                        # Update or create subscription
                        active_sub = await subscription_dal.get_active_subscription_by_user_id(
                            session, actual_user_id, panel_uuid
                        )
                        
                        if active_sub:
                            # Check if subscription needs update
                            if (active_sub.end_date != panel_expire_at or 
                                active_sub.status_from_panel != panel_status or
                                active_sub.is_active != (panel_status == "ACTIVE")):
                                
                                await subscription_dal.update_subscription_end_date(
                                    session, active_sub.subscription_id, panel_expire_at
                                )
                                # Update status fields
                                active_sub.status_from_panel = panel_status
                                active_sub.is_active = (panel_status == "ACTIVE")
                                subscriptions_synced_count += 1
                                subscriptions_updated += 1
                                user_was_updated = True
                                logging.info(f"Updated subscription for user {actual_user_id}: expires {panel_expire_at}, status {panel_status}")
                        else:
                            # Create new subscription record
                            subscription_uuid_to_use = panel_subscription_uuid or panel_uuid
                            
                            logging.info(f"Creating new subscription for user {actual_user_id} with UUID {subscription_uuid_to_use}")
                            
                            sub_payload = {
                                "user_id": actual_user_id,
                                "panel_user_uuid": panel_uuid,
                                "panel_subscription_uuid": subscription_uuid_to_use,
                                "start_date": datetime.now(timezone.utc),
                                "end_date": panel_expire_at,
                                "duration_months": 1,  # Default
                                "is_active": panel_status == "ACTIVE",
                                "status_from_panel": panel_status,
                                "traffic_limit_bytes": settings.user_traffic_limit_bytes,
                            }
                            await subscription_dal.upsert_subscription(session, sub_payload)
                            subscriptions_synced_count += 1
                            subscriptions_created += 1
                            user_was_updated = True
                            
                    except Exception as e:
                        sync_errors.append(f"Error syncing subscription for user {actual_user_id}: {str(e)}")
                        logging.error(f"Error syncing subscription for user {actual_user_id}: {e}")

                if user_was_updated:
                    users_updated += 1
                            
            except Exception as e_user:
                sync_errors.append(f"Error processing panel user {panel_user_dict.get('uuid', 'unknown')}: {str(e_user)}")
                logging.error(f"Error syncing user: {e_user}")

        # Update sync status
        status = "completed_with_errors" if sync_errors else "completed"
        details = (f"📊 Статистика синхронизации:\n"
                  f"🔍 Проверено записей панели: {panel_records_checked}\n"
                  f"👥 Найдено пользователей в БД: {users_found_in_db}\n"
                  f"🔄 Пользователей обновлено: {users_updated}\n"
                  f"📋 Подписок синхронизировано: {subscriptions_synced_count}\n"
                  f"   ├── Создано новых: {subscriptions_created}\n"
                  f"   └── Обновлено существующих: {subscriptions_updated}")
        
        if users_without_telegram_id > 0:
            details += f"\n⚠️ Записей без telegramId: {users_without_telegram_id}"
        if users_not_found_in_db > 0:
            details += f"\n❌ Не найдено в БД: {users_not_found_in_db}"
        if sync_errors:
            details += f"\n🚫 Ошибок: {len(sync_errors)}"

        await panel_sync_dal.update_panel_sync_status(
            session, status, details, panel_records_checked, subscriptions_synced_count
        )
        await session.commit()

        # Detailed logging summary
        logging.info(f"Sync completed - Summary:")
        logging.info(f"  Panel records checked: {panel_records_checked}")
        logging.info(f"  Users without telegramId: {users_without_telegram_id}")
        logging.info(f"  Users not found in local DB: {users_not_found_in_db}")
        logging.info(f"  Users found in local DB: {users_found_in_db}")
        logging.info(f"  Users with UUID updated: {users_uuid_updated}")
        logging.info(f"  Users updated overall: {users_updated}")
        logging.info(f"  Subscriptions total synced: {subscriptions_synced_count}")
        logging.info(f"  Subscriptions created: {subscriptions_created}")
        logging.info(f"  Subscriptions updated: {subscriptions_updated}")
        logging.info(f"  Sync errors: {len(sync_errors)}")

        return {
            "status": status,
            "details": details,
            "users_processed": panel_records_checked,
            "users_synced": users_found_in_db,
            "subs_synced": subscriptions_synced_count,
            "errors": sync_errors
        }

    except Exception as e_sync_global:
        await session.rollback()
        logging.error(f"Global error during sync: {e_sync_global}", exc_info=True)
        error_detail = f"Unexpected error during sync: {str(e_sync_global)[:200]}"
        
        await panel_sync_dal.update_panel_sync_status(
            session, "failed", error_detail, panel_records_checked, subscriptions_synced_count
        )
        
        return {"status": "failed", "details": error_detail, "errors": [str(e_sync_global)]}


@router.message(Command("sync"))
async def sync_command_handler(
    message_event: Union[types.Message, types.CallbackQuery],
    bot: Bot,
    settings: Settings,
    i18n_data: dict,
    panel_service: PanelApiService,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in sync_command_handler")

        if isinstance(message_event, types.Message):
            await message_event.answer("Language error.")
        elif isinstance(message_event, types.CallbackQuery):
            await message_event.answer("Language error.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    target_chat_id = (
        message_event.chat.id
        if isinstance(message_event, types.Message)
        else (message_event.message.chat.id if message_event.message else None)
    )
    if not target_chat_id:
        logging.error("Sync handler: could not determine target_chat_id.")
        if isinstance(message_event, types.CallbackQuery):
            await message_event.answer("Error initiating sync.", show_alert=True)
        return

    if isinstance(message_event, types.Message):
        await message_event.answer(_("sync_started"))

    logging.info(f"Admin ({message_event.from_user.id}) triggered panel sync.")

    # Use the extracted perform_sync function
    try:
        sync_result = await perform_sync(panel_service, session, settings, i18n)
        
        status = sync_result.get("status")
        details = sync_result.get("details", "No details available")
        errors = sync_result.get("errors", [])
        
        if status == "failed":
            await bot.send_message(target_chat_id, _("sync_failed", details=details))
        elif status == "completed_with_errors":
            error_preview = "; ".join(errors[:3])  # Show first 3 errors
            final_message = _(
                "sync_completed_with_errors_details",
                total_checked=sync_result.get("users_processed", 0),
                users_synced=sync_result.get("users_synced", 0),
                subs_synced=sync_result.get("subs_synced", 0),
                errors_count=len(errors),
                error_details_preview=error_preview[:200] + "..." if len(error_preview) > 200 else error_preview
            )
            await bot.send_message(target_chat_id, final_message)
        else:
            final_message = _(
                "sync_completed_details",
                total_checked=sync_result.get("users_processed", 0),
                users_synced=sync_result.get("users_synced", 0),
                subs_synced=sync_result.get("subs_synced", 0)
            )
            await bot.send_message(target_chat_id, _("sync_completed", status="Success", details=final_message))
            
    except Exception as e_sync_global:
        logging.error(f"Global error during /sync command: {e_sync_global}", exc_info=True)
        await bot.send_message(target_chat_id, _("sync_failed", details=str(e_sync_global)))


@router.message(Command("syncstatus"))
async def sync_status_command_handler(
    message: types.Message, i18n_data: dict, settings: Settings, session: AsyncSession
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.answer("Language error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    status_record_model = await panel_sync_dal.get_panel_sync_status(session)
    response_text = ""
    if status_record_model:
        last_time_val = status_record_model.last_sync_time
        last_time_str = (
            last_time_val.strftime("%Y-%m-%d %H:%M:%S UTC") if last_time_val else "N/A"
        )

        details_val = status_record_model.details
        details_str = (
            (details_val[:200] + "...")
            if details_val and len(details_val) > 200
            else (details_val or "N/A")
        )

        response_text = (
            f"<b>{_('admin_stats_last_sync_header')}</b>\n"
            f"  {_('admin_stats_sync_time')}: {last_time_str}\n"
            f"  {_('admin_stats_sync_status')}: {status_record_model.status}\n"
            f"  {_('admin_stats_sync_users_processed')}: {status_record_model.users_processed_from_panel}\n"
            f"  {_('admin_stats_sync_subs_synced')}: {status_record_model.subscriptions_synced}\n"
            f"  {_('admin_stats_sync_details_label')}: {details_str}"
        )
    else:
        response_text = _("admin_sync_status_never_run")

    await message.answer(response_text, parse_mode="HTML")