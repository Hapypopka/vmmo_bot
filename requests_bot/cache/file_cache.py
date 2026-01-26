# ============================================
# VMMO File Cache Base
# ============================================
# Базовый класс для JSON кэширования
# Используется в: auction.py, craft_prices.py, sell_resources.py
# ============================================

import os
import json
import time
from typing import Any, Dict, Optional
from pathlib import Path

# Логирование
try:
    from requests_bot.logger import log_debug, log_warning, log_error
except ImportError:
    def log_debug(msg): pass
    def log_warning(msg): print(f"[WARN] {msg}")
    def log_error(msg): print(f"[ERROR] {msg}")


class FileCache:
    """
    Базовый класс для файлового кэша JSON.

    Attributes:
        file_path: Путь к файлу кэша
        ttl: Время жизни кэша в секундах (0 = бесконечно)
        name: Имя кэша для логов
    """

    def __init__(self, file_path: str, ttl: int = 0, name: str = "CACHE"):
        """
        Args:
            file_path: Путь к файлу кэша
            ttl: Время жизни записей в секундах (0 = без ограничения)
            name: Имя для логирования
        """
        self.file_path = file_path
        self.ttl = ttl
        self.name = name
        self._cache: Optional[Dict] = None

    def load(self) -> Dict:
        """
        Загружает данные из файла кэша.

        Returns:
            Dict: Данные кэша или пустой словарь при ошибке
        """
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                    return self._cache
        except json.JSONDecodeError as e:
            log_error(f"[{self.name}] Ошибка парсинга кэша: {e}")
        except Exception as e:
            log_warning(f"[{self.name}] Ошибка чтения кэша: {e}")

        self._cache = {}
        return self._cache

    def save(self, data: Dict = None):
        """
        Сохраняет данные в файл кэша.

        Args:
            data: Данные для сохранения (если None - сохраняет текущий кэш)
        """
        if data is not None:
            self._cache = data

        if self._cache is None:
            return

        try:
            # Создаём директорию если нет
            dir_path = os.path.dirname(self.file_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)

            log_debug(f"[{self.name}] Кэш сохранён: {self.file_path}")
        except Exception as e:
            log_error(f"[{self.name}] Ошибка записи кэша: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Получает значение из кэша.

        Args:
            key: Ключ
            default: Значение по умолчанию

        Returns:
            Значение или default
        """
        if self._cache is None:
            self.load()

        return self._cache.get(key, default)

    def set(self, key: str, value: Any, save: bool = True):
        """
        Устанавливает значение в кэше.

        Args:
            key: Ключ
            value: Значение
            save: Сохранять сразу в файл
        """
        if self._cache is None:
            self.load()

        self._cache[key] = value

        if save:
            self.save()

    def delete(self, key: str, save: bool = True):
        """Удаляет ключ из кэша"""
        if self._cache is None:
            self.load()

        if key in self._cache:
            del self._cache[key]
            if save:
                self.save()

    def clear(self, save: bool = True):
        """Очищает кэш"""
        self._cache = {}
        if save:
            self.save()

    def exists(self) -> bool:
        """Проверяет существование файла кэша"""
        return os.path.exists(self.file_path)

    @property
    def data(self) -> Dict:
        """Возвращает все данные кэша"""
        if self._cache is None:
            self.load()
        return self._cache


class JSONCache(FileCache):
    """
    Расширенный кэш с поддержкой TTL и временных меток.

    Формат записей:
    {
        "key": {
            "value": <any>,
            "timestamp": <unix_time>
        }
    }
    """

    def get_with_timestamp(self, key: str) -> tuple[Any, float]:
        """
        Получает значение и timestamp.

        Returns:
            (value, timestamp) или (None, 0) если не найдено
        """
        if self._cache is None:
            self.load()

        entry = self._cache.get(key, {})
        if isinstance(entry, dict) and "value" in entry:
            return entry.get("value"), entry.get("timestamp", 0)

        return None, 0

    def get_if_fresh(self, key: str, max_age: int = None) -> Optional[Any]:
        """
        Получает значение только если оно свежее.

        Args:
            key: Ключ
            max_age: Максимальный возраст в секундах (если None - использует self.ttl)

        Returns:
            Значение или None если устарело/не найдено
        """
        value, timestamp = self.get_with_timestamp(key)

        if value is None:
            return None

        ttl = max_age if max_age is not None else self.ttl
        if ttl > 0:
            age = time.time() - timestamp
            if age > ttl:
                log_debug(f"[{self.name}] Кэш '{key}' устарел ({age/3600:.1f}ч)")
                return None

        return value

    def set_with_timestamp(self, key: str, value: Any, save: bool = True):
        """
        Устанавливает значение с текущим timestamp.

        Args:
            key: Ключ
            value: Значение
            save: Сохранять сразу
        """
        if self._cache is None:
            self.load()

        self._cache[key] = {
            "value": value,
            "timestamp": time.time()
        }

        if save:
            self.save()

    def get_age(self, key: str) -> float:
        """
        Возвращает возраст записи в секундах.

        Returns:
            Возраст в секундах или float('inf') если не найдено
        """
        _, timestamp = self.get_with_timestamp(key)
        if timestamp == 0:
            return float('inf')
        return time.time() - timestamp

    def is_stale(self, key: str, max_age: int = None) -> bool:
        """
        Проверяет устарела ли запись.

        Args:
            key: Ключ
            max_age: Максимальный возраст (если None - использует self.ttl)

        Returns:
            True если устарела или не найдена
        """
        age = self.get_age(key)
        ttl = max_age if max_age is not None else self.ttl
        return age > ttl if ttl > 0 else False

    def cleanup_stale(self, max_age: int = None, save: bool = True):
        """
        Удаляет устаревшие записи.

        Args:
            max_age: Максимальный возраст
            save: Сохранять после очистки
        """
        if self._cache is None:
            self.load()

        ttl = max_age if max_age is not None else self.ttl
        if ttl <= 0:
            return

        now = time.time()
        stale_keys = []

        for key, entry in self._cache.items():
            if isinstance(entry, dict) and "timestamp" in entry:
                age = now - entry["timestamp"]
                if age > ttl:
                    stale_keys.append(key)

        for key in stale_keys:
            del self._cache[key]
            log_debug(f"[{self.name}] Удалена устаревшая запись: {key}")

        if stale_keys and save:
            self.save()
