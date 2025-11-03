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
            fmt = probe.get('format', {})
            duration = float(fmt.get('duration', 0) or 0)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream is None:
                logger.error(f"Не найден видео поток в файле: {video_path}")
                return None
                
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
    
    def calculate_start_segment(self, duration: float) -> Tuple[float, float]:
        """Вычисляет начало и конец сегмента с начала видео"""
        # Если видео короче желаемой продолжительности кружка
        if duration <= self.circle_duration:
            return 0, duration
        
        # Берём с начала видео нужную длительность
        start_time = 0
        end_time = min(duration, self.circle_duration)
        
        return start_time, end_time
    
    def create_video_circle(self, input_path: str, output_path: str) -> bool:
        """Создаёт видео кружок из входного видео (надёжный пайплайн)"""
        try:
            # Получаем информацию о видео
            video_info = self.get_video_info(input_path)
            if not video_info:
                return False
            
            logger.info(f"Обрабатываем видео: {video_info['width']}x{video_info['height']}, "
                       f"продолжительность: {video_info['duration']:.2f}с")
            
            # Вычисляем сегмент с начала видео
            start_time, end_time = self.calculate_start_segment(video_info['duration'])
            segment_duration = max(0.5, end_time - start_time)  # не меньше 0.5 сек
            
            logger.info(f"Извлекаем сегмент с начала: {start_time:.2f}с - {end_time:.2f}с "
                       f"(продолжительность: {segment_duration:.2f}с)")
            
            size = self.circle_size  # 240/480/720
            
            # Пайплайн для конвертации:
            # 1. Обрезаем с начала видео нужную длительность
            # 2. Масштабируем с сохранением пропорций
            # 3. Обрезаем до квадрата
            # 4. Добавляем немое аудио, если нужно
            
            video_filter = (
                f"scale='if(gt(iw,ih),-1,{size})':'if(gt(ih,iw),-1,{size})':"
                f"force_original_aspect_ratio=increase,"
                f"crop={size}:{size}"
            )
            
            # Создаём команду конвертации
            input_video = ffmpeg.input(input_path, ss=start_time, t=segment_duration)
            silent_audio = ffmpeg.input('anullsrc=r=48000:cl=stereo', f='lavfi')
            
            output = ffmpeg.output(
                input_video.video,
                silent_audio.audio,
                output_path,
                vcodec='libx264',
                acodec='aac',
                vf=video_filter,
                pix_fmt='yuv420p',
                preset='medium',
                crf=23,
                movflags='+faststart',
                shortest=None  # обрезаем по короткому потоку (видео)
            ).global_args('-loglevel', 'error').overwrite_output()
            
            # Выполняем конвертацию
            ffmpeg.run(output, capture_stderr=True)
            
            # Проверяем, что файл создался успешно
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Видео кружок успешно создан: {output_path}")
                return True
            else:
                logger.error(f"FFmpeg не создал файл (пусто): {output_path}")
                return False
                
        except ffmpeg.Error as e:
            stderr = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            logger.error(f"FFmpeg stderr:\n{stderr}")
            return False
        except Exception as e:
            logger.error(f"Ошибка при создании видео кружка: {e}")
            return False
    
    def process_video(self, input_path: str) -> Optional[str]:
        """Основной метод для обработки видео"""
        try:
            # Убеждаемся, что temp каталог существует
            os.makedirs(self.temp_dir, exist_ok=True)
            
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