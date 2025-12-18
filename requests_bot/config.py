# ============================================
# VMMO Bot - Configuration (requests version)
# ============================================
# Все константы и настройки в одном месте
# ============================================

import os
import json

# Пути
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
