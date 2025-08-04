#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import logging
import shutil
from typing import List, Tuple, Dict, Optional
from collections import defaultdict
from datetime import datetime

import pytesseract
from PIL import Image
from bs4 import BeautifulSoup
import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext

# ==================== Конфигурация ====================
LOG_DIR = "spotify_importer_logs"
SUCCESS_LOG = os.path.join(LOG_DIR, "success.log")
SYSTEM_LOG = os.path.join(LOG_DIR, "system.log")
FILTERED_LOG = os.path.join(LOG_DIR, "filtered.log")
NOT_FOUND_LOG = os.path.join(LOG_DIR, "not_found.log")

# Очистка старых логов
if os.path.exists(LOG_DIR):
    shutil.rmtree(LOG_DIR)
os.makedirs(LOG_DIR)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(SYSTEM_LOG),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()


# ==================== Класс валидации треков ====================
class TrackValidator:
    """Класс для проверки и нормализации названий треков"""

    @staticmethod
    def validate_track(line: str) -> Tuple[bool, str]:
        """Проверяет валидность строки как музыкального трека"""
        # Удаляем расширения файлов
        cleaned = re.sub(r'\.(mp3|wav|flac|m4a|vk|com|remix)$', '', line, flags=re.IGNORECASE)
        cleaned = re.sub(r'[\(\)\[\]\{\}]', '', cleaned).strip()

        if len(cleaned) < 5:
            return False, "Слишком короткая строка"

        # Проверяем наличие ключевых элементов трека
        has_artist = re.search(r'[a-zA-Zа-яА-Я]{3,}', cleaned) is not None
        has_title = re.search(r'[a-zA-Zа-яА-Я]{3,}', cleaned.replace("feat", "")) is not None
        has_separator = re.search(r'[-–—]|ft|feat|vs|with', cleaned) is not None

        if not (has_artist and has_title and has_separator):
            return False, "Не соответствует формату трека"

        return True, ""

    @staticmethod
    def normalize_track(track: str) -> str:
        """Нормализует название трека для поиска"""
        # Удаляем расширения файлов и техническую информацию
        track = re.sub(r'\.(mp3|wav|flac|m4a|vk|com)(?:\s*\(\w+\))?', '', track, flags=re.IGNORECASE)
        track = track.replace('_', ' ')

        # Стандартизируем featuring-нотацию
        track = re.sub(r'\s*[/xX×]\s+|\s+ft\.?\s+|\s+feat\.?\s+|\s+featuring\s+', ' feat. ', track, flags=re.IGNORECASE)

        # Обработка DJ и ремиксов
        track = re.sub(r'\b(DJ|dj|djs)\b\s*([a-zA-Z])', r'\1 \2', track)
        track = re.sub(r'\s*(cover|version|remix|mix|bachata)\b', r' \1', track, flags=re.IGNORECASE)

        # Стандартизируем разделители
        track = re.sub(r'\s*[–—\-:]\s*', ' - ', track)

        # Удаляем специальные символы, сохраняя буквы и основные знаки
        track = re.sub(r'[^\w\s.,!?&\'"\u0400-\u04FF-]', '', track)

        return ' '.join(track.split()).strip()


# ==================== Класс извлечения треков ====================
class TrackExtractor:
    """Класс для извлечения треков из разных форматов файлов"""

    @staticmethod
    def from_html(path: str) -> List[str]:
        """Извлекает треки из HTML файла"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f, "html.parser")
            text = soup.get_text(separator="\n")
            return TrackExtractor._filter_tracks(text.splitlines())
        except Exception as e:
            logger.error(f"Ошибка обработки HTML: {str(e)}")
            return []

    @staticmethod
    def from_image(path: str) -> List[str]:
        """Извлекает треки из изображения с помощью OCR"""
        try:
            image = Image.open(path)
            text = pytesseract.image_to_string(image, lang="eng+rus")
            return TrackExtractor._filter_tracks(text.splitlines())
        except Exception as e:
            logger.error(f"Ошибка OCR: {str(e)}")
            return []

    @staticmethod
    def from_text(path: str) -> List[str]:
        """Извлекает треки из текстового файла"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return TrackExtractor._filter_tracks(lines)
        except Exception as e:
            logger.error(f"Ошибка чтения файла: {str(e)}")
            return []

    @staticmethod
    def _filter_tracks(lines: List[str]) -> List[str]:
        """Фильтрует и нормализует список треков"""
        valid_tracks = []
        seen = set()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            is_valid, reason = TrackValidator.validate_track(line)
            if not is_valid:
                with open(FILTERED_LOG, 'a', encoding='utf-8') as f:
                    cleaned = TrackValidator.normalize_track(line)
                    f.write(
                        f"[{datetime.now()}] "
                        f"{reason} | "
                        f"Оригинал: {line} | "
                        f"После очистки: {cleaned}\n"
                    )
                continue

            normalized = TrackValidator.normalize_track(line)
            if normalized and normalized not in seen:
                seen.add(normalized)
                valid_tracks.append(normalized)

        return valid_tracks


# ==================== Класс работы с Spotify ====================
class SpotifyManager:
    """Класс для взаимодействия с API Spotify"""

    BATCH_SIZE = 100

    def __init__(self):
        try:
            self.sp = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
                    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
                    redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
                    scope="playlist-modify-public playlist-modify-private",
                )
            )
            logger.info("Успешная аутентификация в Spotify")
        except Exception as e:
            logger.error(f"Ошибка аутентификации: {str(e)}")
            raise

    def search_track(self, query: str) -> Tuple[Optional[str], str]:
        """Поиск трека в Spotify с расширенным логированием"""
        try:
            # Генерация вариантов запросов
            queries = [
                query,
                re.sub(r'\s+feat\.\s+', ' ', query),
                re.sub(r'[^\w\s]', '', query),
                query.split(' - ')[0] if ' - ' in query else query
            ]

            for q in queries:
                results = self.sp.search(q=q, type="track", limit=5)
                items = results.get("tracks", {}).get("items", [])

                if items:
                    # Лучшее совпадение по названию и исполнителю
                    for item in items:
                        if self._is_good_match(query, item):
                            return item["uri"], "Точное совпадение"

                    # Возвращаем первый результат если точного совпадения нет
                    return items[0]["uri"], "Частичное совпадение"

            # Если ничего не найдено
            with open(NOT_FOUND_LOG, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now()}] Не найден трек | Запрос: {query}\n")

            return None, "Трек не найден"

        except Exception as e:
            logger.error(f"Ошибка поиска: {query} - {str(e)}")
            return None, f"Ошибка поиска: {str(e)}"

    def _is_good_match(self, query: str, item: dict) -> bool:
        """Проверяет качество совпадения трека"""
        query_lower = query.lower()
        title_match = item['name'].lower() in query_lower
        artist_match = any(
            artist['name'].lower() in query_lower
            for artist in item['artists']
        )
        return title_match and artist_match

    def create_playlist(self, user_id: str, name: str, description: str = "") -> str:
        """Создает новый плейлист"""
        try:
            playlist = self.sp.user_playlist_create(
                user=user_id,
                name=name,
                public=False,
                description=description
            )
            logger.info(f"Создан плейлист: {name}")
            return playlist["id"]
        except Exception as e:
            logger.error(f"Ошибка создания плейлиста: {str(e)}")
            raise

    def add_tracks(self, playlist_id: str, uris: List[str]) -> None:
        """Добавляет треки в плейлист"""
        try:
            for i in range(0, len(uris), self.BATCH_SIZE):
                batch = uris[i:i + self.BATCH_SIZE]
                self.sp.playlist_add_items(playlist_id, batch)

                # Подробное логирование добавленных треков
                for uri in batch:
                    try:
                        track_info = self.sp.track(uri)
                        with open(SUCCESS_LOG, 'a', encoding='utf-8') as f:
                            f.write(
                                f"[{datetime.now()}] Успешно добавлен | "
                                f"Исполнитель: {', '.join(a['name'] for a in track_info['artists'])} | "
                                f"Название: {track_info['name']} | "
                                f"ID: {uri.split(':')[-1]} | "
                                f"Длительность: {track_info['duration_ms'] // 1000} сек\n"
                            )
                    except Exception as e:
                        logger.error(f"Не удалось получить информацию о треке {uri}: {str(e)}")
        except Exception as e:
            logger.error(f"Ошибка добавления треков: {str(e)}")
            raise

    def get_current_user(self) -> dict:
        """Возвращает информацию о текущем пользователе"""
        try:
            return self.sp.current_user()
        except Exception as e:
            logger.error(f"Ошибка получения пользователя: {str(e)}")
            raise


# ==================== Основной класс приложения ====================
class SpotifyImporterApp:
    """Главный класс приложения с графическим интерфейсом"""

    def __init__(self, root):
        self.root = root
        self._setup_window()
        self.spotify = SpotifyManager()
        self._setup_ui()
        self._check_ocr()

        self.raw_tracks = []
        self.found_uris = []
        self.not_found = []
        self.skipped_stats = defaultdict(int)

    def _setup_window(self):
        """Настраивает основное окно приложения"""
        self.root.title("Spotify Playlist Importer Pro")
        self.root.geometry("1000x800")
        self.root.minsize(900, 700)

        # Принудительное отображение окна
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after(100, lambda: self.root.attributes('-topmost', False))

    def _setup_ui(self):
        """Настраивает пользовательский интерфейс"""
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Заголовок
        ttk.Label(
            main_frame,
            text="🎵 Spotify Playlist Importer Pro",
            font=("Helvetica", 16, "bold")
        ).pack(pady=10)

        # Выбор файла
        file_frame = ttk.LabelFrame(main_frame, text="Выберите файл для обработки", padding=10)
        file_frame.pack(fill=tk.X, pady=10)

        self.file_path_var = tk.StringVar()
        path_frame = ttk.Frame(file_frame)
        path_frame.pack(fill=tk.X)

        self.path_entry = ttk.Entry(
            path_frame,
            textvariable=self.file_path_var,
            state="readonly",
            width=70
        )
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        browse_btn = ttk.Button(
            path_frame,
            text="Обзор...",
            command=self._browse_file,
            width=15
        )
        browse_btn.pack(side=tk.LEFT, padx=5)

        # Название плейлиста
        name_frame = ttk.Frame(main_frame)
        name_frame.pack(fill=tk.X, pady=10)

        ttk.Label(
            name_frame,
            text="Название плейлиста:",
            width=20
        ).pack(side=tk.LEFT)

        self.playlist_name_var = tk.StringVar()
        ttk.Entry(
            name_frame,
            textvariable=self.playlist_name_var,
            width=50
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Лог процесса
        process_frame = ttk.LabelFrame(main_frame, text="Процесс обработки", padding=10)
        process_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        self.process_log = scrolledtext.ScrolledText(
            process_frame,
            wrap=tk.WORD,
            width=100,
            height=25,
            font=('Consolas', 9)
        )
        self.process_log.pack(fill=tk.BOTH, expand=True)

        # Прогресс-бар
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            main_frame,
            variable=self.progress_var,
            maximum=100
        )
        self.progress_bar.pack(fill=tk.X, pady=(10, 0))

        # Кнопки
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)

        self.create_btn = ttk.Button(
            btn_frame,
            text="Создать плейлист",
            command=self._start_import,
            width=20
        )
        self.create_btn.pack(side=tk.LEFT, padx=5)

        self.cancel_btn = ttk.Button(
            btn_frame,
            text="Отмена",
            command=self._cancel_operation,
            state=tk.DISABLED,
            width=15
        )
        self.cancel_btn.pack(side=tk.LEFT)

    def _check_ocr(self):
        """Проверяет доступность OCR"""
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception as e:
            messagebox.showwarning(
                "Предупреждение",
                f"Tesseract OCR не установлен. Обработка изображений будет недоступна.\n{str(e)}"
            )
            return False

    def _browse_file(self):
        """Открывает диалог выбора файла"""
        filetypes = [
            ("Все файлы", "*.*"),
            ("Изображения", "*.png *.jpg *.jpeg"),
            ("HTML файлы", "*.html *.htm"),
            ("Текстовые файлы", "*.txt")
        ]

        file_path = filedialog.askopenfilename(
            title="Выберите файл с треками",
            filetypes=filetypes
        )

        if file_path:
            display_path = file_path
            if len(file_path) > 60:
                parts = file_path.split('/')
                display_path = f".../{'/'.join(parts[-3:])}"
            self.file_path_var.set(display_path)
            self.full_file_path = file_path
            logger.info(f"Выбран файл: {file_path}")

    def _log_message(self, message: str):
        """Добавляет сообщение в лог"""
        self.process_log.insert(tk.END, message + "\n")
        self.process_log.see(tk.END)
        self.root.update()
        logger.info(message)

    def _clear_log(self):
        """Очищает лог"""
        self.process_log.delete(1.0, tk.END)

    def _cancel_operation(self):
        """Отменяет текущую операцию"""
        self._log_message("\n⚠️ Операция прервана пользователем")
        self.create_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.DISABLED)

    def _start_import(self):
        """Основной процесс импорта"""
        self._clear_log()
        self.progress_var.set(0)
        self.create_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.skipped_stats = defaultdict(int)

        try:
            # Проверка ввода
            playlist_name = self.playlist_name_var.get().strip()
            if not playlist_name:
                messagebox.showerror("Ошибка", "Введите название плейлиста")
                return

            if not hasattr(self, 'full_file_path'):
                messagebox.showerror("Ошибка", "Выберите файл для обработки")
                return

            input_path = self.full_file_path

            # Шаг 1: Извлечение треков
            self._log_message("🔍 Извлечение треков из файла...")

            if input_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                self.raw_tracks = TrackExtractor.from_image(input_path)
            elif input_path.lower().endswith(('.html', '.htm')):
                self.raw_tracks = TrackExtractor.from_html(input_path)
            else:
                self.raw_tracks = TrackExtractor.from_text(input_path)

            if not self.raw_tracks:
                self._log_message("❌ Не найдено подходящих треков")
                return

            # Показать превью
            self._log_message(f"\n🔍 Найдено {len(self.raw_tracks)} треков. Предпросмотр:")
            for i, track in enumerate(self.raw_tracks[:10], 1):
                self._log_message(f"  {i}. {track}")

            if not messagebox.askyesno("Подтверждение", f"Найдено {len(self.raw_tracks)} треков. Продолжить?"):
                return

            # Шаг 2: Поиск треков
            self._log_message("\n🔍 Поиск треков в Spotify...")
            self.found_uris = []
            self.not_found = []

            # Поиск треков с прогресс-баром
            for i, track in enumerate(self.raw_tracks, 1):
                uri, status = self.spotify.search_track(track)

                if uri:
                    self.found_uris.append(uri)
                    self._log_message(f"  {i}/{len(self.raw_tracks)}: ✅ Найден - {track} ({status})")
                else:
                    self.not_found.append(track)
                    self._log_message(f"  {i}/{len(self.raw_tracks)}: ❌ Не найден - {track}")

                progress = i / len(self.raw_tracks) * 100
                self.progress_var.set(progress)
                self.root.update()
                time.sleep(0.1)

            # Результаты поиска
            self._log_message(f"\n🎯 Найдено: {len(self.found_uris)}/{len(self.raw_tracks)}")

            if self.not_found:
                self._log_message("\n⚠️ Не найдены:")
                for i, nf in enumerate(self.not_found[:15], 1):
                    self._log_message(f"  {i}. {nf}")
                if len(self.not_found) > 15:
                    self._log_message(f"  ...и ещё {len(self.not_found) - 15}")

            # Шаг 3: Создание плейлиста
            if not self.found_uris:
                messagebox.showwarning("Внимание", "Не найдено треков для добавления")
                return

            self._log_message("\n🚀 Создание плейлиста...")
            user_id = self.spotify.get_current_user()["id"]
            playlist_id = self.spotify.create_playlist(user_id, playlist_name)

            # Шаг 4: Добавление треков
            self._log_message(f"\n📤 Добавление {len(self.found_uris)} треков...")
            self.spotify.add_tracks(playlist_id, self.found_uris)

            self._log_message("\n🎉 Готово! Плейлист создан.")
            messagebox.showinfo("Готово", f"Плейлист '{playlist_name}' успешно создан!")

        except Exception as e:
            self._log_message(f"\n❌ Ошибка: {str(e)}")
            messagebox.showerror("Ошибка", f"Произошла ошибка: {str(e)}")
            logger.error(f"Ошибка импорта: {str(e)}", exc_info=True)
        finally:
            self.create_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)


# ==================== Запуск приложения ====================
if __name__ == "__main__":
    try:
        # Проверка окружения для Linux
        if not os.environ.get('DISPLAY') and os.name == 'posix':
            os.environ['DISPLAY'] = ':0'

        root = tk.Tk()
        app = SpotifyImporterApp(root)
        root.mainloop()
    except Exception as e:
        logger.critical(f"Фатальная ошибка: {str(e)}", exc_info=True)
        messagebox.showerror("Критическая ошибка", f"Приложение не может быть запущено: {str(e)}")