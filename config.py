import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

class Config:
    """Конфигурация бота"""
    
    # Токен бота (обязательный)
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    # Настройки файлов
    MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', 50))
    MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
    
    # Настройки видео
    MAX_VIDEO_DURATION = int(os.getenv('MAX_VIDEO_DURATION', 300))  # 5 минут
    CIRCLE_DURATION = int(os.getenv('CIRCLE_DURATION', 10))  # 10 секунд
    CIRCLE_QUALITY = os.getenv('CIRCLE_QUALITY', 'medium')  # low, medium, high
    
    # Настройки логирования
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # Пути к временным файлам
    TEMP_DIR = 'temp'
    
    # Размеры видео кружка (Telegram требует квадратное видео)
    CIRCLE_SIZE = {
        'low': 240,     # 240x240
        'medium': 480,  # 480x480 
        'high': 720     # 720x720
    }
    
    @classmethod
    def validate(cls):
        """Проверяет корректность конфигурации"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN не установлен! Проверьте .env файл")
        
        if cls.CIRCLE_DURATION > 60:
            raise ValueError("CIRCLE_DURATION не может быть больше 60 секунд")
        
        if cls.CIRCLE_QUALITY not in cls.CIRCLE_SIZE:
            raise ValueError(f"CIRCLE_QUALITY должно быть одним из: {list(cls.CIRCLE_SIZE.keys())}")
        
        # Создаем временную папку если её нет
        os.makedirs(cls.TEMP_DIR, exist_ok=True)
        
        return True