# ============================================
# VMMO Bot - Watchdog Module (requests version)
# ============================================
# Защита от зависания: отслеживает время без активности
# и принудительно выходит из застревания
# ============================================

import time
import os
import signal

from requests_bot.config import (
    WATCHDOG_TIMEOUT, WATCHDOG_CYCLE_THRESHOLD, NO_PROGRESS_LIMIT, DUNGEONS_URL,
    AUTO_RECOVERY_TIMEOUT
)

# Глобальное состояние
_last_action_time = time.time()
_watchdog_trigger_count = 0
_consecutive_no_progress = 0  # Счётчик атак без прогресса

# Трекинг прогресса для авторестарта
_last_progress_time = time.time()  # Время последнего реального прогресса
_dungeons_completed = 0  # Счётчик завершённых данженов в сессии
_items_processed = 0  # Счётчик обработанных предметов


def reset_watchdog():
    """
    Сбрасывает watchdog таймер.
    Вызывать после каждого успешного действия:
    - Вход в данжен
    - Атака по врагу
    - Сбор лута
    - Переход на следующий этап
    """
    global _last_action_time, _watchdog_trigger_count
    _last_action_time = time.time()
    _watchdog_trigger_count = 0  # Успешное действие сбрасывает счётчик циклов


def get_watchdog_idle_time():
    """Возвращает время в секундах с последнего успешного действия"""
    return time.time() - _last_action_time


def is_watchdog_triggered():
    """Проверяет, сработал ли watchdog (90+ секунд без активности)"""
    return get_watchdog_idle_time() >= WATCHDOG_TIMEOUT


def increment_watchdog_cycle():
    """
    Увеличивает счётчик срабатываний watchdog.
    Возвращает True если достигнут порог цикла (5+ срабатываний).
    """
    global _watchdog_trigger_count
    _watchdog_trigger_count += 1
    return _watchdog_trigger_count >= WATCHDOG_CYCLE_THRESHOLD


def get_watchdog_cycle_count():
    """Возвращает текущее количество срабатываний watchdog подряд"""
    return _watchdog_trigger_count


def reset_watchdog_cycle():
    """Принудительно сбрасывает счётчик циклов watchdog"""
    global _watchdog_trigger_count
    _watchdog_trigger_count = 0


# Счётчик атак без прогресса (для боя)
def reset_no_progress_counter():
    """Сбрасывает счётчик атак без прогресса"""
    global _consecutive_no_progress
    _consecutive_no_progress = 0


def increment_no_progress():
    """
    Увеличивает счётчик атак без прогресса.
    Возвращает True если достигнут лимит.
    """
    global _consecutive_no_progress
    _consecutive_no_progress += 1
    return _consecutive_no_progress >= NO_PROGRESS_LIMIT


def get_no_progress_count():
    """Возвращает количество атак без прогресса"""
    return _consecutive_no_progress


def check_watchdog(client, popups_client=None):
    """
    Проверяет watchdog и выполняет восстановление при необходимости.

    Args:
        client: VMMOClient
        popups_client: PopupsClient (опционально)

    Returns:
        None если всё ок
        "recovered" если восстановились
        "hard_reset" если потребовался hard reset
    """
    if not is_watchdog_triggered():
        return None

    idle_time = int(get_watchdog_idle_time())
    cycle_count = get_watchdog_cycle_count()

    # Проверяем цикл застревания
    if increment_watchdog_cycle():
        print(f"[WATCHDOG] {cycle_count + 1} срабатываний подряд — HARD RESET!")

        # Hard reset - просто идём на страницу данженов
        client.get(DUNGEONS_URL)

        reset_watchdog_cycle()
        reset_watchdog()
        return "hard_reset"

    print(f"[WATCHDOG] Бот простаивает {idle_time} сек (попытка {cycle_count + 1}/{WATCHDOG_CYCLE_THRESHOLD})")

    # Пробуем выйти из застревания
    if popups_client:
        popups_client.emergency_unstuck()
    else:
        # Без popups_client просто идём в данжены
        client.get(DUNGEONS_URL)

    reset_watchdog()
    return "recovered"


# ============================================
# Авторестарт при отсутствии прогресса
# ============================================

def mark_progress(action_type: str = "generic"):
    """
    Отмечает реальный прогресс бота.
    Вызывать при:
    - Завершении данжена
    - Обработке предметов (продажа/разборка)
    - Завершении крафта
    - Сборе почты
    """
    global _last_progress_time, _dungeons_completed, _items_processed
    _last_progress_time = time.time()

    if action_type == "dungeon":
        _dungeons_completed += 1
    elif action_type == "item":
        _items_processed += 1


def get_time_since_progress() -> int:
    """Возвращает секунды с последнего реального прогресса"""
    return int(time.time() - _last_progress_time)


def reset_progress_tracking():
    """Сбрасывает трекинг прогресса (вызывать при старте бота)"""
    global _last_progress_time, _dungeons_completed, _items_processed
    _last_progress_time = time.time()
    _dungeons_completed = 0
    _items_processed = 0


def check_auto_recovery() -> bool:
    """
    Проверяет, нужен ли авторестарт бота.

    Returns:
        True если бот должен перезапуститься
    """
    time_since = get_time_since_progress()

    if time_since >= AUTO_RECOVERY_TIMEOUT:
        minutes = time_since // 60
        print(f"[AUTO-RECOVERY] Нет прогресса {minutes} мин! Требуется рестарт.")
        return True

    return False


def trigger_auto_restart():
    """
    Инициирует авторестарт бота.
    Перезапускает текущий процесс через os.execv().
    """
    import sys

    print("[AUTO-RECOVERY] Инициирую авторестарт бота...")

    # Получаем текущие аргументы командной строки
    python = sys.executable
    args = sys.argv[:]

    # Удаляем lock файл перед рестартом
    try:
        from requests_bot.config import get_profile
        profile = get_profile()
        if profile:
            lock_file = f"profiles/{profile}/.lock"
            if os.path.exists(lock_file):
                os.remove(lock_file)
                print(f"[AUTO-RECOVERY] Удалён lock файл: {lock_file}")
    except Exception as e:
        print(f"[AUTO-RECOVERY] Ошибка удаления lock: {e}")

    print(f"[AUTO-RECOVERY] Перезапуск: {python} {' '.join(args)}")

    # Перезапускаем процесс
    os.execv(python, [python] + args)
