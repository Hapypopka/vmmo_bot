# ============================================
# VMMO Craft Price Checker
# ============================================
# Получает цены с аукциона для расчёта профитности крафта
# ============================================

import re
import time
import json
import os
from urllib.parse import urlencode, quote
from bs4 import BeautifulSoup

from requests_bot.config import BASE_URL
from requests_bot.craft import RECIPES, ITEM_NAMES

# Путь к общему кэшу цен (доступен всем персонажам)
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED_CACHE_FILE = os.path.join(SCRIPT_DIR, "shared_auction_cache.json")
CACHE_TTL = 14400  # 4 часа в секундах

# Путь к файлу локов крафта (распределение между ботами)
CRAFT_LOCKS_FILE = os.path.join(SCRIPT_DIR, "shared_craft_locks.json")
CRAFT_LOCKS_LOCKFILE = os.path.join(SCRIPT_DIR, "shared_craft_locks.lock")
LOCK_TTL = 7200  # 2 часа - лок протухает если бот не обновил

# Комиссия аукциона (5%)
AUCTION_FEE = 0.05

# File lock для атомарных операций с локами
import fcntl

class FileLock:
    """Простой file lock для синхронизации между процессами"""
    def __init__(self, lockfile):
        self.lockfile = lockfile
        self.fd = None

    def __enter__(self):
        self.fd = open(self.lockfile, 'w')
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        self.fd.close()
        return False

# Все профитные рецепты для автовыбора
# Исключены: copperOre (убыточная), twilightSteel/twilightAnthracite (требуют сапфиры/рубины)
FINAL_RECIPES = [
    "ironBar",       # Железный Слиток
    "copperBar",     # Медный Слиток
    "bronzeBar",     # Бронзовый Слиток
    "platinumBar",   # Платиновый Слиток
    "thorBar",       # Слиток Тора
    "bronze",        # Бронза
    "iron",          # Железо
    "platinum",      # Платина
    "rawOre",        # Железная Руда
    "thor",          # Тор
    "copper",        # Медь
]


# ============================================
# Система локов для распределения крафта между ботами
# ============================================

def load_craft_locks():
    """
    Загружает локи крафта из файла.

    Returns:
        dict: {profile: {"recipe_id": "ironBar", "timestamp": 123456789}, ...}
    """
    if not os.path.exists(CRAFT_LOCKS_FILE):
        return {}

    try:
        with open(CRAFT_LOCKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка чтения локов: {e}")
        return {}


def save_craft_locks(locks):
    """Сохраняет локи крафта в файл."""
    try:
        with open(CRAFT_LOCKS_FILE, "w", encoding="utf-8") as f:
            json.dump(locks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка сохранения локов: {e}")


def get_recipe_bot_counts():
    """
    Подсчитывает сколько активных ботов на каждом рецепте.
    Протухшие локи (>2ч) не считаются.

    Структура локов: {profile: {"recipe_id": "ironBar", "timestamp": 123}, ...}

    Returns:
        dict: {recipe_id: count, ...}
    """
    locks = load_craft_locks()
    now = time.time()
    counts = {recipe: 0 for recipe in FINAL_RECIPES}

    for profile, lock_info in locks.items():
        recipe_id = lock_info.get("recipe_id")
        if not recipe_id or recipe_id not in FINAL_RECIPES:
            continue

        # Проверяем не протух ли лок
        timestamp = lock_info.get("timestamp", 0)
        if now - timestamp > LOCK_TTL:
            continue  # Протух - не считаем

        counts[recipe_id] = counts.get(recipe_id, 0) + 1

    return counts


def get_sorted_recipes_by_profit():
    """
    Возвращает список рецептов отсортированных по профиту (из кэша).

    Returns:
        list: [(recipe_id, profit_per_hour), ...] отсортированный по убыванию профита
    """
    cached_prices = load_shared_cache()
    if not cached_prices:
        # Нет кэша - возвращаем в дефолтном порядке
        return [(r, 0) for r in FINAL_RECIPES]

    recipe_profits = []

    for recipe_id in FINAL_RECIPES:
        if recipe_id not in RECIPES:
            continue

        recipe = RECIPES[recipe_id]
        result_name = recipe["name"]
        sell_price = cached_prices.get(result_name, 0)

        if sell_price <= 0:
            recipe_profits.append((recipe_id, 0))
            continue

        # Расчёт себестоимости
        reqs = _get_full_requirements_static(recipe_id)
        mineral_price = cached_prices.get("Минерал", 0)

        total_cost = (
            reqs["minerals"] * mineral_price +
            reqs["silver"] / 100.0
        )
        total_time = reqs["total_time"]

        if total_time <= 0:
            recipe_profits.append((recipe_id, 0))
            continue

        # Учитываем комиссию аукциона 5%
        net_sell_price = sell_price * (1 - AUCTION_FEE)
        profit = net_sell_price - total_cost
        profit_per_hour = (profit / total_time) * 3600
        recipe_profits.append((recipe_id, profit_per_hour))

    # Сортируем по профиту (убывание)
    recipe_profits.sort(key=lambda x: x[1], reverse=True)
    return recipe_profits


def acquire_craft_lock(profile):
    """
    Берёт лок на крафт для профиля (с file lock для атомарности).

    Структура: {profile: {"recipe_id": "ironBar", "timestamp": 123}, ...}

    Логика:
    1. Если у профиля есть активный лок - продлеваем
    2. Считаем сколько ботов на каждом рецепте (без протухших)
    3. Находим минимальное кол-во
    4. Среди рецептов с минимумом берём самый выгодный

    Args:
        profile: имя профиля (char1, char2, ...)

    Returns:
        str: recipe_id который взяли
    """
    try:
        with FileLock(CRAFT_LOCKS_LOCKFILE):
            locks = load_craft_locks()
            now = time.time()

            # Проверяем - может у нас уже есть активный лок?
            if profile in locks:
                lock_info = locks[profile]
                if now - lock_info.get("timestamp", 0) <= LOCK_TTL:
                    # Наш лок ещё активен - обновляем и возвращаем
                    recipe_id = lock_info.get("recipe_id")
                    locks[profile]["timestamp"] = now
                    save_craft_locks(locks)
                    return recipe_id

            # Считаем ботов на каждом рецепте (внутри лока!)
            bot_counts = {recipe: 0 for recipe in FINAL_RECIPES}
            for p, lock_info in locks.items():
                recipe_id = lock_info.get("recipe_id")
                if not recipe_id or recipe_id not in FINAL_RECIPES:
                    continue
                timestamp = lock_info.get("timestamp", 0)
                if now - timestamp > LOCK_TTL:
                    continue  # Протух - не считаем
                bot_counts[recipe_id] = bot_counts.get(recipe_id, 0) + 1

            # Получаем рецепты отсортированные по профиту
            sorted_recipes = get_sorted_recipes_by_profit()

            # Находим минимальное кол-во ботов
            min_count = min(bot_counts.values()) if bot_counts else 0

            # Среди рецептов с минимумом ботов берём самый выгодный
            for recipe_id, profit in sorted_recipes:
                if bot_counts.get(recipe_id, 0) == min_count:
                    # Берём этот рецепт
                    locks[profile] = {"recipe_id": recipe_id, "timestamp": now}
                    save_craft_locks(locks)
                    print(f"[CRAFT_LOCKS] {profile}: взял {recipe_id} (ботов: {min_count}, профит: {profit:.1f}з/ч)")
                    return recipe_id

            # Fallback - первый из списка
            recipe_id = FINAL_RECIPES[0]
            locks[profile] = {"recipe_id": recipe_id, "timestamp": now}
            save_craft_locks(locks)
            print(f"[CRAFT_LOCKS] {profile}: fallback на {recipe_id}")
            return recipe_id

    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка acquire_craft_lock: {e}")
        return FINAL_RECIPES[0]  # fallback без лока


def refresh_craft_lock(profile, recipe_id):
    """
    Обновляет timestamp лока (вызывать при продаже партии).
    Использует file lock для атомарности.

    Структура: {profile: {"recipe_id": "ironBar", "timestamp": 123, "current": 0, "batch": 5}, ...}

    Args:
        profile: имя профиля
        recipe_id: ID рецепта
    """
    try:
        with FileLock(CRAFT_LOCKS_LOCKFILE):
            locks = load_craft_locks()
            now = time.time()

            # Обновляем/создаём лок для профиля (сбрасываем прогресс после продажи)
            locks[profile] = {"recipe_id": recipe_id, "timestamp": now, "current": 0, "batch": 5}
            save_craft_locks(locks)
            print(f"[CRAFT_LOCKS] {profile}: обновил лок на {recipe_id}")
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка refresh_craft_lock: {e}")


def update_craft_progress(profile, recipe_id, current_count, batch_size):
    """
    Обновляет прогресс крафта (текущее количество / цель).
    Вызывается после проверки инвентаря.

    Args:
        profile: имя профиля
        recipe_id: ID рецепта
        current_count: текущее количество в инвентаре
        batch_size: целевое количество для партии
    """
    try:
        with FileLock(CRAFT_LOCKS_LOCKFILE):
            locks = load_craft_locks()
            now = time.time()

            # Обновляем прогресс
            locks[profile] = {
                "recipe_id": recipe_id,
                "timestamp": now,
                "current": current_count,
                "batch": batch_size
            }
            save_craft_locks(locks)
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка update_craft_progress: {e}")


def release_craft_lock(profile):
    """
    Освобождает лок профиля (опционально, при остановке бота).

    Структура: {profile: {"recipe_id": "ironBar", "timestamp": 123}, ...}

    Args:
        profile: имя профиля
    """
    try:
        with FileLock(CRAFT_LOCKS_LOCKFILE):
            locks = load_craft_locks()

            if profile in locks:
                recipe_id = locks[profile].get("recipe_id")
                del locks[profile]
                save_craft_locks(locks)
                print(f"[CRAFT_LOCKS] {profile}: освободил {recipe_id}")
    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка release_craft_lock: {e}")


# Категории аукциона для разных типов предметов
# Сырьё: /auction?category=resources&sub_resources=materials
# Ресурсы: /auction?category=resources&sub_resources=stones
AUCTION_CATEGORIES = {
    # Сырьё (вкладка "Сырьё") - крафтовые материалы
    "materials": {
        "category": "resources",
        "sub_resources": "materials",
        "items": [
            "Железная Руда", "Железо", "Железный Слиток",
            "Медная Руда", "Медь", "Медный Слиток",
            "Бронза", "Бронзовый Слиток",
            "Тор", "Слиток Тора",
            "Платина", "Платиновый Слиток",
            "Сумеречная Сталь", "Сумеречный Антрацит",
        ]
    },
    # Ресурсы (вкладка "Ресурсы") - минералы, камни
    "stones": {
        "category": "resources",
        "sub_resources": "stones",
        "items": ["Минерал", "Сапфир", "Рубин"]
    },
}


def load_shared_cache():
    """
    Загружает общий кэш цен из файла.

    Returns:
        dict: {"prices": {item_name: price}, "timestamp": int}
    """
    if not os.path.exists(SHARED_CACHE_FILE):
        return None

    try:
        with open(SHARED_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

        # Проверяем срок действия
        timestamp = cache.get("timestamp", 0)
        age = time.time() - timestamp

        if age > CACHE_TTL:
            print(f"[CACHE] Кэш устарел ({age/3600:.1f}ч), обновляем...")
            return None

        print(f"[CACHE] Используем кэш (возраст: {age/3600:.1f}ч)")
        return cache.get("prices", {})
    except Exception as e:
        print(f"[CACHE] Ошибка чтения кэша: {e}")
        return None


def save_shared_cache(prices):
    """
    Сохраняет цены в общий кэш.

    Args:
        prices: dict {item_name: price}
    """
    try:
        cache = {
            "prices": prices,
            "timestamp": int(time.time())
        }
        with open(SHARED_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        print(f"[CACHE] Сохранено {len(prices)} цен в общий кэш")
    except Exception as e:
        print(f"[CACHE] Ошибка сохранения кэша: {e}")


def get_cached_price(item_name):
    """
    Получает цену из кэша без загрузки всего кэша.

    Args:
        item_name: название предмета

    Returns:
        float or None: цена или None если не найдена
    """
    cached_prices = load_shared_cache()
    if cached_prices:
        return cached_prices.get(item_name)
    return None


def is_cache_expired():
    """
    Проверяет истёк ли кэш цен.

    Returns:
        bool: True если кэш устарел или не существует
    """
    if not os.path.exists(SHARED_CACHE_FILE):
        return True

    try:
        with open(SHARED_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

        timestamp = cache.get("timestamp", 0)
        age = time.time() - timestamp
        return age > CACHE_TTL
    except Exception:
        return True


def get_best_craft_from_cache():
    """
    Возвращает самый выгодный предмет для крафта на основе кэша цен.

    Логика:
    1. Загружает кэш цен
    2. Если кэш устарел - возвращает (None, True) = нужно обновить
    3. Вычисляет profit_per_hour для каждого финального рецепта
    4. Возвращает (item_id, False) самого выгодного

    Финальные рецепты (то что продаётся):
    - ironBar (Железный Слиток)
    - copperBar (Медный Слиток)
    - bronzeBar (Бронзовый Слиток)
    - platinumBar (Платиновый Слиток)
    - thorBar (Слиток Тора)
    - twilightSteel (Сумеречная Сталь)
    - twilightAnthracite (Сумеречный Антрацит)

    Returns:
        tuple: (item_id: str or None, needs_refresh: bool)
    """
    # Проверяем кэш
    if is_cache_expired():
        print("[CRAFT_PRICES] Кэш устарел, требуется обновление")
        return (None, True)

    cached_prices = load_shared_cache()
    if not cached_prices:
        print("[CRAFT_PRICES] Кэш пуст, требуется обновление")
        return (None, True)

    # Используем глобальную константу FINAL_RECIPES
    best_recipe = None
    best_profit_per_hour = -float('inf')

    for recipe_id in FINAL_RECIPES:
        if recipe_id not in RECIPES:
            continue

        recipe = RECIPES[recipe_id]
        result_name = recipe["name"]

        # Цена продажи
        sell_price = cached_prices.get(result_name, 0)
        if sell_price <= 0:
            continue

        # Расчёт полной себестоимости "с нуля"
        # Используем рекурсивный расчёт через временный checker
        total_cost = 0
        total_time = 0

        # Простой расчёт себестоимости по кэшу
        # Минералы - основной ресурс
        mineral_price = cached_prices.get("Минерал", 0)
        sapphire_price = cached_prices.get("Сапфир", 0)
        ruby_price = cached_prices.get("Рубин", 0)

        # Получаем полные требования для рецепта
        reqs = _get_full_requirements_static(recipe_id)

        total_cost = (
            reqs["minerals"] * mineral_price +
            reqs["sapphires"] * sapphire_price +
            reqs["rubies"] * ruby_price +
            reqs["silver"] / 100.0  # серебро в золото
        )
        total_time = reqs["total_time"]

        if total_time <= 0:
            continue

        # Учитываем комиссию аукциона 5%
        net_sell_price = sell_price * (1 - AUCTION_FEE)
        profit = net_sell_price - total_cost
        profit_per_hour = (profit / total_time) * 3600

        print(f"[CRAFT_PRICES] {result_name}: продажа={sell_price:.2f}з (-5%={net_sell_price:.2f}з), себестоимость={total_cost:.2f}з, "
              f"профит={profit:.2f}з, профит/час={profit_per_hour:.2f}з")

        if profit_per_hour > best_profit_per_hour:
            best_profit_per_hour = profit_per_hour
            best_recipe = recipe_id

    if best_recipe:
        print(f"[CRAFT_PRICES] Лучший крафт: {best_recipe} ({best_profit_per_hour:.2f}з/час)")
        return (best_recipe, False)

    print("[CRAFT_PRICES] Не найден выгодный крафт")
    return (None, True)


def _get_full_requirements_static(recipe_id, count=1):
    """
    Статическая версия get_full_requirements без необходимости создавать CraftPriceChecker.
    Рекурсивно вычисляет все базовые ресурсы для крафта.

    Returns:
        dict: {"minerals": int, "sapphires": int, "rubies": int, "silver": int, "total_time": int}
    """
    if recipe_id not in RECIPES:
        return {"minerals": 0, "sapphires": 0, "rubies": 0, "silver": 0, "total_time": 0}

    recipe = RECIPES[recipe_id]
    result = {
        "minerals": 0,
        "sapphires": 0,
        "rubies": 0,
        "silver": 0,
        "total_time": 0,
    }

    # Время на сам крафт
    result["total_time"] = recipe.get("craft_time", 0) * count

    # Ресурсы этого рецепта
    if "minerals" in recipe:
        result["minerals"] = recipe["minerals"] * count
    if "sapphires" in recipe:
        result["sapphires"] = recipe["sapphires"] * count
    if "rubies" in recipe:
        result["rubies"] = recipe["rubies"] * count
    if "silver" in recipe:
        result["silver"] = recipe["silver"] * count

    # Рекурсивно обрабатываем зависимости
    if "requires" in recipe:
        for req_id, req_count in recipe["requires"].items():
            total_req = req_count * count
            sub_req = _get_full_requirements_static(req_id, total_req)

            result["minerals"] += sub_req["minerals"]
            result["sapphires"] += sub_req["sapphires"]
            result["rubies"] += sub_req["rubies"]
            result["silver"] += sub_req["silver"]
            result["total_time"] += sub_req["total_time"]

    return result


def get_optimal_batch_size(recipe_id):
    """
    Определяет оптимальный batch_size для продажи на основе времени крафта.

    Логика:
    - Очень долгий крафт (> 3ч) → 1 шт (платиновый слиток)
    - Долгий (1-3ч) → 2-3 шт (бронзовый слиток, слиток тора)
    - Средний (30м-1ч) → 5 шт (железный слиток, медный слиток)
    - Быстрый (10-30м) → 7 шт (бронза, железо)
    - Очень быстрый (< 10м) → 10 шт (медь, руда)

    Args:
        recipe_id: ID рецепта

    Returns:
        int: оптимальный batch_size
    """
    if recipe_id not in RECIPES:
        return 5  # дефолт

    # Получаем полное время крафта "с нуля"
    reqs = _get_full_requirements_static(recipe_id)
    total_time_sec = reqs["total_time"]
    total_time_min = total_time_sec / 60

    # Определяем batch_size по времени
    if total_time_min > 180:  # > 3 часов
        return 1
    elif total_time_min > 120:  # 2-3 часа
        return 2
    elif total_time_min > 60:  # 1-2 часа
        return 3
    elif total_time_min > 30:  # 30м - 1ч
        return 5
    elif total_time_min > 10:  # 10-30м
        return 7
    else:  # < 10м
        return 10


def refresh_craft_prices_cache(client):
    """
    Обновляет кэш цен крафта через HTTP запросы к аукциону.

    Вызывается ботом когда кэш устарел.

    Args:
        client: VMMOClient instance

    Returns:
        bool: True если успешно обновлено
    """
    try:
        print("[CRAFT_PRICES] Обновляю кэш цен с аукциона...")
        checker = CraftPriceChecker(client, use_cache=False)
        prices = checker.get_all_craft_prices()

        if prices and len(prices) > 0:
            print(f"[CRAFT_PRICES] Кэш обновлён: {len(prices)} цен")
            return True
        else:
            print("[CRAFT_PRICES] Не удалось получить цены")
            return False
    except Exception as e:
        print(f"[CRAFT_PRICES] Ошибка обновления кэша: {e}")
        return False


class CraftPriceChecker:
    """Получает цены с аукциона для крафтовых материалов"""

    def __init__(self, client, use_cache=True):
        """
        Args:
            client: VMMOClient instance
            use_cache: использовать ли общий кэш (по умолчанию True)
        """
        self.client = client
        self.prices = {}  # {item_name: price_per_unit}
        self._full_cost_cache = {}  # кэш для рекурсивных расчётов
        self.use_cache = use_cache

    # ============================================
    # Рекурсивный расчёт полной себестоимости "с нуля"
    # ============================================

    def get_full_requirements(self, recipe_id, count=1):
        """
        Рекурсивно вычисляет ВСЕ базовые ресурсы для крафта.

        Args:
            recipe_id: ID рецепта (например "platinumBar")
            count: сколько штук крафтим

        Returns:
            dict: {
                "minerals": int,  # всего минералов
                "sapphires": int,  # всего сапфиров
                "rubies": int,  # всего рубинов
                "silver": int,  # всего серебра (игровая валюта)
                "total_time": int,  # общее время в секундах
                "craft_steps": list,  # этапы крафта
            }
        """
        if recipe_id not in RECIPES:
            return {"minerals": 0, "sapphires": 0, "rubies": 0, "silver": 0, "total_time": 0, "craft_steps": []}

        recipe = RECIPES[recipe_id]
        result = {
            "minerals": 0,
            "sapphires": 0,
            "rubies": 0,
            "silver": 0,
            "total_time": 0,
            "craft_steps": [],
        }

        # Время на сам крафт этого предмета
        result["total_time"] = recipe.get("craft_time", 0) * count

        # Минералы этого рецепта
        if "minerals" in recipe:
            result["minerals"] = recipe["minerals"] * count

        # Сапфиры и рубины этого рецепта
        if "sapphires" in recipe:
            result["sapphires"] = recipe["sapphires"] * count
        if "rubies" in recipe:
            result["rubies"] = recipe["rubies"] * count

        # Серебро (игровая валюта, 100 серебра = 1 золото)
        if "silver" in recipe:
            result["silver"] = recipe["silver"] * count

        # Добавляем этот шаг
        result["craft_steps"].append({
            "recipe": recipe_id,
            "name": recipe["name"],
            "count": count,
            "time": recipe.get("craft_time", 0) * count,
        })

        # Рекурсивно обрабатываем зависимости
        if "requires" in recipe:
            for req_id, req_count in recipe["requires"].items():
                total_req = req_count * count  # сколько нужно для count штук

                # Рекурсивно получаем требования для компонента
                sub_req = self.get_full_requirements(req_id, total_req)

                result["minerals"] += sub_req["minerals"]
                result["sapphires"] += sub_req["sapphires"]
                result["rubies"] += sub_req["rubies"]
                result["silver"] += sub_req["silver"]
                result["total_time"] += sub_req["total_time"]

                # Вставляем шаги компонентов ПЕРЕД текущим шагом
                result["craft_steps"] = sub_req["craft_steps"] + result["craft_steps"]

        return result

    def calculate_full_cost(self, recipe_id):
        """
        Рассчитывает ПОЛНУЮ себестоимость крафта с нуля (только из минералов/сапфиров/рубинов + серебро).

        Returns:
            dict: {
                "minerals": int,
                "sapphires": int,
                "rubies": int,
                "silver": int,  # серебра (игровая валюта)
                "total_time": int,  # секунды
                "mineral_cost": float,  # стоимость минералов
                "sapphire_cost": float,
                "ruby_cost": float,
                "silver_cost": float,  # стоимость серебра (silver / 100)
                "total_cost": float,  # общая себестоимость
            }
        """
        reqs = self.get_full_requirements(recipe_id, 1)

        mineral_price = self.prices.get("Минерал", 0)
        sapphire_price = self.prices.get("Сапфир", 0)
        ruby_price = self.prices.get("Рубин", 0)

        mineral_cost = reqs["minerals"] * mineral_price
        sapphire_cost = reqs["sapphires"] * sapphire_price
        ruby_cost = reqs["rubies"] * ruby_price
        # Серебро: 100 серебра = 1 золото
        silver_cost = reqs["silver"] / 100.0

        return {
            "minerals": reqs["minerals"],
            "sapphires": reqs["sapphires"],
            "rubies": reqs["rubies"],
            "silver": reqs["silver"],
            "total_time": reqs["total_time"],
            "craft_steps": reqs["craft_steps"],
            "mineral_cost": mineral_cost,
            "sapphire_cost": sapphire_cost,
            "ruby_cost": ruby_cost,
            "silver_cost": silver_cost,
            "total_cost": mineral_cost + sapphire_cost + ruby_cost + silver_cost,
        }

    def get_category_for_item(self, item_name):
        """Определяет категорию аукциона для предмета"""
        for cat_id, cat_info in AUCTION_CATEGORIES.items():
            if item_name in cat_info["items"]:
                return cat_info
        return None

    def search_item(self, item_name):
        """
        Ищет предмет на аукционе и возвращает цену за 1 шт.

        Args:
            item_name: Название предмета (например "Минерал")

        Returns:
            float or None: Цена за 1 шт в золоте (с учётом серебра)
        """
        category = self.get_category_for_item(item_name)
        if not category:
            print(f"[PRICES] Неизвестная категория для '{item_name}'")
            return None

        # Формируем URL поиска
        # /auction?category=resources&sub_resources=materials&ppAction=search&name=Железо
        params = {
            "category": category["category"],
            "sub_resources": category["sub_resources"],
            "ppAction": "search",
            "name": item_name,
        }

        search_url = f"{BASE_URL}/auction?" + urlencode(params, encoding='utf-8')

        print(f"[PRICES] Ищу '{item_name}' на аукционе...")

        try:
            self.client.get(search_url)
            soup = self.client.soup()

            if not soup:
                print(f"[PRICES] Не удалось загрузить страницу")
                return None

            # Парсим первый лот
            lot = soup.select_one("div.list-el")
            if not lot:
                print(f"[PRICES] Нет лотов для '{item_name}'")
                return None

            # Получаем количество (формат: x1000)
            text = lot.get_text()
            qty_match = re.search(r'x(\d+)', text)
            qty = int(qty_match.group(1)) if qty_match else 1

            # Получаем цену из блока _auction
            auction_div = lot.select_one("div._auction")
            if not auction_div:
                # Альтернативный поиск цены
                auction_div = lot.select_one("div.b-actions")

            if not auction_div:
                print(f"[PRICES] Не найден блок цены")
                return None

            # Парсим цену по иконкам валюты
            # Формат: <span class="i12 i12-money_gold"></span><span>73</span>
            #         <span class="i12 i12-money_silver"></span><span>90</span>
            gold = 0
            silver = 0

            gold_icon = auction_div.select_one("span.i12-money_gold")
            silver_icon = auction_div.select_one("span.i12-money_silver")

            if gold_icon:
                next_span = gold_icon.find_next_sibling("span")
                if next_span and next_span.get_text(strip=True).isdigit():
                    gold = int(next_span.get_text(strip=True))

            if silver_icon:
                next_span = silver_icon.find_next_sibling("span")
                if next_span and next_span.get_text(strip=True).isdigit():
                    silver = int(next_span.get_text(strip=True))

            if gold == 0 and silver == 0:
                print(f"[PRICES] Не удалось распарсить цену")
                return None

            # Цена за 1 шт (золото + серебро/100)
            total_price = gold + silver / 100.0
            price_per_unit = total_price / qty

            print(f"[PRICES] {item_name}: {qty} шт за {gold}з {silver}с = {price_per_unit:.4f}з/шт")

            return price_per_unit

        except Exception as e:
            print(f"[PRICES] Ошибка поиска '{item_name}': {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_all_craft_prices(self):
        """
        Получает цены на все крафтовые материалы.
        Использует общий кэш если доступен.

        Returns:
            dict: {item_name: price_per_unit}
        """
        # Пытаемся загрузить из кэша
        if self.use_cache:
            cached_prices = load_shared_cache()
            if cached_prices:
                self.prices = cached_prices
                print(f"[PRICES] Загружено {len(cached_prices)} цен из кэша")
                return cached_prices

        # Кэш не найден - парсим с аукциона
        # Собираем все уникальные названия
        all_items = set()

        # Из рецептов
        for recipe_id, recipe in RECIPES.items():
            all_items.add(recipe["name"])
            if "requires" in recipe:
                for req_id in recipe["requires"]:
                    if req_id in ITEM_NAMES:
                        all_items.add(ITEM_NAMES[req_id])

        # Ресурсы для крафта
        all_items.add("Минерал")
        all_items.add("Сапфир")
        all_items.add("Рубин")

        print(f"[PRICES] Парсим цены для {len(all_items)} предметов с аукциона...")

        prices = {}
        for item_name in sorted(all_items):
            price = self.search_item(item_name)
            if price is not None:
                prices[item_name] = price
            time.sleep(0.5)  # Пауза между запросами

        self.prices = prices

        # Всегда сохраняем в общий кэш после парсинга
        # use_cache контролирует только ЧТЕНИЕ, не запись
        save_shared_cache(prices)

        return prices

    def calculate_craft_profit(self, recipe_id):
        """
        Рассчитывает профит от крафта.

        Args:
            recipe_id: ID рецепта из RECIPES

        Returns:
            dict: {
                "sell_price": float,  # цена продажи
                "cost": float,  # стоимость материалов
                "profit": float,  # профит
                "profit_percent": float,  # профит в %
                "materials": dict,  # стоимость каждого материала
            }
        """
        if recipe_id not in RECIPES:
            return None

        recipe = RECIPES[recipe_id]
        result_name = recipe["name"]

        # Цена продажи результата
        sell_price = self.prices.get(result_name, 0)

        # Стоимость материалов
        total_cost = 0
        materials_cost = {}

        if "requires" in recipe:
            for req_id, req_count in recipe["requires"].items():
                req_name = ITEM_NAMES.get(req_id, req_id)
                req_price = self.prices.get(req_name, 0)
                cost = req_price * req_count
                materials_cost[req_name] = cost
                total_cost += cost

        # Стоимость минералов (если требуются)
        if "minerals" in recipe and recipe["minerals"] > 0:
            mineral_price = self.prices.get("Минерал", 0)
            mineral_cost = mineral_price * recipe["minerals"]
            materials_cost["Минерал"] = mineral_cost
            total_cost += mineral_cost

        # Сапфиры и рубины
        if "sapphires" in recipe:
            sapphire_price = self.prices.get("Сапфир", 0)
            sapphire_cost = sapphire_price * recipe["sapphires"]
            materials_cost["Сапфир"] = sapphire_cost
            total_cost += sapphire_cost

        if "rubies" in recipe:
            ruby_price = self.prices.get("Рубин", 0)
            ruby_cost = ruby_price * recipe["rubies"]
            materials_cost["Рубин"] = ruby_cost
            total_cost += ruby_cost

        # Учитываем комиссию аукциона 5%
        net_sell_price = sell_price * (1 - AUCTION_FEE)
        profit = net_sell_price - total_cost
        profit_percent = (profit / total_cost * 100) if total_cost > 0 else 0

        return {
            "name": result_name,
            "sell_price": sell_price,  # цена до комиссии (для отображения)
            "net_sell_price": net_sell_price,  # цена после комиссии
            "cost": total_cost,
            "profit": profit,
            "profit_percent": profit_percent,
            "materials": materials_cost,
            "craft_time": recipe.get("craft_time", 0),
        }

    def calculate_buy_profit(self, recipe_id):
        """
        Рассчитывает профит при ПОКУПКЕ компонентов (а не крафте их).

        Например, для Медного Слитка:
        - Покупаем 10 меди на аукционе
        - Тратим только 10 минералов
        - Крафтим только последний шаг (10 мин)

        Returns:
            dict с buy_cost, buy_profit, buy_time, buy_profit_per_hour
        """
        if recipe_id not in RECIPES:
            return None

        recipe = RECIPES[recipe_id]
        result_name = recipe["name"]

        # Цена продажи результата
        sell_price = self.prices.get(result_name, 0)
        if sell_price == 0:
            return None

        # Стоимость = покупка компонентов + минералы рецепта
        total_cost = 0

        # Покупаем компоненты на аукционе
        components_info = []
        if "requires" in recipe:
            for req_id, req_count in recipe["requires"].items():
                req_name = ITEM_NAMES.get(req_id, req_id)
                req_price = self.prices.get(req_name, 0)
                component_cost = req_price * req_count
                total_cost += component_cost
                components_info.append(f"{req_count}× {req_name}")

        # Плюс минералы самого рецепта
        mineral_price = self.prices.get("Минерал", 0)
        minerals_needed = recipe.get("minerals", 0)
        total_cost += minerals_needed * mineral_price

        # Плюс сапфиры/рубины если есть
        sapphire_price = self.prices.get("Сапфир", 0)
        ruby_price = self.prices.get("Рубин", 0)
        sapphires_needed = recipe.get("sapphires", 0)
        rubies_needed = recipe.get("rubies", 0)
        total_cost += sapphires_needed * sapphire_price
        total_cost += rubies_needed * ruby_price

        # Плюс серебро (игровая валюта)
        silver_needed = recipe.get("silver", 0)
        total_cost += silver_needed / 100.0

        # Время = только этот крафт
        craft_time = recipe.get("craft_time", 0)

        # Профит (учитываем комиссию аукциона 5%)
        net_sell_price = sell_price * (1 - AUCTION_FEE)
        profit = net_sell_price - total_cost
        profit_percent = (profit / total_cost * 100) if total_cost > 0 else 0
        profit_per_hour = (profit / craft_time * 3600) if craft_time > 0 else 0

        return {
            "buy_cost": total_cost,
            "buy_profit": profit,
            "buy_profit_percent": profit_percent,
            "buy_time": craft_time,
            "buy_profit_per_hour": profit_per_hour,
            "buy_components": ", ".join(components_info) if components_info else "нет",
            "buy_minerals": minerals_needed,
            "buy_sapphires": sapphires_needed,
            "buy_rubies": rubies_needed,
            "buy_silver": silver_needed,
        }

    def get_all_profits(self):
        """
        Рассчитывает профит для всех рецептов.
        Включает полный расчёт "с нуля" (минералы, время, себестоимость).
        И расчёт "с покупкой" компонентов.

        Returns:
            list: Отсортированный по профиту список рецептов
        """
        profits = []

        for recipe_id in RECIPES:
            profit_info = self.calculate_craft_profit(recipe_id)
            if profit_info:
                profit_info["recipe_id"] = recipe_id

                # Добавляем полный расчёт "с нуля"
                full_cost = self.calculate_full_cost(recipe_id)
                profit_info["full_minerals"] = full_cost["minerals"]
                profit_info["full_sapphires"] = full_cost["sapphires"]
                profit_info["full_rubies"] = full_cost["rubies"]
                profit_info["full_silver"] = full_cost["silver"]
                profit_info["full_time"] = full_cost["total_time"]
                profit_info["full_cost"] = full_cost["total_cost"]
                profit_info["craft_steps"] = full_cost["craft_steps"]

                # Профит "с нуля" = цена продажи (после комиссии) - полная себестоимость
                profit_info["full_profit"] = profit_info["net_sell_price"] - full_cost["total_cost"]
                if full_cost["total_cost"] > 0:
                    profit_info["full_profit_percent"] = (profit_info["full_profit"] / full_cost["total_cost"]) * 100
                else:
                    profit_info["full_profit_percent"] = 0

                # Профит в час (золото/час при крафте с нуля)
                if full_cost["total_time"] > 0:
                    profit_info["profit_per_hour"] = (profit_info["full_profit"] / full_cost["total_time"]) * 3600
                else:
                    profit_info["profit_per_hour"] = 0

                # Добавляем расчёт "с покупкой компонентов"
                buy_info = self.calculate_buy_profit(recipe_id)
                if buy_info:
                    profit_info.update(buy_info)
                else:
                    # Дефолтные значения если нет данных
                    profit_info["buy_cost"] = 0
                    profit_info["buy_profit"] = 0
                    profit_info["buy_profit_percent"] = 0
                    profit_info["buy_time"] = 0
                    profit_info["buy_profit_per_hour"] = 0
                    profit_info["buy_components"] = ""
                    profit_info["buy_minerals"] = 0
                    profit_info["buy_sapphires"] = 0
                    profit_info["buy_rubies"] = 0
                    profit_info["buy_silver"] = 0

                profits.append(profit_info)

        # Сортируем по профиту в час (по убыванию)
        profits.sort(key=lambda x: x["profit_per_hour"], reverse=True)

        return profits

    def print_profit_report(self):
        """Выводит отчёт по профитности крафта"""
        if not self.prices:
            print("[PRICES] Сначала загрузите цены через get_all_craft_prices()")
            return

        profits = self.get_all_profits()

        print("\n" + "=" * 60)
        print("ОТЧЁТ ПО ПРОФИТНОСТИ КРАФТА")
        print("=" * 60)

        for info in profits:
            profit_sign = "+" if info["profit"] >= 0 else ""
            print(f"\n{info['name']} ({info['recipe_id']}):")
            print(f"  Цена продажи: {info['sell_price']:.2f}з")
            print(f"  Стоимость материалов: {info['cost']:.2f}з")
            print(f"  Профит: {profit_sign}{info['profit']:.2f}з ({profit_sign}{info['profit_percent']:.1f}%)")
            print(f"  Время крафта: {info['craft_time'] // 60} мин")

            if info["materials"]:
                print(f"  Материалы:")
                for mat_name, mat_cost in info["materials"].items():
                    print(f"    - {mat_name}: {mat_cost:.2f}з")

        print("\n" + "=" * 60)


def test_prices(client):
    """Тест получения цен с аукциона"""
    checker = CraftPriceChecker(client)

    # Тестируем поиск одного предмета
    price = checker.search_item("Минерал")
    print(f"Минерал: {price}з/шт")

    price = checker.search_item("Железная Руда")
    print(f"Железная Руда: {price}з/шт")


if __name__ == "__main__":
    from requests_bot.client import VMMOClient
    from requests_bot.config import load_settings, set_profile, get_credentials

    set_profile("char2")
    load_settings()

    client = VMMOClient()
    username, password = get_credentials()

    if client.login(username, password):
        test_prices(client)
