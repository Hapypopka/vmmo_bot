# ============================================
# VMMO Bot - Watchdog Module (requests version)
# ============================================
# Защита от зависания: отслеживает время без активности
# и принудительно выходит из застревания
# ============================================

import time

# Настройки watchdog
WATCHDOG_TIMEOUT = 90  # 90 секунд без активности = застревание
WATCHDOG_CYCLE_THRESHOLD = 5  # 5 срабатываний подряд = hard reset

# Глобальное состояние
_last_action_time = time.time()
_watchdog_trigger_count = 0
_consecutive_no_progress = 0  # Счётчик атак без прогресса


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
    Возвращает True если достигнут лимит (240 атак).
    """
    global _consecutive_no_progress
    _consecutive_no_progress += 1
    return _consecutive_no_progress >= 240


def get_no_progress_count():
    """Возвращает количество атак без прогресса"""
    return _consecutive_no_progress


class WatchdogMixin:
    """
    Миксин для добавления watchdog функциональности в клиент.

    Использование:
        class MyClient(WatchdogMixin):
            def do_action(self):
                self.reset_watchdog()
                # ... действие ...
                if self.is_watchdog_triggered():
                    self.handle_stuck()
    """

    def __init__(self):
        self._last_action = time.time()
        self._trigger_count = 0
        self._no_progress = 0

    def reset_watchdog(self):
        """Сбрасывает watchdog"""
        self._last_action = time.time()
        self._trigger_count = 0

    def is_watchdog_triggered(self):
        """Проверяет застревание"""
        return (time.time() - self._last_action) >= WATCHDOG_TIMEOUT

    def get_idle_time(self):
        """Время простоя в секундах"""
        return time.time() - self._last_action

    def handle_watchdog_trigger(self, client):
        """
        Обрабатывает срабатывание watchdog.
        Возвращает: "recovered" или "hard_reset"
        """
        self._trigger_count += 1
        idle = int(self.get_idle_time())

        if self._trigger_count >= WATCHDOG_CYCLE_THRESHOLD:
            # Много срабатываний - hard reset
            print(f"[WATCHDOG] {self._trigger_count} срабатываний подряд — HARD RESET!")
            self._trigger_count = 0
            client.get("/dungeons?52")
            return "hard_reset"

        print(f"[WATCHDOG] Простой {idle} сек (попытка {self._trigger_count}/{WATCHDOG_CYCLE_THRESHOLD})")

        # Пробуем выйти из застревания
        from requests_bot.popups import PopupsClient
        popups = PopupsClient(client)
        popups.emergency_unstuck()

        return "recovered"


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
        client.get("/dungeons?52")

        reset_watchdog_cycle()
        reset_watchdog()
        return "hard_reset"

    print(f"[WATCHDOG] Бот простаивает {idle_time} сек (попытка {cycle_count + 1}/{WATCHDOG_CYCLE_THRESHOLD})")

    # Пробуем выйти из застревания
    if popups_client:
        popups_client.emergency_unstuck()
    else:
        # Без popups_client просто идём в данжены
        client.get("/dungeons?52")

    reset_watchdog()
    return "recovered"
