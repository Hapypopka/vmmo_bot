# ============================================
# VMMO Bot - Configuration (requests version)
# ============================================
# Все константы и настройки в одном месте
# Поддержка профилей: --profile char1
# ============================================

import os
import json

# Пути (базовые, могут быть переопределены профилем)
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")

# Текущий профиль (устанавливается через set_profile)
_current_profile = None
_profile_config = {}

# Пути по умолчанию (переопределяются при загрузке профиля)
LOGS_DIR = os.path.join(SCRIPT_DIR, "logs")
COOKIES_FILE = os.path.join(SCRIPT_DIR, "cookies.json")
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.json")
STATS_FILE = os.path.join(SCRIPT_DIR, "stats.json")
AUCTION_BLACKLIST_FILE = os.path.join(SCRIPT_DIR, "auction_blacklist.json")

# URLs
BASE_URL = "https://vmmo.vten.ru"
CITY_URL = f"{BASE_URL}/city"
DUNGEONS_URL = f"{BASE_URL}/dungeons?52"
HELL_GAMES_URL = f"{BASE_URL}/basin/combat"
LOGIN_URL = f"{BASE_URL}/login"

# Watchdog
WATCHDOG_TIMEOUT = 90  # Секунд без активности = застревание
WATCHDOG_CYCLE_THRESHOLD = 5  # Срабатываний подряд = hard reset
NO_PROGRESS_LIMIT = 240  # Атак без прогресса

# Backpack
BACKPACK_THRESHOLD = 18  # Порог для очистки рюкзака

# Dungeon action limits (Brutal difficulty = longer fights)
DUNGEON_ACTION_LIMITS = {
    "dng:ShadowGuard": 500,
    "dng:Barony": 500,
    "dng:HighDungeon": 500,
    "default": 500,
}

# Dungeons to skip
SKIP_DUNGEONS = [
    # "dng:RestMonastery",  # Монастырь покоя - тест
]

# Protected items - never sell or disassemble
PROTECTED_ITEMS = [
    "Железо",
    "Железная Руда",
    "Железный Слиток",
    "Треснутый Кристалл Тикуана",
    "Печать Сталкера I",
    "Печать Сталкера II",
    "Печать Сталкера III",
    # Квестовые/ценные предметы
    "Золотой Оберег",
    "Изумительная пылинка",
]

# HTTP headers
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
}

AJAX_HEADERS = {
    "Wicket-Ajax": "true",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/xml, text/xml, */*; q=0.01",
}


def load_settings():
    """Загружает настройки из settings.json"""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def get_setting(key, default=None):
    """Получает настройку по ключу"""
    settings = load_settings()
    return settings.get(key, default)


# ============================================
# Profile Management
# ============================================

def set_profile(profile_name):
    """
    Устанавливает профиль и обновляет все пути.
    Вызывается при старте бота с --profile аргументом.
    """
    global _current_profile, _profile_config
    global LOGS_DIR, COOKIES_FILE, STATS_FILE
    global SKIP_DUNGEONS, DUNGEON_ACTION_LIMITS

    profile_dir = os.path.join(PROFILES_DIR, profile_name)
    config_file = os.path.join(profile_dir, "config.json")

    if not os.path.exists(profile_dir):
        raise ValueError(f"Profile '{profile_name}' not found in {PROFILES_DIR}")

    # Создаём папку logs внутри профиля если нет
    profile_logs = os.path.join(profile_dir, "logs")
    os.makedirs(profile_logs, exist_ok=True)

    # Обновляем глобальные пути
    _current_profile = profile_name
    LOGS_DIR = profile_logs
    COOKIES_FILE = os.path.join(profile_dir, "cookies.json")
    STATS_FILE = os.path.join(profile_dir, "stats.json")

    # Загружаем конфиг профиля
    if os.path.exists(config_file):
        with open(config_file, "r", encoding="utf-8") as f:
            _profile_config = json.load(f)
        print(f"[CONFIG] Loaded profile: {profile_name} ({_profile_config.get('name', 'unnamed')})")
    else:
        _profile_config = {}
        print(f"[CONFIG] Profile '{profile_name}' has no config.json, using defaults")

    # Обновляем настройки из профиля
    if "skip_dungeons" in _profile_config:
        SKIP_DUNGEONS = _profile_config["skip_dungeons"]

    if "dungeon_action_limits" in _profile_config:
        DUNGEON_ACTION_LIMITS.update(_profile_config["dungeon_action_limits"])

    return _profile_config


def get_profile_config():
    """Возвращает конфиг текущего профиля"""
    return _profile_config


def get_profile_name():
    """Возвращает имя текущего профиля"""
    return _current_profile


def is_event_dungeon_enabled():
    """Проверяет, включен ли ивент для текущего профиля"""
    return _profile_config.get("event_dungeon_enabled", True)


def get_skill_cooldowns():
    """Возвращает КД скиллов для текущего профиля"""
    skill_cds = _profile_config.get("skill_cooldowns", {})
    # Конвертируем ключи в int
    return {int(k): v for k, v in skill_cds.items()} if skill_cds else None


def get_credentials():
    """Возвращает логин/пароль для текущего профиля"""
    username = _profile_config.get("username")
    password = _profile_config.get("password")
    if username and password:
        return username, password
    return None, None
