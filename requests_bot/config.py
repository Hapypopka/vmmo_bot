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
PROFILE_DIR = None  # Папка текущего профиля

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
BACKPACK_THRESHOLD = 18  # Порог для очистки рюкзака (из 28 слотов)

# Combat
LOOT_COLLECT_INTERVAL = 3  # Собирать лут каждые N атак (через refresher)
GCD = 2.0  # Global Cooldown между скиллами (секунды)
ATTACK_CD = 0.6  # Cooldown между автоатаками (секунды)

# Craft locks and cache
CRAFT_LOCK_TTL = 7200  # 2 часа - лок крафта протухает если бот не обновил
CRAFT_CACHE_TTL = 14400  # 4 часа - кэш цен аукциона

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

# Only these dungeons (whitelist) - if set, ONLY these dungeons will be run
ONLY_DUNGEONS = []  # Empty = all dungeons allowed

# Protected items - never sell or disassemble
# Дефолтные значения (используются если нет файла)
_DEFAULT_PROTECTED_ITEMS = [
    # Крафт железа
    "Железо",
    "Железная Руда",
    "Железный Слиток",
    # Крафт меди/бронзы
    "Медь",
    "Медная Руда",
    "Медный Слиток",
    "Бронза",
    "Бронзовый Слиток",
    # Крафт платины
    "Платина",
    "Платиновый Слиток",
    # Крафт тора
    "Тор",
    "Слиток Тора",
    # Квестовые/ценные
    "Треснутый Кристалл Тикуана",
    "Печать Сталкера I",
    "Печать Сталкера II",
    "Печать Сталкера III",
    "Золотой Оберег",
    "Изумительная пылинка",
    # Все ларцы оберегов (частичное совпадение)
    "Оберегов",
    # Сундуки/ларцы (открываем, не продаём)
    "Сундук",
    "Ларец",
    "Ящик",
    "Шкатулка",
    # Экипировка
    "Шлем Нордов",
    # Ресурсы ивентов
    "Ледяной Кристалл",
    "Уголь Эфирного Древа",
]

# Файл с защищёнными предметами (редактируется через ТГ)
PROTECTED_ITEMS_FILE = os.path.join(SCRIPT_DIR, "protected_items.json")

def _load_protected_items():
    """Загружает защищённые предметы из файла или возвращает дефолт"""
    if os.path.exists(PROTECTED_ITEMS_FILE):
        try:
            with open(PROTECTED_ITEMS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[CONFIG] Ошибка загрузки protected_items: {e}")
    return _DEFAULT_PROTECTED_ITEMS.copy()

# Загружаем при старте
PROTECTED_ITEMS = _load_protected_items()


def add_protected_item(item_name):
    """
    Добавляет предмет в список защищённых.
    Используется при сборе ежедневных наград.

    Args:
        item_name: Название предмета

    Returns:
        bool: True если добавлен (или уже был)
    """
    global PROTECTED_ITEMS

    # Проверяем, нет ли уже такого (частичное совпадение)
    item_lower = item_name.lower()
    for existing in PROTECTED_ITEMS:
        if existing.lower() in item_lower or item_lower in existing.lower():
            print(f"[CONFIG] Предмет '{item_name}' уже защищён (как '{existing}')")
            return True

    # Добавляем
    PROTECTED_ITEMS.append(item_name)

    # Сохраняем в файл
    try:
        with open(PROTECTED_ITEMS_FILE, "w", encoding="utf-8") as f:
            json.dump(PROTECTED_ITEMS, f, ensure_ascii=False, indent=2)
        print(f"[CONFIG] Добавлен защищённый предмет: {item_name}")
        return True
    except IOError as e:
        print(f"[CONFIG] Ошибка сохранения protected_items: {e}")
        return False


def reload_protected_items():
    """
    Перезагружает PROTECTED_ITEMS из файла.
    Используется веб-панелью после изменений.
    """
    global PROTECTED_ITEMS
    PROTECTED_ITEMS = _load_protected_items()
    return PROTECTED_ITEMS


def get_protected_items():
    """
    Возвращает актуальный список защищённых предметов.
    Перезагружает из файла если он изменился.
    """
    global PROTECTED_ITEMS, _protected_items_mtime

    try:
        current_mtime = os.path.getmtime(PROTECTED_ITEMS_FILE) if os.path.exists(PROTECTED_ITEMS_FILE) else 0
        if current_mtime != _protected_items_mtime:
            PROTECTED_ITEMS = _load_protected_items()
            _protected_items_mtime = current_mtime
    except OSError:
        pass

    return PROTECTED_ITEMS

# Время модификации файла для отслеживания изменений
_protected_items_mtime = os.path.getmtime(PROTECTED_ITEMS_FILE) if os.path.exists(PROTECTED_ITEMS_FILE) else 0


# HTTP headers
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "DNT": "1",
    "Sec-GPC": "1",
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
    except (json.JSONDecodeError, FileNotFoundError, IOError):
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
    global _current_profile, _profile_config, PROFILE_DIR
    global LOGS_DIR, COOKIES_FILE, STATS_FILE
    global SKIP_DUNGEONS, DUNGEON_ACTION_LIMITS

    profile_dir = os.path.join(PROFILES_DIR, profile_name)
    PROFILE_DIR = profile_dir  # Сохраняем глобально
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

    try:
        print(f"[CONFIG] COOKIES_FILE = {COOKIES_FILE}")
    except UnicodeEncodeError:
        print(f"[CONFIG] COOKIES_FILE = (path with special chars)")

    # Загружаем конфиг профиля
    if os.path.exists(config_file):
        with open(config_file, "r", encoding="utf-8") as f:
            _profile_config = json.load(f)
        print(f"[CONFIG] Loaded profile: {profile_name} ({_profile_config.get('name', 'unnamed')})")

        # Миграция старого формата craft_queue → craft_items
        migrate_craft_queue_to_items()
    else:
        _profile_config = {}
        print(f"[CONFIG] Profile '{profile_name}' has no config.json, using defaults")

    # Обновляем настройки из профиля
    global SKIP_DUNGEONS, ONLY_DUNGEONS
    if "skip_dungeons" in _profile_config:
        SKIP_DUNGEONS = _profile_config["skip_dungeons"].copy()
    else:
        SKIP_DUNGEONS = []

    if "only_dungeons" in _profile_config:
        ONLY_DUNGEONS = _profile_config["only_dungeons"].copy()
    else:
        ONLY_DUNGEONS = []

    if "dungeon_action_limits" in _profile_config:
        DUNGEON_ACTION_LIMITS.update(_profile_config["dungeon_action_limits"])

    # Загружаем скипнутые данжены из deaths.json
    _load_skipped_from_deaths()

    return _profile_config


def get_profile_config():
    """Возвращает конфиг текущего профиля"""
    return _profile_config


def get_profile_name():
    """Возвращает имя текущего профиля"""
    return _current_profile


def get_profile_username():
    """Возвращает username из профиля (для уведомлений)"""
    return _profile_config.get("username", _current_profile or "unknown")


def is_dungeons_enabled():
    """Проверяет, включены ли обычные данжены для текущего профиля"""
    return _profile_config.get("dungeons_enabled", True)


# ARCHIVED: is_event_dungeon_enabled() and is_ny_event_dungeon_enabled() moved to archive/events/ (2026-01)

def is_arena_enabled():
    """Проверяет, включена ли арена для текущего профиля"""
    return _profile_config.get("arena_enabled", False)


def get_arena_max_fights():
    """Возвращает максимум боёв на арене за сессию"""
    return _profile_config.get("arena_max_fights", 50)


def is_hell_games_enabled():
    """Проверяет, включены ли Адские Игры для текущего профиля"""
    return _profile_config.get("hell_games_enabled", True)


def is_light_side():
    """
    Проверяет, светлый ли персонаж (для Адских Игр).
    Светлые атакуют dark источники, тёмные атакуют light.
    По умолчанию False (тёмный).
    """
    return _profile_config.get("is_light_side", False)


def is_pet_resurrection_enabled():
    """Проверяет, включено ли автовоскрешение питомца для текущего профиля"""
    return _profile_config.get("pet_resurrection_enabled", False)


def is_survival_mines_enabled():
    """Проверяет, включена ли Заброшенная Шахта для текущего профиля"""
    return _profile_config.get("survival_mines_enabled", False)


def is_daily_rewards_enabled():
    """Проверяет, включен ли автосбор ежедневных наград для текущего профиля"""
    return _profile_config.get("daily_rewards_enabled", True)  # По умолчанию ВКЛ


def is_iron_craft_enabled():
    """Проверяет, включен ли крафт железа для текущего профиля"""
    return _profile_config.get("iron_craft_enabled", False)


def get_dungeon_tabs():
    """
    Возвращает список вкладок данжей для проверки.
    По умолчанию ["tab2"] (50+).

    Формат в config.json:
    "dungeon_tabs": ["tab2", "tab3"]  // 50+ и 30-39
    """
    return _profile_config.get("dungeon_tabs", ["tab2"])


def get_extra_dungeons():
    """
    Возвращает список дополнительных данжей из других вкладок.

    Формат в config.json:
    "extra_dungeons": [
        {"tab": "tab3", "id": "dng:ShadowGuard"}
    ]
    """
    return _profile_config.get("extra_dungeons", [])


# ============================================
# Очередь крафта
# ============================================

# Доступные предметы для крафта
CRAFTABLE_ITEMS = {
    "rawOre": "Железная Руда",
    "iron": "Железо",
    "ironBar": "Железный Слиток",
    "rawCopper": "Медная Руда",
    "copper": "Медь",
    "copperBar": "Медный Слиток",
    "bronze": "Бронза",
    "bronzeBar": "Бронзовый Слиток",
    "rawPlatinum": "Платиновая Руда",
    "platinum": "Платина",
    "platinumBar": "Платиновый Слиток",
    "thor": "Тор",
    "thorBar": "Слиток Тора",
    "twilightSteel": "Сумеречная Сталь",
    "twilightAnthracite": "Сумеречный Антрацит",
}


def get_craft_items():
    """
    Возвращает список предметов для автокрафта.

    Формат в config.json:
    "craft_items": [
        {"item": "copper", "batch_size": 5},
        {"item": "iron", "batch_size": 10}
    ]

    Returns:
        list: Список предметов для крафта
    """
    return _profile_config.get("craft_items", [])


def get_craft_items_from_disk():
    """
    Читает craft_items напрямую с диска (не из памяти).
    Используется для обнаружения изменений конфига через веб-панель.

    Returns:
        list: Список предметов для крафта
    """
    global _current_profile
    if not _current_profile:
        return []

    config_file = os.path.join(PROFILES_DIR, _current_profile, "config.json")
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config.get("craft_items", [])
    except Exception:
        return []


def add_craft_item(item_id, batch_size):
    """
    Добавляет предмет в список автокрафта.

    Args:
        item_id: ID предмета (iron, ironBar, copper, bronze, platinum)
        batch_size: Размер партии для продажи

    Returns:
        bool: True если успешно
    """
    global _profile_config

    if item_id not in CRAFTABLE_ITEMS:
        return False

    if "craft_items" not in _profile_config:
        _profile_config["craft_items"] = []

    _profile_config["craft_items"].append({
        "item": item_id,
        "batch_size": int(batch_size)
    })

    save_profile_config()
    return True


def set_craft_finish_time(finish_timestamp):
    """
    Сохраняет время завершения крафта (unix timestamp).

    Args:
        finish_timestamp: Unix timestamp когда крафт завершится
    """
    global _profile_config
    _profile_config["craft_finish_time"] = finish_timestamp
    save_profile_config()


def get_craft_finish_time():
    """
    Возвращает время завершения крафта (unix timestamp).

    Returns:
        int or None: Unix timestamp или None если крафт не запущен
    """
    return _profile_config.get("craft_finish_time")


def clear_craft_finish_time():
    """Очищает сохранённое время завершения крафта"""
    global _profile_config
    if "craft_finish_time" in _profile_config:
        del _profile_config["craft_finish_time"]
        save_profile_config()


def is_craft_ready_soon(threshold_seconds=60):
    """
    Проверяет, скоро ли завершится крафт.

    Args:
        threshold_seconds: За сколько секунд до завершения считать "скоро"

    Returns:
        bool: True если крафт завершится в течение threshold_seconds
    """
    import time
    finish_time = get_craft_finish_time()
    if not finish_time:
        return False

    current_time = int(time.time())
    time_left = finish_time - current_time

    # Если time_left <= 0, крафт УЖЕ готов (или просрочен)
    # Если 0 < time_left <= threshold, крафт СКОРО готов
    return time_left <= threshold_seconds


def remove_craft_item(index):
    """
    Удаляет предмет из списка автокрафта по индексу.

    Args:
        index: Индекс предмета в списке

    Returns:
        bool: True если успешно
    """
    global _profile_config

    items = _profile_config.get("craft_items", [])
    if 0 <= index < len(items):
        items.pop(index)
        _profile_config["craft_items"] = items
        save_profile_config()
        return True
    return False


def clear_craft_items():
    """Очищает весь список автокрафта"""
    global _profile_config
    _profile_config["craft_items"] = []
    save_profile_config()


def migrate_craft_queue_to_items():
    """
    Конвертирует старый craft_queue в новый craft_items.
    Вызывается автоматически при загрузке конфига.
    """
    global _profile_config

    old_queue = _profile_config.get("craft_queue", [])

    # Проверяем что это старый формат (есть поле "done")
    if old_queue and isinstance(old_queue, list) and len(old_queue) > 0:
        if "done" in old_queue[0]:
            # Старый формат - мигрируем
            new_items = [
                {"item": task["item"], "batch_size": task["count"]}
                for task in old_queue
            ]
            _profile_config["craft_items"] = new_items
            del _profile_config["craft_queue"]
            save_profile_config()
            print(f"[CONFIG] Мигрирован craft_queue → craft_items ({len(new_items)} предметов)")


def save_profile_config():
    """Сохраняет конфиг текущего профиля в файл"""
    global _profile_config, _current_profile

    if not _current_profile:
        return False

    config_file = os.path.join(PROFILES_DIR, _current_profile, "config.json")
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(_profile_config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[CONFIG] Ошибка сохранения: {e}")
        return False


def get_survival_mines_max_wave():
    """Возвращает максимальную волну для выхода из шахты (по умолчанию 31)"""
    return _profile_config.get("survival_mines_max_wave", 31)


def get_survival_mines_max_level():
    """Возвращает максимальный уровень для шахты (после него бот останавливается)"""
    return _profile_config.get("survival_mines_max_level", None)


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
# Resource Selling Settings
# ============================================

# Дефолтные настройки продажи ресурсов
DEFAULT_RESOURCE_SELL_SETTINGS = {
    "mineral": {"enabled": False, "stack": 1000, "reserve": 200},   # Минерал
    "skull": {"enabled": False, "stack": 1000, "reserve": 200},      # Череп
    "sapphire": {"enabled": False, "stack": 100, "reserve": 10},     # Сапфир
    "ruby": {"enabled": False, "stack": 100, "reserve": 10},         # Рубин
}

# Маппинг internal_name -> русское название для аукциона
RESOURCE_NAMES = {
    "mineral": "Минерал",
    "skull": "Череп",
    "sapphire": "Сапфир",
    "ruby": "Рубин",
}

# Маппинг internal_name -> id ресурса на сервере
RESOURCE_IDS = {
    "mineral": 3,
    "skull": 2,
    "sapphire": 4,
    "ruby": 5,
}


def is_resource_selling_enabled():
    """Проверяет, включена ли продажа ресурсов хотя бы для одного типа"""
    settings = get_resource_sell_settings()
    return any(s.get("enabled", False) for s in settings.values())


def get_resource_sell_settings():
    """
    Возвращает настройки продажи ресурсов.

    Формат в config.json:
    "resource_sell": {
        "mineral": {"enabled": true, "stack": 1000, "reserve": 200},
        "skull": {"enabled": true, "stack": 1000, "reserve": 200},
        "sapphire": {"enabled": false, "stack": 100, "reserve": 10},
        "ruby": {"enabled": false, "stack": 100, "reserve": 10}
    }

    Returns:
        dict: Настройки для каждого ресурса
    """
    saved = _profile_config.get("resource_sell", {})
    result = {}

    for res_key, defaults in DEFAULT_RESOURCE_SELL_SETTINGS.items():
        res_settings = saved.get(res_key, {})
        result[res_key] = {
            "enabled": res_settings.get("enabled", defaults["enabled"]),
            "stack": res_settings.get("stack", defaults["stack"]),
            "reserve": res_settings.get("reserve", defaults["reserve"]),
        }

    return result


def get_resource_sell_config(resource_key):
    """
    Возвращает настройки продажи для конкретного ресурса.

    Args:
        resource_key: mineral, skull, sapphire, ruby

    Returns:
        dict: {"enabled": bool, "stack": int, "reserve": int}
    """
    settings = get_resource_sell_settings()
    return settings.get(resource_key, DEFAULT_RESOURCE_SELL_SETTINGS.get(resource_key, {}))


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


def _load_skipped_from_deaths():
    """
    Загружает скипнутые данжены из deaths.json в SKIP_DUNGEONS.
    Вызывается при загрузке профиля.
    """
    global SKIP_DUNGEONS
    deaths = load_deaths()

    for dungeon_id, data in deaths.items():
        if data.get("skipped") or data.get("current_difficulty") == "skip":
            if dungeon_id not in SKIP_DUNGEONS:
                SKIP_DUNGEONS.append(dungeon_id)
                print(f"[CONFIG] Скипаем {data.get('name', dungeon_id)} (из deaths.json)")


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

    Returns:
        tuple: (new_difficulty, should_skip) - новая сложность и нужно ли скипать
    """
    global SKIP_DUNGEONS
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

    # Если умер на normal - добавляем в skip
    if difficulty == "normal":
        deaths[dungeon_id]["current_difficulty"] = "skip"
        deaths[dungeon_id]["skipped"] = True
        print(f"[CONFIG] {dungeon_name}: умер на normal, данж будет скипаться!")

        # Добавляем в SKIP_DUNGEONS если ещё нет
        if dungeon_id not in SKIP_DUNGEONS:
            SKIP_DUNGEONS.append(dungeon_id)

        save_deaths(deaths)
        return "skip", True

    # Снижаем сложность
    current_diff = deaths[dungeon_id].get("current_difficulty", "brutal")

    # Если уже skip - оставляем skip
    if current_diff == "skip":
        print(f"[CONFIG] {dungeon_name}: уже в skip, оставляем")
        save_deaths(deaths)
        return "skip", True

    try:
        current_idx = DIFFICULTY_LEVELS.index(current_diff)
        if current_idx < len(DIFFICULTY_LEVELS) - 1:
            new_diff = DIFFICULTY_LEVELS[current_idx + 1]
            deaths[dungeon_id]["current_difficulty"] = new_diff
            print(f"[CONFIG] {dungeon_name}: сложность снижена {current_diff} -> {new_diff}")
        else:
            print(f"[CONFIG] {dungeon_name}: уже минимальная сложность (normal)")
            new_diff = "normal"
    except ValueError:
        # Неизвестная сложность - ставим normal
        deaths[dungeon_id]["current_difficulty"] = "normal"
        new_diff = "normal"

    save_deaths(deaths)
    return new_diff, False


def get_dungeon_difficulty(dungeon_id):
    """
    Получает рекомендуемую сложность для данжена.

    Приоритет:
    1. deaths.json (если там есть запись)
    2. dungeon_difficulties из профиля (начальная сложность)
    3. "brutal" по умолчанию

    Returns:
        str: 'brutal', 'hero', или 'normal'
    """
    # Сначала проверяем deaths.json
    deaths = load_deaths()
    if dungeon_id in deaths:
        return deaths[dungeon_id].get("current_difficulty", "brutal")

    # Проверяем настройку профиля для начальной сложности
    profile_difficulties = _profile_config.get("dungeon_difficulties", {})
    if dungeon_id in profile_difficulties:
        return profile_difficulties[dungeon_id]

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
