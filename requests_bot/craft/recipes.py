# ============================================
# VMMO Craft Recipes
# ============================================
# Рецепты и названия для крафта горного дела
# ============================================

# Названия предметов для поиска в инвентаре
ITEM_NAMES = {
    # Железная цепочка
    "rawOre": "Железная Руда",
    "iron": "Железо",
    "ironBar": "Железный Слиток",
    # Медная/бронзовая цепочка
    "copperOre": "Медная Руда",
    "copper": "Медь",
    "copperBar": "Медный Слиток",
    "bronze": "Бронза",
    "bronzeBar": "Бронзовый Слиток",
    # Платиновая цепочка
    "platinum": "Платина",
    "platinumBar": "Платиновый Слиток",
    # Торовая цепочка
    "thor": "Тор",
    "thorBar": "Слиток Тора",
    # Сумеречные материалы (4 уровень)
    "twilightSteel": "Сумеречная Сталь",
    "twilightAnthracite": "Сумеречный Антрацит",
}


# Рецепты горного дела
# Данные получены с сервера игры 2026-01-10
RECIPES = {
    # === Железная цепочка ===
    "rawOre": {
        "name": "Железная Руда",
        "start_url": "/profs/startwork/rawOre",
        "craft_time": 300,  # 5 минут
        "level": 1,
        "minerals": 1,  # 1 минерал (ресурс игрока)
        "silver": 2,  # 2 серебра (игровая валюта)
    },
    "iron": {
        "name": "Железо",
        "start_url": "/profs/startwork/iron",
        "craft_time": 300,  # 5 минут
        "level": 1,
        "requires": {"rawOre": 1},  # 1 железная руда
        "minerals": 2,  # 2 минерала (ресурс игрока)
    },
    "ironBar": {
        "name": "Железный Слиток",
        "start_url": None,  # особый путь через level=2
        "craft_time": 600,  # 10 минут
        "level": 2,
        "prof_page": "/profs/prof/miningMaster?level=2",
        "craft_action": "CAP_craftReceipt",
        "receipt": "ironBar",
        "requires": {"iron": 5},  # 5 железа
    },
    # === Медная/бронзовая цепочка ===
    "copperOre": {
        "name": "Медная Руда",
        "start_url": "/profs/startwork/copperOre",
        "craft_time": 120,  # 2 минуты
        "level": 1,
        "minerals": 1,  # 1 минерал (ресурс игрока)
    },
    "copper": {
        "name": "Медь",
        "start_url": "/profs/startwork/copper",
        "craft_time": 300,  # 5 минут
        "level": 1,
        "requires": {"copperOre": 1},  # 1 медная руда
        "minerals": 1,  # 1 минерал (ресурс игрока)
    },
    "copperBar": {
        "name": "Медный Слиток",
        "start_url": None,  # особый путь через level=2
        "craft_time": 600,  # 10 минут
        "level": 2,
        "prof_page": "/profs/prof/miningMaster?level=2",
        "craft_action": "CAP_craftReceipt",
        "receipt": "copperBar",
        "requires": {"copper": 10},  # 10 меди
        "minerals": 10,  # 10 минералов (ресурс игрока)
    },
    "bronze": {
        "name": "Бронза",
        "start_url": None,  # особый путь через level=2
        "craft_time": 900,  # 15 минут
        "level": 2,
        "prof_page": "/profs/prof/miningMaster?level=2",
        "craft_action": "CAP_craftReceipt",
        "receipt": "bronze",
        "requires": {"rawOre": 3, "copper": 2},  # 3 жел.руды + 2 меди
        "minerals": 2,  # 2 минерала (ресурс игрока)
    },
    "bronzeBar": {
        "name": "Бронзовый Слиток",
        "start_url": None,  # особый путь через level=3
        "craft_time": 600,  # 10 минут
        "level": 3,
        "prof_page": "/profs/prof/miningMaster?level=3",
        "craft_action": "CAP_craftReceipt",
        "receipt": "bronzeBar",
        "requires": {"bronze": 5},  # 5 бронзы
    },
    # === Платиновая цепочка ===
    "platinum": {
        "name": "Платина",
        "start_url": None,  # особый путь через level=3
        "craft_time": 1800,  # 30 минут
        "level": 3,
        "prof_page": "/profs/prof/miningMaster?level=3",
        "craft_action": "CAP_craftReceipt",
        "receipt": "platinum",
        "requires": {"rawOre": 25},  # 25 жел.руды
        "minerals": 25,  # 25 минералов (ресурс игрока)
    },
    "platinumBar": {
        "name": "Платиновый Слиток",
        "start_url": None,  # особый путь через level=3
        "craft_time": 600,  # 10 минут
        "level": 3,
        "prof_page": "/profs/prof/miningMaster?level=3",
        "craft_action": "CAP_craftReceipt",
        "receipt": "platinumBar",
        "requires": {"platinum": 5},  # 5 платины
    },
    # === Торовая цепочка ===
    "thor": {
        "name": "Тор",
        "start_url": None,  # особый путь через level=2
        "craft_time": 1200,  # 20 минут
        "level": 2,
        "prof_page": "/profs/prof/miningMaster?level=2",
        "craft_action": "CAP_craftReceipt",
        "receipt": "tor",  # В игре "tor", не "thor"!
        "requires": {"rawOre": 5, "iron": 3},  # 5 жел.руды + 3 железа
        "minerals": 10,  # 10 минералов
    },
    "thorBar": {
        "name": "Слиток Тора",
        "start_url": None,  # особый путь через level=3
        "craft_time": 600,  # 10 минут
        "level": 3,
        "prof_page": "/profs/prof/miningMaster?level=3",
        "craft_action": "CAP_craftReceipt",
        "receipt": "torBar",  # В игре "torBar", не "thorBar"!
        "requires": {"thor": 5},  # 5 тора
    },
    # === Сумеречные материалы (4 уровень) ===
    "twilightSteel": {
        "name": "Сумеречная Сталь",
        "start_url": None,  # особый путь через level=4
        "craft_time": 2400,  # 40 минут
        "level": 4,
        "prof_page": "/profs/prof/miningMaster?level=4",
        "craft_action": "CAP_craftReceipt",
        "receipt": "twilightSteel",
        "requires": {"ironBar": 3, "thor": 2, "platinum": 5},  # 3 жел.слитка + 2 тора + 5 платины
    },
    "twilightAnthracite": {
        "name": "Сумеречный Антрацит",
        "start_url": None,  # особый путь через level=4
        "craft_time": 2400,  # 40 минут
        "level": 4,
        "prof_page": "/profs/prof/miningMaster?level=4",
        "craft_action": "CAP_craftReceipt",
        "receipt": "twilightAnthracite",
        "requires": {"ironBar": 3, "thorBar": 2, "platinum": 5},  # 3 жел.слитка + 2 слитка тора + 5 платины
        "sapphires": 50,  # 50 сапфиров (ресурс игрока)
        "rubies": 10,  # 10 рубинов (ресурс игрока)
    },
}

# Порядок крафта для железных слитков
CRAFT_ORDER_IRON = ["rawOre", "iron", "ironBar"]

# Порядок крафта для бронзы
# Сначала накапливаем медную руду, потом жел.руду, потом крафтим медь, потом бронзу
CRAFT_ORDER_BRONZE = ["copperOre", "rawOre", "copper", "bronze"]

# Кэш страниц пагинации для рецептов (receipt_id -> page_number)
# Если нашли рецепт на странице 2, запоминаем чтобы сразу туда идти
_RECIPE_PAGE_CACHE = {}


def get_recipe(recipe_id: str) -> dict:
    """Получает рецепт по ID"""
    return RECIPES.get(recipe_id, {})


def get_item_name(item_id: str) -> str:
    """Получает русское название предмета"""
    return ITEM_NAMES.get(item_id, item_id)


def get_craft_time(recipe_id: str) -> int:
    """Получает время крафта в секундах"""
    recipe = RECIPES.get(recipe_id, {})
    return recipe.get("craft_time", 300)


def get_recipe_level(recipe_id: str) -> int:
    """Получает уровень рецепта"""
    recipe = RECIPES.get(recipe_id, {})
    return recipe.get("level", 1)


def get_recipe_requires(recipe_id: str) -> dict:
    """Получает требования рецепта"""
    recipe = RECIPES.get(recipe_id, {})
    return recipe.get("requires", {})
