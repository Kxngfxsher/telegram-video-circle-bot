import os
import tempfile
import logging
import ffmpeg
from typing import Optional, Tuple
from config import Config

logger = logging.getLogger(__name__)

class VideoProcessor:
    """Класс для обработки видео файлов"""
    
    def __init__(self):
        self.temp_dir = Config.TEMP_DIR
        self.circle_duration = Config.CIRCLE_DURATION
        self.circle_size = Config.CIRCLE_SIZE[Config.CIRCLE_QUALITY]
        
    def get_video_info(self, video_path: str) -> Optional[dict]:
        """Получает информацию о видео файле"""
        try:
            probe = ffmpeg.probe(video_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream is None:
                logger.error(f"Не найден видео поток в файле: {video_path}")
                return None
                
            duration = float(video_stream.get('duration', 0))
            width = int(video_stream.get('width', 0))
            height = int(video_stream.get('height', 0))
            
            return {
                'duration': duration,
                'width': width,
                'height': height,
                'codec': video_stream.get('codec_name'),
                'fps': eval(video_stream.get('r_frame_rate', '0/1'))
            }
            
        except Exception as e:
            logger.error(f"Ошибка при получении информации о видео: {e}")
            return None
    
    def calculate_middle_segment(self, duration: float) -> Tuple[float, float]:
        """Вычисляет начало и конец среднего сегмента видео"""
        # Если видео короче желаемой продолжительности кружка
        if duration <= self.circle_duration:
            return 0, duration
        
        # Находим середину видео
        middle = duration / 2
        
        # Вычисляем начало сегмента
        start_time = max(0, middle - self.circle_duration / 2)
        end_time = min(duration, start_time + self.circle_duration)
        
        # Корректируем, если вышли за границы
        if end_time == duration:
            start_time = max(0, duration - self.circle_duration)
            
        return start_time, end_time
    
    def create_video_circle(self, input_path: str, output_path: str) -> bool:
        """Создаёт видео кружок из входного видео"""
        try:
            # Получаем информацию о видео
            video_info = self.get_video_info(input_path)
            if not video_info:
                return False
            
            logger.info(f"Обрабатываем видео: {video_info['width']}x{video_info['height']}, "
                       f"продолжительность: {video_info['duration']:.2f}с")
            
            # Вычисляем средний сегмент
            start_time, end_time = self.calculate_middle_segment(video_info['duration'])
            segment_duration = end_time - start_time
            
            logger.info(f"Извлекаем сегмент: {start_time:.2f}с - {end_time:.2f}с "
                       f"(продолжительность: {segment_duration:.2f}с)")
            
            # Создаём ffmpeg команду
            input_stream = ffmpeg.input(input_path, ss=start_time, t=segment_duration)
            
            # Применяем фильтры:
            # 1. Масштабируем до нужного размера с сохранением пропорций
            # 2. Обрезаем до квадрата
            output_stream = (
                input_stream
                .video
                .filter('scale', f'{self.circle_size}:{self.circle_size}:force_original_aspect_ratio=increase')
                .filter('crop', self.circle_size, self.circle_size)
            )
            
            # Сохраняем в файл
            output_stream = ffmpeg.output(
                output_stream,
                output_path,
                vcodec='libx264',
                acodec='aac',
                **{
                    'movflags': '+faststart',  # Оптимизация для стриминга
                    'pix_fmt': 'yuv420p',     # Совместимость с большинством плееров
                    'preset': 'medium',       # Баланс скорости и качества
                    'crf': '23'              # Качество (18-28, меньше = лучше)
                }
            )
            
            # Выполняем конвертацию
            ffmpeg.run(output_stream, overwrite_output=True, quiet=True)
            
            # Проверяем, что файл создался успешно
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Видео кружок успешно создан: {output_path}")
                return True
            else:
                logger.error(f"Не удалось создать видео кружок: {output_path}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при создании видео кружка: {e}")
            return False
    
    def process_video(self, input_path: str) -> Optional[str]:
        """Основной метод для обработки видео"""
        try:
            # Создаём временный файл для выходного видео
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False, dir=self.temp_dir) as temp_file:
                output_path = temp_file.name
            
            # Проверяем, что входной файл существует
            if not os.path.exists(input_path):
                logger.error(f"Входной файл не найден: {input_path}")
                return None
            
            # Создаём видео кружок
            if self.create_video_circle(input_path, output_path):
                return output_path
            else:
                # Удаляем неудачный файл
                if os.path.exists(output_path):
                    os.unlink(output_path)
                return None
                
        except Exception as e:
            logger.error(f"Ошибка при обработке видео: {e}")
            return None
    
    def cleanup_temp_file(self, file_path: str):
        """Удаляет временный файл"""
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug(f"Временный файл удалён: {file_path}")
        except Exception as e:
            logger.warning(f"Не удалось удалить временный файл {file_path}: {e}")