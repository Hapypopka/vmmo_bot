# ============================================
# VMMO Bot - Logger Module (requests version)
# ============================================
# Логирование в файл и консоль для анализа
# ============================================

import os
import sys
import logging
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(SCRIPT_DIR, "logs")

# Создаём папку для логов
os.makedirs(LOGS_DIR, exist_ok=True)

# Глобальный логгер
_logger = None
_log_file = None


def init_logger(name="vmmo_bot"):
    """
    Инициализирует логгер с выводом в файл и консоль.
    Возвращает логгер.
    """
    global _logger, _log_file

    if _logger is not None:
        return _logger

    # Создаём логгер
    _logger = logging.getLogger(name)
    _logger.setLevel(logging.DEBUG)

    # Формат: [время] [уровень] сообщение
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )

    # Детальный формат для файла
    file_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Файл лога с датой и временем
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file = os.path.join(LOGS_DIR, f"bot_{timestamp}.log")

    # Handler для файла (DEBUG и выше)
    file_handler = logging.FileHandler(_log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    # Handler для консоли (INFO и выше)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    _logger.addHandler(file_handler)
    _logger.addHandler(console_handler)

    _logger.info(f"=== Лог сессии: {_log_file} ===")

    return _logger


def get_logger():
    """Возвращает текущий логгер (инициализирует если нужно)"""
    global _logger
    if _logger is None:
        init_logger()
    return _logger


def get_log_file():
    """Возвращает путь к текущему файлу лога"""
    return _log_file


# Удобные функции для логирования
def log_debug(msg):
    """DEBUG - детальная отладка (только в файл)"""
    get_logger().debug(msg)


def log_info(msg):
    """INFO - основная информация"""
    get_logger().info(msg)


def log_warning(msg):
    """WARNING - предупреждения"""
    get_logger().warning(msg)


def log_error(msg):
    """ERROR - ошибки"""
    get_logger().error(msg)


def log_critical(msg):
    """CRITICAL - критические ошибки"""
    get_logger().critical(msg)


# Специализированные логгеры для разных модулей
def log_combat(msg):
    """Лог боя"""
    get_logger().info(f"[COMBAT] {msg}")


def log_dungeon(msg):
    """Лог данжена"""
    get_logger().info(f"[DUNGEON] {msg}")


def log_event(msg):
    """Лог ивента"""
    get_logger().info(f"[EVENT] {msg}")


def log_hell(msg):
    """Лог Адских Игр"""
    get_logger().info(f"[HELL] {msg}")


def log_mail(msg):
    """Лог почты"""
    get_logger().info(f"[MAIL] {msg}")


def log_backpack(msg):
    """Лог рюкзака"""
    get_logger().info(f"[BACKPACK] {msg}")


def log_watchdog(msg):
    """Лог watchdog"""
    get_logger().warning(f"[WATCHDOG] {msg}")


def log_stats(msg):
    """Лог статистики"""
    get_logger().info(f"[STATS] {msg}")


def log_http(method, url, status=None):
    """Лог HTTP запросов (DEBUG)"""
    if status:
        get_logger().debug(f"[HTTP] {method} {url} -> {status}")
    else:
        get_logger().debug(f"[HTTP] {method} {url}")


def log_session_start():
    """Лог начала сессии"""
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("VMMO Bot Session Started")
    logger.info(f"Log file: {_log_file}")
    logger.info("=" * 60)


def log_session_end(stats_dict):
    """Лог конца сессии со статистикой"""
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("SESSION ENDED")
    logger.info("-" * 40)
    for key, value in stats_dict.items():
        logger.info(f"  {key}: {value}")
    logger.info("=" * 60)


def log_cycle_start(cycle_num):
    """Лог начала цикла"""
    get_logger().info(f"{'#' * 50}")
    get_logger().info(f"# CYCLE {cycle_num}")
    get_logger().info(f"{'#' * 50}")


def log_dungeon_start(name, dungeon_id):
    """Лог входа в данжен"""
    get_logger().info(f">>> Entering dungeon: {name} ({dungeon_id})")


def log_dungeon_result(name, result, actions):
    """Лог результата данжена"""
    if result == "completed":
        get_logger().info(f"<<< COMPLETED: {name} in {actions} actions")
    elif result == "died":
        get_logger().warning(f"<<< DIED in {name} after {actions} actions")
    elif result in ("watchdog", "stuck"):
        get_logger().error(f"<<< STUCK in {name} after {actions} actions")
    else:
        get_logger().warning(f"<<< {result.upper()}: {name} after {actions} actions")


def log_error_with_context(msg, context=None):
    """Лог ошибки с контекстом для отладки"""
    logger = get_logger()
    logger.error(msg)
    if context:
        logger.debug(f"Context: {context[:500]}...")  # Первые 500 символов


# Декоратор для логирования функций
def logged(func):
    """Декоратор для автологирования вызовов функций"""
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        log_debug(f"-> {func_name}()")
        try:
            result = func(*args, **kwargs)
            log_debug(f"<- {func_name}() = {result}")
            return result
        except Exception as e:
            log_error(f"!! {func_name}() raised {type(e).__name__}: {e}")
            raise
    return wrapper
