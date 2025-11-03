import logging
import asyncio
import os
import sys
from typing import Optional
from telegram import Update, Video
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import Config
from video_processor import VideoProcessor

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
)
logger = logging.getLogger(__name__)

processor = VideoProcessor()

# Хранение персональных настроек пользователей (в памяти процесса)
user_settings = {
    # user_id: {'duration': int, 'scale': int}
}

HELP_TEXT = (
    "Привет! Я конвертирую пересланные видео в видео-кружочки (video notes).\n\n"
    "Как пользоваться:\n"
    "1) Перешлите мне видео (до FullHD).\n"
    "2) Я возьму начало ролика нужной длительности и пришлю кружочек.\n\n"
    "Команды:\n"
    "/start — краткая справка\n"
    "/help — помощь\n"
    "/duration <сек> — установить длительность кружка (1-60 сек)\n"
    "/duration — узнать текущую длительность\n"
    "/scale <проценты> — масштаб изображения (50-300%)\n"
    "/scale — узнать текущий масштаб\n\n"
    "Примеры:\n"
    "/duration 15 (установить 15 секунд)\n"
    "/scale 150 (увеличить изображение на 50%)\n"
    "/scale 75 (уменьшить, больше сцены видно)"
)

def get_user_setting(user_id: int, key: str, default):
    """Получить персональную настройку пользователя"""
    return user_settings.get(user_id, {}).get(key, default)

def set_user_setting(user_id: int, key: str, value):
    """Установить персональную настройку пользователя"""
    if user_id not in user_settings:
        user_settings[user_id] = {}
    user_settings[user_id][key] = value

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)

async def duration_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для установки/просмотра длительности кружка"""
    user_id = update.effective_user.id
    
    if not context.args:
        # Показываем текущую длительность
        current_duration = get_user_setting(user_id, 'duration', Config.CIRCLE_DURATION)
        await update.message.reply_text(
            f"Текущая длительность кружка: {current_duration} сек.\n"
            f"Для изменения используйте: /duration <1-60>"
        )
        return
    
    try:
        new_duration = int(context.args[0])
        
        if new_duration < 1 or new_duration > 60:
            await update.message.reply_text(
                "Длительность должна быть от 1 до 60 секунд.\n"
                "Пример: /duration 15"
            )
            return
        
        set_user_setting(user_id, 'duration', new_duration)
        await update.message.reply_text(
            f"✅ Длительность кружка установлена: {new_duration} сек.\n"
            "Теперь отправьте видео для обработки."
        )
        
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Неверный формат. Используйте: /duration <число>\n"
            "Пример: /duration 20"
        )

async def scale_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для установки/просмотра масштаба кружка"""
    user_id = update.effective_user.id
    
    if not context.args:
        # Показываем текущий масштаб
        current_scale = get_user_setting(user_id, 'scale', 100)
        await update.message.reply_text(
            f"Текущий масштаб изображения: {current_scale}%\n"
            f"Для изменения используйте: /scale <50-300>\n\n"
            f"100% — оригинал\n"
            f"150% — увеличить (крупнее)\n"
            f"75% — уменьшить (больше сцены)"
        )
        return
    
    try:
        new_scale = int(context.args[0])
        
        if new_scale < 50 or new_scale > 300:
            await update.message.reply_text(
                "Масштаб должен быть от 50 до 300 процентов.\n"
                "Примеры:\n"
                "/scale 100 (оригинал)\n"
                "/scale 150 (увеличить на 50%)\n"
                "/scale 75 (уменьшить на 25%)"
            )
            return
        
        set_user_setting(user_id, 'scale', new_scale)
        scale_description = (
            "оригинал" if new_scale == 100 else
            f"увеличено на {new_scale - 100}%" if new_scale > 100 else
            f"уменьшено на {100 - new_scale}%"
        )
        await update.message.reply_text(
            f"✅ Масштаб изображения установлен: {new_scale}% ({scale_description})\n"
            "Теперь отправьте видео для обработки."
        )
        
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Неверный формат. Используйте: /scale <число>\n"
            "Пример: /scale 150"
        )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user_id = update.effective_user.id
    tg_video: Optional[Video] = message.video or message.effective_attachment

    if not tg_video:
        await message.reply_text("Пожалуйста, пришлите видео.")
        return

    # Проверка размера файла
    if tg_video.file_size and tg_video.file_size > Config.MAX_FILE_SIZE_BYTES:
        await message.reply_text(
            f"Файл слишком большой. Максимум {Config.MAX_FILE_SIZE_MB} МБ."
        )
        return

    await message.chat.send_action(ChatAction.UPLOAD_VIDEO_NOTE)

    try:
        # Скачиваем оригинал во временную папку
        file = await context.bot.get_file(tg_video.file_id)
        os.makedirs(Config.TEMP_DIR, exist_ok=True)
        input_path = os.path.join(Config.TEMP_DIR, f"input_{tg_video.file_unique_id}.mp4")
        await file.download_to_drive(custom_path=input_path)

        # Получаем персональные настройки пользователя
        user_duration = get_user_setting(user_id, 'duration', Config.CIRCLE_DURATION)
        user_scale = get_user_setting(user_id, 'scale', 100)
        
        # Обрабатываем видео → делаем кружок с персональными настройками
        output_path = processor.process_video(
            input_path, 
            duration_override=user_duration,
            scale_override=user_scale
        )
        if not output_path:
            await message.reply_text("Не удалось обработать видео. Попробуйте другое.")
            return

        # Отправляем как video note (кружок)
        with open(output_path, 'rb') as f:
            await message.reply_video_note(video_note=f)

        # Убираем временные файлы
        processor.cleanup_temp_file(input_path)
        processor.cleanup_temp_file(output_path)

    except Exception as e:
        logger.exception("Ошибка при обработке видео")
        await message.reply_text(f"Ошибка: {e}")

def main():
    Config.validate()
    
    # Исправление для Windows: устанавливаем правильную политику event loop
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    application = Application.builder().token(Config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("duration", duration_cmd))
    application.add_handler(CommandHandler("scale", scale_cmd))

    # Обрабатываем видео и файлы, содержащие видео
    application.add_handler(MessageHandler(
        filters.VIDEO | filters.Document.VIDEO, handle_video
    ))

    logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
    application.run_polling()

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка бота...")