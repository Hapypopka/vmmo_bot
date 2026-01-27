# ============================================
# VMMO Craft Distribution
# ============================================
# Распределение крафта между ботами
# Локи, квоты, координация
# ============================================

import os
import sys
import time
import json

from requests_bot.config import CRAFT_LOCK_TTL

# Путь к файлу локов крафта (распределение между ботами)
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CRAFT_LOCKS_FILE = os.path.join(SCRIPT_DIR, "shared_craft_locks.json")
CRAFT_LOCKS_LOCKFILE = os.path.join(SCRIPT_DIR, "shared_craft_locks.lock")

# Алиас для обратной совместимости
LOCK_TTL = CRAFT_LOCK_TTL

# File lock для атомарных операций (кроссплатформенный)
if sys.platform == 'win32':
    import msvcrt

    class FileLock:
        """Кроссплатформенный file lock для Windows"""
        def __init__(self, lockfile):
            self.lockfile = lockfile
            self.fd = None

        def __enter__(self):
            self.fd = open(self.lockfile, 'w')
            msvcrt.locking(self.fd.fileno(), msvcrt.LK_LOCK, 1)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
            self.fd.close()
            return False
else:
    import fcntl

    class FileLock:
        """Простой file lock для синхронизации между процессами (Linux/Mac)"""
        def __init__(self, lockfile):
            self.lockfile = lockfile
            self.fd = None

        def __enter__(self):
            self.fd = open(self.lockfile, 'w')
            fcntl.flock(self.fd, fcntl.LOCK_EX)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.fd.close()
            return False


# Все профитные рецепты для автовыбора
# Исключены: copperOre (убыточная), twilightSteel/twilightAnthracite (требуют сапфиры/рубины)
FINAL_RECIPES = [
    "ironBar",       # Железный Слиток
    "copperBar",     # Медный Слиток
    "bronzeBar",     # Бронзовый Слиток
    "platinumBar",   # Платиновый Слиток
    "thorBar",       # Слиток Тора
    "bronze",        # Бронза
    "iron",          # Железо
    "platinum",      # Платина
    "rawOre",        # Железная Руда
    "thor",          # Тор
    "copper",        # Медь
]


def load_craft_locks():
    """
    Загружает локи крафта из файла.

    Returns:
        dict: {profile: {"recipe_id": "ironBar", "timestamp": 123456789}, ...}
    """
    if not os.path.exists(CRAFT_LOCKS_FILE):
        return {}

    try:
        with open(CRAFT_LOCKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка чтения локов: {e}")
        return {}


def save_craft_locks(locks):
    """Сохраняет локи крафта в файл."""
    try:
        with open(CRAFT_LOCKS_FILE, "w", encoding="utf-8") as f:
            json.dump(locks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка сохранения локов: {e}")


def get_recipe_bot_counts():
    """
    Подсчитывает сколько активных ботов на каждом рецепте.
    Протухшие локи (>2ч) не считаются.

    Returns:
        dict: {recipe_id: count, ...}
    """
    locks = load_craft_locks()
    now = time.time()
    counts = {recipe: 0 for recipe in FINAL_RECIPES}

    for profile, lock_info in locks.items():
        recipe_id = lock_info.get("recipe_id")
        if not recipe_id or recipe_id not in FINAL_RECIPES:
            continue

        timestamp = lock_info.get("timestamp", 0)
        if now - timestamp > LOCK_TTL:
            continue  # Протух - не считаем

        counts[recipe_id] = counts.get(recipe_id, 0) + 1

    return counts


def refresh_craft_lock(profile, recipe_id):
    """
    Обновляет timestamp лока (вызывать при продаже партии).

    Args:
        profile: имя профиля
        recipe_id: ID рецепта
    """
    try:
        with FileLock(CRAFT_LOCKS_LOCKFILE):
            locks = load_craft_locks()
            now = time.time()

            # Получаем оптимальный batch_size для этого рецепта
            try:
                from requests_bot.craft_prices import get_optimal_batch_size
                batch = get_optimal_batch_size(recipe_id)
            except Exception:
                batch = 5  # fallback

            locks[profile] = {"recipe_id": recipe_id, "timestamp": now, "current": 0, "batch": batch}
            save_craft_locks(locks)
            print(f"[CRAFT_LOCKS] {profile}: обновил лок на {recipe_id}")
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка refresh_craft_lock: {e}")


def update_craft_progress(profile, recipe_id, current_count, batch_size):
    """
    Обновляет прогресс крафта (текущее количество / цель).

    Args:
        profile: имя профиля
        recipe_id: ID рецепта
        current_count: текущее количество в инвентаре
        batch_size: целевое количество для партии
    """
    try:
        with FileLock(CRAFT_LOCKS_LOCKFILE):
            locks = load_craft_locks()
            now = time.time()

            locks[profile] = {
                "recipe_id": recipe_id,
                "timestamp": now,
                "current": current_count,
                "batch": batch_size
            }
            save_craft_locks(locks)
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка update_craft_progress: {e}")


def release_craft_lock(profile):
    """
    Освобождает лок профиля (опционально, при остановке бота).

    Args:
        profile: имя профиля
    """
    try:
        with FileLock(CRAFT_LOCKS_LOCKFILE):
            locks = load_craft_locks()

            if profile in locks:
                recipe_id = locks[profile].get("recipe_id")
                del locks[profile]
                save_craft_locks(locks)
                print(f"[CRAFT_LOCKS] {profile}: освободил {recipe_id}")
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка release_craft_lock: {e}")
