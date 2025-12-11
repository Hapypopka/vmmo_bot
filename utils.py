# ============================================
# VMMO Bot - Utility Functions
# ============================================

import time
import random
import re
import os
from datetime import datetime

# ========== ЛОГИРОВАНИЕ В ФАЙЛ ==========
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = None


def init_logging():
    """Инициализирует логирование в файл"""
    global LOG_FILE
    os.makedirs(LOG_DIR, exist_ok=True)
    log_filename = datetime.now().strftime("bot_%Y-%m-%d_%H-%M-%S.log")
    LOG_FILE = os.path.join(LOG_DIR, log_filename)
    write_log("=== Логирование запущено ===")


def write_log(message):
    """Записывает сообщение в лог-файл"""
    if LOG_FILE:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except:
            pass


def save_debug_screenshot(page, reason="error"):
    """Сохраняет скриншот для дебага"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(LOG_DIR, f"screenshot_{reason}_{timestamp}.png")
        page.screenshot(path=filename)
        write_log(f"📸 Скриншот сохранён: {filename}")
        return filename
    except Exception as e:
        write_log(f"❌ Не удалось сохранить скриншот: {e}")
        return None


def log_error(message, page=None):
    """Логирует ошибку + делает скриншот"""
    error_msg = f"❌ ERROR: {message}"
    print(error_msg)
    write_log(error_msg)
    if page:
        save_debug_screenshot(page, "error")


# ========== WATCHDOG СИСТЕМА ==========
# Глобальный таймер для отслеживания активности бота
_last_action_time = time.time()
WATCHDOG_TIMEOUT = 90  # 90 секунд без активности = застревание (было 120)

# Счётчик последовательных срабатываний watchdog для детекции циклов
_watchdog_trigger_count = 0
WATCHDOG_CYCLE_THRESHOLD = 5  # После 5 срабатываний подряд — принудительный hard reset


def reset_watchdog():
    """Сбрасывает watchdog таймер. Вызывать после каждого успешного действия."""
    global _last_action_time, _watchdog_trigger_count
    _last_action_time = time.time()
    _watchdog_trigger_count = 0  # Сбрасываем счётчик циклов при успешном действии


def get_watchdog_idle_time():
    """Возвращает время простоя в секундах"""
    return time.time() - _last_action_time


def is_watchdog_triggered():
    """Проверяет, сработал ли watchdog (90+ секунд без активности)"""
    return get_watchdog_idle_time() >= WATCHDOG_TIMEOUT


def increment_watchdog_cycle():
    """Увеличивает счётчик срабатываний watchdog. Возвращает True если достигнут порог цикла."""
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


def antibot_delay(base=0.5, spread=1.2):
    """Рандомная задержка для обхода антибот-защиты"""
    delay = base + random.random() * spread
    time.sleep(delay)


def log(message):
    """Вывод сообщения с временной меткой + запись в файл"""
    formatted = f"{time.strftime('%H:%M:%S')} {message}"
    print(formatted)
    write_log(message)


def parse_cooldown_time(cd_text):
    """
    Парсит время КД из текста вида "14м 30с", "2ч 33м", "59м 32с"
    Возвращает время в секундах или None если не удалось распарсить.
    """
    if not cd_text:
        return None

    total_seconds = 0

    # Ищем часы
    hours_match = re.search(r'(\d+)\s*ч', cd_text)
    if hours_match:
        total_seconds += int(hours_match.group(1)) * 3600

    # Ищем минуты
    minutes_match = re.search(r'(\d+)\s*м', cd_text)
    if minutes_match:
        total_seconds += int(minutes_match.group(1)) * 60

    # Ищем секунды
    seconds_match = re.search(r'(\d+)\s*с', cd_text)
    if seconds_match:
        total_seconds += int(seconds_match.group(1))

    return total_seconds if total_seconds > 0 else None


def format_duration(seconds):
    """Форматирует секунды в читаемый вид: 'Xм Yс'"""
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}м {secs}с"


def safe_click(page, selector, timeout=5000):
    """
    Безопасный клик через dispatch_event - работает даже когда окно не в фокусе.
    Возвращает True если клик успешен, False если элемент не найден.
    """
    try:
        element = page.wait_for_selector(selector, timeout=timeout, state="visible")
        if element:
            element.dispatch_event("click")
            return True
    except:
        pass
    return False


def safe_click_element(element):
    """
    Безопасный клик по уже найденному элементу через dispatch_event.
    Возвращает True если клик успешен.
    """
    try:
        if element:
            element.dispatch_event("click")
            return True
    except:
        pass
    return False
