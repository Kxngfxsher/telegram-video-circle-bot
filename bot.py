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

HELP_TEXT = (
    "Привет! Я конвертирую пересланные видео в видео-кружочки (video notes).\n\n"
    "Как пользоваться:\n"
    "1) Перешлите мне видео (до FullHD).\n"
    "2) Я возьму середину ролика (до 60 сек) и пришлю кружочек.\n\n"
    "Команды:\n"
    "/start — краткая справка\n"
    "/help — помощь\n"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
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

        # Обрабатываем видео → делаем кружок
        output_path = processor.process_video(input_path)
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