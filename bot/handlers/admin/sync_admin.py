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
    users_processed_count = 0
    users_synced_successfully = 0
    subscriptions_synced_count = 0
    sync_errors = []

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
                users_processed_count += 1
                panel_uuid = panel_user_dict.get("uuid")
                telegram_id_from_panel = panel_user_dict.get("telegramId")

                if not panel_uuid:
                    sync_errors.append(f"Panel user missing UUID: {panel_user_dict}")
                    continue

                # Sync user data
                existing_user = None
                if telegram_id_from_panel:
                    existing_user = await user_dal.get_user_by_id(session, telegram_id_from_panel)

                if existing_user:
                    if existing_user.panel_user_uuid != panel_uuid:
                        existing_user.panel_user_uuid = panel_uuid
                        users_synced_successfully += 1
                        logging.info(f"Updated panel UUID for user {telegram_id_from_panel}")

                # Sync subscription data if user exists
                if existing_user:
                    panel_expire_at_iso = panel_user_dict.get("expireAt")
                    panel_status = panel_user_dict.get("status", "UNKNOWN")
                    
                    if panel_expire_at_iso:
                        try:
                            panel_expire_at = datetime.fromisoformat(
                                panel_expire_at_iso.replace("Z", "+00:00")
                            )
                            
                            # Update or create subscription
                            active_sub = await subscription_dal.get_active_subscription_by_user_id(
                                session, telegram_id_from_panel, panel_uuid
                            )
                            
                            if active_sub:
                                if active_sub.end_date != panel_expire_at:
                                    await subscription_dal.update_subscription_end_date(
                                        session, active_sub.subscription_id, panel_expire_at
                                    )
                                    subscriptions_synced_count += 1
                            else:
                                # Create new subscription record if none exists
                                sub_payload = {
                                    "user_id": telegram_id_from_panel,
                                    "panel_user_uuid": panel_uuid,
                                    "panel_subscription_uuid": panel_uuid,  # Using same UUID
                                    "start_date": datetime.now(timezone.utc),
                                    "end_date": panel_expire_at,
                                    "duration_months": 1,  # Default
                                    "is_active": panel_status == "ACTIVE",
                                    "status_from_panel": panel_status,
                                    "traffic_limit_bytes": settings.user_traffic_limit_bytes,
                                }
                                await subscription_dal.upsert_subscription(session, sub_payload)
                                subscriptions_synced_count += 1
                                
                        except Exception as e:
                            sync_errors.append(f"Error syncing subscription for user {telegram_id_from_panel}: {str(e)}")
                            
            except Exception as e_user:
                sync_errors.append(f"Error processing panel user {panel_user_dict.get('uuid', 'unknown')}: {str(e_user)}")
                logging.error(f"Error syncing user: {e_user}")

        # Update sync status
        status = "completed_with_errors" if sync_errors else "completed"
        details = f"Synced {users_synced_successfully}/{users_processed_count} users, {subscriptions_synced_count} subscriptions"
        if sync_errors:
            details += f", {len(sync_errors)} errors"

        await panel_sync_dal.update_panel_sync_status(
            session, status, details, users_processed_count, subscriptions_synced_count
        )
        await session.commit()

        return {
            "status": status,
            "details": details,
            "users_processed": users_processed_count,
            "users_synced": users_synced_successfully,
            "subs_synced": subscriptions_synced_count,
            "errors": sync_errors
        }

    except Exception as e_sync_global:
        await session.rollback()
        logging.error(f"Global error during sync: {e_sync_global}", exc_info=True)
        error_detail = f"Unexpected error during sync: {str(e_sync_global)[:200]}"
        
        await panel_sync_dal.update_panel_sync_status(
            session, "failed", error_detail, users_processed_count, subscriptions_synced_count
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