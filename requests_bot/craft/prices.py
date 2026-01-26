# ============================================
# VMMO Craft Price Cache
# ============================================
# Кэш цен аукциона для крафта
# ============================================

import os
import sys
import time
import json

from requests_bot.config import CRAFT_CACHE_TTL

# Путь к общему кэшу цен (доступен всем персонажам)
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHARED_CACHE_FILE = os.path.join(SCRIPT_DIR, "shared_auction_cache.json")
CACHE_UPDATE_LOCKFILE = os.path.join(SCRIPT_DIR, "shared_cache_update.lock")

# Алиас для обратной совместимости
CACHE_TTL = CRAFT_CACHE_TTL

# Комиссия аукциона (5%)
AUCTION_FEE = 0.05


def load_shared_cache():
    """
    Загружает общий кэш цен из файла.

    Returns:
        dict: {"prices": {item_name: price}, "timestamp": int} или None
    """
    if not os.path.exists(SHARED_CACHE_FILE):
        return None

    try:
        with open(SHARED_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

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


# Категории аукциона для разных типов предметов
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
