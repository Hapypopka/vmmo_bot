"""
Централизованные константы для VMMO Bot.
Все таймауты, задержки и regex паттерны в одном месте.
"""

import re

# ═══════════════════════════════════════════════════════════════════════════════
# TIMING CONSTANTS - задержки и таймауты
# ═══════════════════════════════════════════════════════════════════════════════

# HTTP
HTTP_TIMEOUT = 30  # секунд
SERVER_UPDATE_RETRY_DELAY = 10  # секунд между попытками при обновлении сервера
SERVER_UPDATE_MAX_RETRIES = 30  # максимум попыток

# Combat
GCD = 2.0  # Global Cooldown между скиллами
ATTACK_CD = 0.6  # Cooldown между автоатаками
COMBAT_ACTION_DELAY = 0.3  # Задержка после действия в бою
LOOT_COLLECT_INTERVAL = 1.5  # Интервал сбора лута (metronome)

# Arena
ARENA_QUEUE_TIMEOUT = 180  # секунд ожидания в очереди
ARENA_READY_WAIT = 10  # секунд на подтверждение готовности
ARENA_CD_WAIT = 300  # 5 минут между боями арены
ARENA_MIN_FIGHTS_LEFT = 2  # минимум боёв для входа

# Dungeon
DUNGEON_WAIT_AFTER_ACTION = 0.5  # секунд после действия
DUNGEON_STAGE_TRANSITION_WAIT = 1.0  # секунд между этапами

# Craft
CRAFT_CHECK_INTERVAL = 60  # секунд между проверками крафта
CRAFT_LOCK_TIMEOUT = 60  # секунд таймаут блокировки

# Survival Mines
MINES_MAX_WAVE = 30  # максимальная волна
MINES_WAVE_WAIT = 1.0  # секунд между волнами

# General
PAGE_LOAD_WAIT = 1.0  # секунд ожидания загрузки страницы
API_RETRY_DELAY = 3  # секунд между повторами API
SHORT_DELAY = 0.3  # короткая задержка
MEDIUM_DELAY = 1.0  # средняя задержка
LONG_DELAY = 3.0  # длинная задержка


# ═══════════════════════════════════════════════════════════════════════════════
# REGEX PATTERNS - паттерны для парсинга
# ═══════════════════════════════════════════════════════════════════════════════

class Patterns:
    """Компилированные regex паттерны для парсинга HTML/JS"""

    # Количество предметов (x5, х10)
    QUANTITY_X = re.compile(r'[xх](\d+)', re.IGNORECASE)

    # Page ID из JavaScript
    PAGE_ID = re.compile(r'ptxPageId\s*=\s*(\d+)')

    # Wicket AJAX вызовы
    WICKET_AJAX = re.compile(r'Wicket\.Ajax\.ajax\(\{[^}]*"c":"([^"]+)"[^}]*"u":"([^"]+)"')
    WICKET_AJAX_ALT = re.compile(r'"u":"([^"]+)"[^}]*"c":"([^"]+)"')  # Альтернативный порядок

    # URL скиллов в бою
    SKILL_URL = re.compile(r'skills-(\d+)-skillBlock-skillBlockInner-skillLink')
    SKILL_LINK = re.compile(r'"u":"([^"]*skills-\d+-skillBlock[^"]*)"')

    # Атака в бою
    ATTACK_URL = re.compile(r'"u":"([^"]*attack[^"]*)"', re.IGNORECASE)

    # Metronome (heartbeat) URL
    METRONOME = re.compile(r"Wicket\.Timer\.set\('metronome'[^;]*'([^']+)'")

    # Кнопка продолжения боя
    CONTINUE_COMBAT = re.compile(r'href=["\']([^"\']*(?:ppAction=combat|nextStep|/step/)[^"\']*)["\']', re.IGNORECASE)

    # Результат боя
    BATTLE_RESULT = re.compile(r'(победа|поражение|ничья)', re.IGNORECASE)

    # Золото из текста
    GOLD_AMOUNT = re.compile(r'(\d[\d\s]*)\s*(?:золот|gold)', re.IGNORECASE)

    # Ресурсы
    RESOURCE_VALUE = re.compile(r'>\s*([\d\s]+)\s*<')

    # Время (для таймеров)
    TIME_HMS = re.compile(r'(\d+):(\d+):(\d+)')
    TIME_MS = re.compile(r'(\d+):(\d+)')

    # ID предмета из URL/атрибута
    ITEM_ID = re.compile(r'item[_-]?id[=:]?\s*(\d+)', re.IGNORECASE)

    # Цена на аукционе
    AUCTION_PRICE = re.compile(r'(\d[\d\s]*)\s*(?:за\s*шт|each)?', re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════════
# COMBAT CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

# Позиции врагов в бою
ENEMY_POSITIONS = [21, 22, 23, 24, 25]

# Позиции скиллов
SKILL_POSITIONS = [1, 2, 3, 4, 5]

# Дефолтные кулдауны скиллов (секунды)
DEFAULT_SKILL_COOLDOWNS = {
    1: 15.5,
    2: 24.5,
    3: 39.5,
    4: 54.5,
    5: 42.5
}


# ═══════════════════════════════════════════════════════════════════════════════
# URL PATHS
# ═══════════════════════════════════════════════════════════════════════════════

class URLs:
    """Пути к страницам игры"""

    CITY = "/city"
    BACKPACK = "/backpack"
    AUCTION = "/auction"
    MAIL = "/mail"
    DUNGEONS = "/dungeons"
    ARENA = "/arena"
    CRAFT = "/craft"
    BANK = "/bank"
    TAVERN = "/tavern"

    # API endpoints
    API_QUEST_VIEW = "/api/quest/view"
    API_QUEST_ACCEPT = "/api/quest/accept"
    API_QUEST_COMPLETE = "/api/quest/complete"
