# ============================================
# VMMO Bot Configuration - Warrior
# ============================================

import os
import json

# Путь к папке скрипта (для загрузки cookies.json)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.json")

# ============================================
# Загрузка настроек из settings.json
# ============================================
def _load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

_settings = _load_settings()

# ============================================
# URLs
# ============================================
BASE_URL = "https://vmmo.vten.ru"
CITY_URL = f"{BASE_URL}/city"
DUNGEONS_URL = f"{BASE_URL}/dungeons?52"
HELL_GAMES_URL = f"{BASE_URL}/basin/combat"
LOGIN_URL = f"{BASE_URL}/login"

# ============================================
# Тайминги и лимиты (из settings.json или дефолтные)
# ============================================
BACKPACK_THRESHOLD = _settings.get('backpack_threshold', 15)
MAX_NO_UNITS_ATTEMPTS = _settings.get('max_no_units', 5)
RESTART_INTERVAL = _settings.get('restart_interval', 7200)
MAX_ENTER_FAILURES = 2           # Макс. ошибок входа перед принудительным обновлением

# ============================================
# Селекторы - Навигация
# ============================================
DUNGEONS_BUTTON_SELECTOR = 'a.btn.nav-btn[href*="dungeons"]'
ATTACK_SELECTOR = "#ptx_combat_rich2_attack_link"

# ============================================
# Селекторы - Юниты (позиции 21-25 для данженов)
# ============================================
UNIT_SELECTORS = [
    ".unit._unit-pos-21",
    ".unit._unit-pos-22",
    ".unit._unit-pos-23",
    ".unit._unit-pos-24",
    ".unit._unit-pos-25",
]

# ============================================
# Селекторы - Рюкзак
# ============================================
BACKPACK_LINK_SELECTOR = 'a.main-menu-link._rack[title="Рюкзак"]'
BACKPACK_COUNT_SELECTOR = 'a.main-menu-link._rack .link-text'
DISASSEMBLE_BUTTON_SELECTOR = 'a[data-on-click-sound="ui take-apart"]'
CONFIRM_BUTTON_SELECTOR = 'span.go-btn-in'

# ============================================
# Селекторы - Попапы и виджеты
# ============================================
POPUP_CLOSE_SELECTOR = 'a.popup-close-link'
WIDGET_LEAVE_PARTY_SELECTOR = 'div.widget a.go-btn[href*="leaveParty"]'
COMBAT_LOOT_SELECTOR = 'div.combat-loot'
REST_BONUS_POPUP_SELECTOR = 'div.popup-inner img[src*="rest-buff"]'
REST_BONUS_CONTINUE_SELECTOR = 'div.popup-inner a.go-btn'

# ============================================
# Скиллы (позиция → название)
# ============================================
SKILLS = {
    1: "Талисман Доблести",
    2: "Гром и Молния",
    3: "Ледяной Удар",
    4: "Ярость Богов",
    5: "Рывок Жизни",
}

# Скиллы, которые НЕ используем в Адских Играх
HELL_GAMES_SKIP_SKILLS = [1]  # Талисман Доблести

# ============================================
# Браузер
# ============================================
BROWSER_VIEWPORT = {"width": 1920, "height": 1080}
BROWSER_SCREEN = {"width": 1920, "height": 1080}
