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
    # Все ларцы оберегов (частичное совпадение)
    "Оберегов",
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

    print(f"[CONFIG] COOKIES_FILE = {COOKIES_FILE}")

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


def is_hell_games_enabled():
    """Проверяет, включены ли Адские Игры для текущего профиля"""
    return _profile_config.get("hell_games_enabled", True)


def is_pet_resurrection_enabled():
    """Проверяет, включено ли автовоскрешение питомца для текущего профиля"""
    return _profile_config.get("pet_resurrection_enabled", False)


def get_skill_cooldowns():
    """Возвращает КД скиллов для текущего профиля"""
    skill_cds = _profile_config.get("skill_cooldowns", {})
    # Конвертируем ключи в int
    return {int(k): v for k, v in skill_cds.items()} if skill_cds else None


def get_skill_hp_threshold():
    """Возвращает пороги HP для использования скиллов.

    Формат в config.json:
    "skill_hp_threshold": {
        "2": 20000,  // Скилл 2 только если HP врага > 20k
        "3": 20000   // Скилл 3 только если HP врага > 20k
    }

    Returns:
        dict: {skill_pos: min_hp} или {} если не задано
    """
    thresholds = _profile_config.get("skill_hp_threshold", {})
    # Конвертируем ключи в int
    return {int(k): v for k, v in thresholds.items()} if thresholds else {}


def get_credentials():
    """Возвращает логин/пароль для текущего профиля"""
    username = _profile_config.get("username")
    password = _profile_config.get("password")
    if username and password:
        return username, password
    return None, None


# ============================================
# Death Tracking & Difficulty Management
# ============================================

# Файл для хранения смертей (создаётся в папке профиля)
_deaths_file = None

# Уровни сложности (от высокой к низкой)
DIFFICULTY_LEVELS = ["brutal", "hero", "normal"]


def _get_deaths_file():
    """Получает путь к файлу смертей"""
    global _deaths_file
    if _deaths_file:
        return _deaths_file

    if _current_profile:
        profile_dir = os.path.join(PROFILES_DIR, _current_profile)
        _deaths_file = os.path.join(profile_dir, "deaths.json")
    else:
        _deaths_file = os.path.join(SCRIPT_DIR, "deaths.json")

    return _deaths_file


def load_deaths():
    """Загружает историю смертей из файла"""
    deaths_file = _get_deaths_file()
    try:
        if os.path.exists(deaths_file):
            with open(deaths_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[CONFIG] Ошибка загрузки deaths.json: {e}")
    return {}


def save_deaths(deaths):
    """Сохраняет историю смертей в файл"""
    deaths_file = _get_deaths_file()
    try:
        with open(deaths_file, "w", encoding="utf-8") as f:
            json.dump(deaths, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[CONFIG] Ошибка сохранения deaths.json: {e}")


def record_death(dungeon_id, dungeon_name, difficulty="brutal"):
    """
    Записывает смерть в данжене.

    Args:
        dungeon_id: ID данжена (например 'dng:RestMonastery')
        dungeon_name: Название данжена
        difficulty: Текущая сложность
    """
    deaths = load_deaths()

    if dungeon_id not in deaths:
        deaths[dungeon_id] = {
            "name": dungeon_name,
            "deaths": [],
            "current_difficulty": difficulty,
        }

    # Добавляем запись о смерти
    from datetime import datetime
    deaths[dungeon_id]["deaths"].append({
        "time": datetime.now().isoformat(),
        "difficulty": difficulty,
    })

    # Снижаем сложность
    current_diff = deaths[dungeon_id].get("current_difficulty", "brutal")
    try:
        current_idx = DIFFICULTY_LEVELS.index(current_diff)
        if current_idx < len(DIFFICULTY_LEVELS) - 1:
            new_diff = DIFFICULTY_LEVELS[current_idx + 1]
            deaths[dungeon_id]["current_difficulty"] = new_diff
            print(f"[CONFIG] {dungeon_name}: сложность снижена {current_diff} -> {new_diff}")
        else:
            print(f"[CONFIG] {dungeon_name}: уже минимальная сложность (normal)")
    except ValueError:
        deaths[dungeon_id]["current_difficulty"] = "normal"

    save_deaths(deaths)
    return deaths[dungeon_id]["current_difficulty"]


def get_dungeon_difficulty(dungeon_id):
    """
    Получает рекомендуемую сложность для данжена.

    Returns:
        str: 'brutal', 'hero', или 'normal'
    """
    deaths = load_deaths()
    if dungeon_id in deaths:
        return deaths[dungeon_id].get("current_difficulty", "brutal")
    return "brutal"  # По умолчанию Брутал


def get_death_stats():
    """Возвращает статистику смертей для отображения"""
    deaths = load_deaths()
    stats = []
    for dungeon_id, data in deaths.items():
        stats.append({
            "id": dungeon_id,
            "name": data.get("name", dungeon_id),
            "deaths": len(data.get("deaths", [])),
            "difficulty": data.get("current_difficulty", "brutal"),
        })
    return stats


def reset_dungeon_difficulty(dungeon_id):
    """Сбрасывает сложность данжена на Брутал"""
    deaths = load_deaths()
    if dungeon_id in deaths:
        deaths[dungeon_id]["current_difficulty"] = "brutal"
        save_deaths(deaths)
        print(f"[CONFIG] {dungeon_id}: сложность сброшена на brutal")
