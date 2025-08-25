# Bot utilities package

from dataclasses import dataclass
from typing import Optional
from aiogram import types


@dataclass
class MessageContent:
    """Класс для хранения информации о контенте сообщения"""
    content_type: str
    file_id: Optional[str] = None
    text: Optional[str] = None


def get_message_content(message: types.Message) -> MessageContent:
    """
    Определяет тип контента сообщения и возвращает его данные.
    Использует match/case вместо длинных if-elif цепочек.
    """
    text = (message.text or message.caption or "").strip()
    
    # Проверяем наличие медиа-контента
    media_content = None
    if message.photo:
        media_content = ("photo", message.photo[-1].file_id)
    elif message.video:
        media_content = ("video", message.video.file_id)
    elif message.animation:
        media_content = ("animation", message.animation.file_id)
    elif message.document:
        media_content = ("document", message.document.file_id)
    elif message.audio:
        media_content = ("audio", message.audio.file_id)
    elif message.voice:
        media_content = ("voice", message.voice.file_id)
    elif message.sticker:
        media_content = ("sticker", message.sticker.file_id)
    elif message.video_note:
        media_content = ("video_note", message.video_note.file_id)
    
    # Используем match/case для определения типа контента
    match media_content:
        case (content_type, file_id):
            return MessageContent(content_type=content_type, file_id=file_id, text=text)
        case None:
            return MessageContent(content_type="text", text=text)
        case _:
            return MessageContent(content_type="text", text=text)


async def send_message_by_type(bot, chat_id: int, content: MessageContent, **kwargs) -> None:
    """
    Отправляет сообщение указанного типа.
    Использует match/case вместо длинных if-elif цепочек.
    """
    match content.content_type:
        case "text":
            await bot.send_message(
                chat_id=chat_id,
                text=content.text,
                **kwargs
            )
        case "photo":
            await bot.send_photo(
                chat_id=chat_id,
                photo=content.file_id,
                caption=content.text or None,
                **kwargs
            )
        case "video":
            await bot.send_video(
                chat_id=chat_id,
                video=content.file_id,
                caption=content.text or None,
                **kwargs
            )
        case "animation":
            await bot.send_animation(
                chat_id=chat_id,
                animation=content.file_id,
                caption=content.text or None,
                **kwargs
            )
        case "document":
            await bot.send_document(
                chat_id=chat_id,
                document=content.file_id,
                caption=content.text or None,
                **kwargs
            )
        case "audio":
            await bot.send_audio(
                chat_id=chat_id,
                audio=content.file_id,
                caption=content.text or None,
                **kwargs
            )
        case "voice":
            await bot.send_voice(
                chat_id=chat_id,
                voice=content.file_id,
                caption=content.text or None,
                **kwargs
            )
        case "sticker":
            await bot.send_sticker(
                chat_id=chat_id,
                sticker=content.file_id,
                # stickers не поддерживают caption - удаляем его из kwargs
                **{k: v for k, v in kwargs.items() if k != 'caption'}
            )
        case "video_note":
            await bot.send_video_note(
                chat_id=chat_id,
                video_note=content.file_id,
                # video_note не поддерживает caption - удаляем его из kwargs
                **{k: v for k, v in kwargs.items() if k != 'caption'}
            )
        case _:
            # Fallback для неизвестных типов
            await bot.send_message(
                chat_id=chat_id,
                text=content.text or "Unknown content type",
                **{k: v for k, v in kwargs.items() if k != 'caption'}
            )


async def send_message_via_queue(queue_manager, uid: int, content: MessageContent, **kwargs) -> None:
    """
    Отправляет сообщение через очередь в зависимости от типа контента.
    Использует match/case вместо длинных if-elif цепочек.
    """
    match content.content_type:
        case "text":
            await queue_manager.send_message(
                chat_id=uid, text=content.text, **kwargs
            )
        case "photo":
            await queue_manager.send_photo(
                chat_id=uid, photo=content.file_id, caption=content.text or None, **kwargs
            )
        case "video":
            await queue_manager.send_video(
                chat_id=uid, video=content.file_id, caption=content.text or None, **kwargs
            )
        case "animation":
            await queue_manager.send_animation(
                chat_id=uid, animation=content.file_id, caption=content.text or None, **kwargs
            )
        case "document":
            await queue_manager.send_document(
                chat_id=uid, document=content.file_id, caption=content.text or None, **kwargs
            )
        case "audio":
            await queue_manager.send_audio(
                chat_id=uid, audio=content.file_id, caption=content.text or None, **kwargs
            )
        case "voice":
            await queue_manager.send_voice(
                chat_id=uid, voice=content.file_id, caption=content.text or None, **kwargs
            )
        case "sticker":
            await queue_manager.send_sticker(
                chat_id=uid, sticker=content.file_id
            )
        case "video_note":
            await queue_manager.send_video_note(
                chat_id=uid, video_note=content.file_id
            )
        case _:
            # Fallback для неизвестных типов
            await queue_manager.send_message(
                chat_id=uid, text=content.text or "Unknown content type", **kwargs
            )


async def send_direct_message(bot, chat_id: int, content: MessageContent, extra_text: str = "", **kwargs) -> None:
    """
    Отправляет прямое сообщение с дополнительной обработкой для sticker и video_note.
    Для этих типов медиа отправляется отдельное текстовое сообщение, т.к. они не поддерживают caption.
    """
    match content.content_type:
        case "sticker":
            # Отправляем стикер
            await bot.send_sticker(
                chat_id=chat_id,
                sticker=content.file_id,
                **{k: v for k, v in kwargs.items() if k != 'caption'}
            )
            # Если есть текст с подписью, отправляем отдельно
            if content.text or extra_text:
                text_to_send = (content.text + extra_text) if content.text else extra_text
                await bot.send_message(
                    chat_id,
                    text_to_send,
                    **{k: v for k, v in kwargs.items() if k not in ['caption']}
                )
        case "video_note":
            # Отправляем видео-заметку
            await bot.send_video_note(
                chat_id=chat_id,
                video_note=content.file_id,
                **{k: v for k, v in kwargs.items() if k != 'caption'}
            )
            # Если есть текст с подписью, отправляем отдельно
            if content.text or extra_text:
                text_to_send = (content.text + extra_text) if content.text else extra_text
                await bot.send_message(
                    chat_id,
                    text_to_send,
                    **{k: v for k, v in kwargs.items() if k not in ['caption']}
                )
        case "text":
            # Для текста объединяем с extra_text
            final_text = (content.text + extra_text) if content.text else extra_text
            await bot.send_message(
                chat_id=chat_id,
                text=final_text,
                **kwargs
            )
        case _:
            # Для остальных типов медиа используем caption
            final_caption = (content.text + extra_text) if content.text else None
            await send_message_by_type(
                bot, chat_id, 
                MessageContent(content.content_type, content.file_id, final_caption),
                **kwargs
            )