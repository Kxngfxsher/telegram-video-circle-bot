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
        self.circle_size = Config.CIRCLE_SIZE[Config.CIRCLE_QUALITY]
        
    def get_video_info(self, video_path: str) -> Optional[dict]:
        """Получает информацию о видео файле"""
        try:
            probe = ffmpeg.probe(video_path)
            fmt = probe.get('format', {})
            duration = float(fmt.get('duration', 0) or 0)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)
            
            if video_stream is None:
                logger.error(f"Не найден видео поток в файле: {video_path}")
                return None
                
            width = int(video_stream.get('width', 0))
            height = int(video_stream.get('height', 0))
            
            return {
                'duration': duration,
                'width': width,
                'height': height,
                'video_codec': video_stream.get('codec_name'),
                'audio_codec': audio_stream.get('codec_name') if audio_stream else None,
                'has_audio': audio_stream is not None,
                'fps': eval(video_stream.get('r_frame_rate', '0/1'))
            }
            
        except Exception as e:
            logger.error(f"Ошибка при получении информации о видео: {e}")
            return None
    
    def calculate_start_segment(self, duration: float, target_duration: int) -> Tuple[float, float]:
        """Вычисляет начало и конец сегмента с начала видео"""
        if duration <= target_duration:
            return 0, duration
        start_time = 0
        end_time = min(duration, target_duration)
        return start_time, end_time
    
    def create_scale_filter(self, scale_percent: int) -> str:
        """Создаёт фильтр масштабирования для кружка"""
        size = self.circle_size
        zoom_factor = scale_percent / 100.0
        
        if scale_percent == 100:
            # Обычное масштабирование до квадрата
            return (
                f"scale='if(gt(iw,ih),-1,{size})':'if(gt(ih,iw),-1,{size})':"
                f"force_original_aspect_ratio=increase,crop={size}:{size}"
            )
        
        # Масштабирование с зумом:
        # 1. Сначала масштабируем по максимальной стороне с запасом для зума
        # 2. Потом применяем зум и кадрируем
        intermediate_size = int(size * max(1.2, zoom_factor))  # Даём запас для качества
        
        return (
            f"scale='if(gt(iw,ih),-1,{intermediate_size})':'if(gt(ih,iw),-1,{intermediate_size})':"
            f"force_original_aspect_ratio=increase,"
            f"crop={intermediate_size}:{intermediate_size},"
            f"scale={int(size * zoom_factor)}:{int(size * zoom_factor)},"
            f"crop={size}:{size}"
        )
    
    def create_video_circle(self, input_path: str, output_path: str, target_duration: int, scale_percent: int) -> bool:
        """Создаёт видео кружок с настраиваемым масштабом"""
        try:
            info = self.get_video_info(input_path)
            if not info:
                return False
            
            logger.info(
                f"Обрабатываем видео: {info['width']}x{info['height']}, длительность: {info['duration']:.2f}с, "
                f"видео кодек: {info['video_codec']}, аудио: {info['audio_codec'] or 'нет'}, "
                f"масштаб: {scale_percent}%"
            )
            
            start_time, end_time = self.calculate_start_segment(info['duration'], target_duration)
            segment_duration = max(0.5, end_time - start_time)
            logger.info(
                f"Извлекаем сегмент с начала: {start_time:.2f}с - {end_time:.2f}с (продолжительность: {segment_duration:.2f}с)"
            )
            
            # Создаём фильтр масштабирования с учётом зума
            video_filter = self.create_scale_filter(scale_percent)
            
            in_v = ffmpeg.input(input_path, ss=start_time, t=segment_duration)
            
            # Оптимизированные параметры для Telegram:
            video_params = {
                'vcodec': 'libx264',
                'vf': video_filter,
                'pix_fmt': 'yuv420p',
                'preset': 'medium',
                'crf': '23',
                'maxrate': '2500k',     # Максимальный битрейт 2.5 Mbps
                'bufsize': '5000k',     # Буфер 5 MB
                'movflags': '+faststart'
            }
            
            audio_params = {
                'acodec': 'aac',
                'audio_bitrate': '128k'  # Ограничиваем битрейт аудио
            }
            
            if info['has_audio']:
                # Сохраняем оригинальный звук
                output = ffmpeg.output(
                    in_v.video, in_v.audio,
                    output_path,
                    **video_params,
                    **audio_params,
                    shortest=None
                )
            else:
                # Добавляем немой трек
                silent_audio = ffmpeg.input('anullsrc=r=48000:cl=stereo', f='lavfi')
                output = ffmpeg.output(
                    in_v.video, silent_audio.audio,
                    output_path,
                    **video_params,
                    **audio_params,
                    shortest=None
                )
            
            output = output.global_args('-loglevel', 'error').overwrite_output()
            ffmpeg.run(output, capture_stderr=True)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Видео кружок успешно создан: {output_path}")
                return True
            logger.error(f"FFmpeg не создал файл (пусто): {output_path}")
            return False
        
        except ffmpeg.Error as e:
            stderr = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            logger.error(f"FFmpeg stderr:\n{stderr}")
            return False
        except Exception as e:
            logger.error(f"Ошибка при создании видео кружка: {e}")
            return False
    
    def process_video(self, input_path: str, duration_override: Optional[int] = None, scale_override: Optional[int] = None) -> Optional[str]:
        """Основной метод для обработки видео с персональными настройками"""
        try:
            os.makedirs(self.temp_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False, dir=self.temp_dir) as temp_file:
                output_path = temp_file.name
            if not os.path.exists(input_path):
                logger.error(f"Входной файл не найден: {input_path}")
                return None
            
            # Используем персональные настройки или по умолчанию
            target_duration = duration_override if duration_override is not None else Config.CIRCLE_DURATION
            target_scale = scale_override if scale_override is not None else 100
            
            if self.create_video_circle(input_path, output_path, target_duration, target_scale):
                return output_path
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