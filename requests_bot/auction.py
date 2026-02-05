# ============================================
# VMMO Auction Module (requests version)
# ============================================
# Выставление предметов на аукцион
# ============================================

import re
import time
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .backpack import (
    BackpackClient,
    is_protected_item,
    load_auction_blacklist,
    add_to_auction_blacklist,
)
from .config import get_craft_items
from .sales_tracker import record_listed

BASE_URL = "https://vmmo.vten.ru"

# Минимальная цена по умолчанию (в серебре)
DEFAULT_MIN_PRICE = 5

# Дефолтные цены за штуку когда нет конкурентов (в серебре)
DEFAULT_PRICES = {
    # Железная цепочка
    "Железный Слиток": 200,  # 2 золота
    "Железо": 40,            # 40 серебра
    "Железная Руда": 10,     # 10 серебра
    # Медная/бронзовая цепочка
    "Бронзовый Слиток": 250, # 2.5 золота
    "Бронза": 150,           # 1.5 золота
    "Медный Слиток": 100,    # 1 золото
    "Медь": 30,              # 30 серебра
    "Медная Руда": 10,       # 10 серебра
    # Платиновая цепочка
    "Платиновый Слиток": 500,  # 5 золота
    "Платина": 300,          # 3 золота
    # Торовая цепочка
    "Слиток Тора": 800,      # 8 золота
    "Тор": 500,              # 5 золота
}

# Минимальные стаки для продажи (предметы, которые не крафтовые но продаём только пачками)
# Ключ - начало названия предмета, значение - минимальный стак
STACK_SELL_RULES = {
    "Осколок": 10,
    "Руна": 10,
}

# Маппинг item_id из крафта → название предмета
CRAFT_ITEM_NAMES = {
    "ironBar": "Железный Слиток",
    "iron": "Железо",
    "rawOre": "Железная Руда",
    "bronzeBar": "Бронзовый Слиток",
    "bronze": "Бронза",
    "copperBar": "Медный Слиток",
    "copper": "Медь",
    "copperOre": "Медная Руда",
    "platinumBar": "Платиновый Слиток",
    "platinum": "Платина",
    "thorBar": "Слиток Тора",
    "thor": "Тор",
}

# ============================================
# Кэш цен аукциона (чтобы боты не перебивали друг друга)
# ============================================

PRICE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "profiles", "auction_price_cache.json")
PRICE_CACHE_TTL = 24 * 60 * 60  # 24 часа в секундах


def load_price_cache() -> dict:
    """Загружает кэш цен из файла"""
    try:
        if os.path.exists(PRICE_CACHE_FILE):
            with open(PRICE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[AUCTION] Ошибка чтения кэша цен: {e}")
    return {}


def save_price_cache(cache: dict):
    """Сохраняет кэш цен в файл"""
    try:
        os.makedirs(os.path.dirname(PRICE_CACHE_FILE), exist_ok=True)
        with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[AUCTION] Ошибка записи кэша цен: {e}")


def get_cached_price(item_name: str) -> int | None:
    """
    Получает цену из кэша если она свежая.

    Returns:
        int: цена за единицу в серебре, или None если кэш устарел/отсутствует
    """
    cache = load_price_cache()

    if item_name not in cache:
        return None

    entry = cache[item_name]
    age = time.time() - entry.get("timestamp", 0)

    if age > PRICE_CACHE_TTL:
        print(f"[AUCTION] Кэш для '{item_name}' устарел ({age/3600:.1f}ч)")
        return None

    price = entry.get("price_per_unit", 0)
    profile = entry.get("profile", "?")
    hours_ago = age / 3600
    print(f"[AUCTION] Цена из кэша: {item_name} = {price}с/шт ({profile}, {hours_ago:.1f}ч назад)")

    return price


def set_cached_price(item_name: str, price_per_unit: int, profile: str = "unknown"):
    """Записывает цену в кэш"""
    cache = load_price_cache()

    cache[item_name] = {
        "price_per_unit": price_per_unit,
        "timestamp": time.time(),
        "profile": profile
    }

    save_price_cache(cache)
    print(f"[AUCTION] Кэш обновлён: {item_name} = {price_per_unit}с/шт")


def get_batch_size_for_item(item_name):
    """
    Получает batch_size для предмета из конфига крафта или правил стаков.

    Returns:
        int: batch_size или 1 если не найден (продавать сразу)
    """
    # Проверяем правила стаков (Осколки и т.д.)
    for prefix, min_stack in STACK_SELL_RULES.items():
        if item_name.startswith(prefix):
            return min_stack

    craft_items = get_craft_items()

    # Ищем item_id по названию
    item_id = None
    for craft_id, craft_name in CRAFT_ITEM_NAMES.items():
        if craft_name == item_name:
            item_id = craft_id
            break

    if not item_id:
        return 1  # Не крафтовый предмет - продаём сразу

    # Ищем batch_size в конфиге
    for craft_item in craft_items:
        if craft_item.get("item") == item_id:
            return craft_item.get("batch_size", 1)

    return 1  # Не в очереди крафта - продаём сразу


def is_blacklist_exempt(item_name):
    """Проверяет, защищён ли предмет от попадания в чёрный список (крафт, осколки)"""
    # Осколки и другие стаковые предметы
    for prefix in STACK_SELL_RULES:
        if item_name.startswith(prefix):
            return True
    # Крафтовые предметы
    if item_name in CRAFT_ITEM_NAMES.values():
        return True
    return False


class AuctionClient:
    """Клиент для работы с аукционом"""

    def __init__(self, client, profile: str = "unknown"):
        """
        Args:
            client: VMMOClient instance
            profile: имя профиля (для кэша цен)
        """
        self.client = client
        self.profile = profile
        self.backpack = BackpackClient(client)
        self.items_listed = 0
        self.items_disassembled = 0

    def get_my_item_count(self):
        """
        Получает количество нашего товара на странице аукциона.

        Returns:
            int: Количество
        """
        soup = self.client.soup()
        if not soup:
            return 1

        # Ищем наш предмет
        my_item = soup.select_one("div.panel-inner-2")
        if not my_item:
            return 1

        # Ищем количество
        count_span = my_item.select_one("span.e-count")
        if count_span:
            text = count_span.get_text(strip=True)
            match = re.search(r'[xх](\d+)', text, re.IGNORECASE)
            if match:
                return int(match.group(1))

        # Fallback: ищем количество в тексте всего блока
        full_text = my_item.get_text()
        match = re.search(r'[xх](\d+)', full_text, re.IGNORECASE)
        if match:
            return int(match.group(1))

        return 1

    def get_competitor_min_price(self):
        """
        Получает минимальную цену конкурента.

        Returns:
            tuple: (gold, silver, count) или (0, 0, 0) если конкурентов нет
        """
        soup = self.client.soup()
        if not soup:
            return 0, 0, 0

        # Ищем лоты конкурентов (у которых есть кнопка-ссылка "выкупить")
        # Наш собственный лот имеет span.go-btn (не кликабельный), а конкуренты - a.go-btn
        all_lots = soup.select("div.list-el")
        competitor = None
        for lot in all_lots:
            # Проверяем есть ли кнопка-ссылка (a, не span)
            buy_btn = lot.select_one("a.go-btn._auction")
            if buy_btn:
                competitor = lot
                break

        if not competitor:
            return 0, 0, 0

        # Получаем количество в лоте
        count = 1
        count_span = competitor.select_one("span.e-count")
        if count_span:
            text = count_span.get_text(strip=True)
            match = re.search(r'[xх](\d+)', text, re.IGNORECASE)
            if match:
                count = int(match.group(1))

        # Получаем цену выкупа
        buy_btn = competitor.select_one("a.go-btn._auction")

        gold = 0
        silver = 0

        # Парсим HTML кнопки для извлечения цены
        btn_html = str(buy_btn)

        # Ищем золото - число перед иконкой золота или после
        gold_icon = buy_btn.select_one("span.i12-money_gold")
        silver_icon = buy_btn.select_one("span.i12-money_silver")

        # Парсим текст кнопки
        btn_text = buy_btn.get_text()
        numbers = re.findall(r'\d+', btn_text)

        if gold_icon and silver_icon and len(numbers) >= 2:
            gold = int(numbers[0])
            silver = int(numbers[1])
        elif gold_icon and len(numbers) >= 1:
            gold = int(numbers[0])
        elif silver_icon and len(numbers) >= 1:
            silver = int(numbers[0])

        return gold, silver, count

    def calculate_price(self, my_count, item_name=None):
        """
        Рассчитывает цену для нашего лота.
        Сначала проверяет кэш (чтобы боты не перебивали друг друга).

        Args:
            my_count: Количество нашего товара
            item_name: Название предмета (для дефолтной цены и кэша)

        Returns:
            tuple: (gold, silver)
        """
        # DISABLED: Кэш отключён - всегда проверяем актуальную цену на рынке
        # Причина: с кэшем ничего не продаётся, конкуренты перебивают
        # if item_name:
        #     cached_price = get_cached_price(item_name)
        #     if cached_price is not None:
        #         our_total = cached_price * my_count
        #         gold = our_total // 100
        #         silver = our_total % 100
        #         return gold, silver

        # Смотрим конкурентов на рынке
        comp_gold, comp_silver, comp_count = self.get_competitor_min_price()

        if comp_count == 0 or (comp_gold == 0 and comp_silver == 0):
            # Конкурентов нет - используем дефолтную цену
            if item_name and item_name in DEFAULT_PRICES:
                price_per_unit = DEFAULT_PRICES[item_name]
                our_total = price_per_unit * my_count
                gold = our_total // 100
                silver = our_total % 100
                print(f"[AUCTION] Нет конкурентов, дефолтная цена: {price_per_unit}с/шт")
                # Кэш отключён
                return gold, silver
            else:
                # Неизвестный предмет - не продаём
                return None, None

        # Цена за единицу в серебре
        total_silver = comp_gold * 100 + comp_silver
        price_per_unit = total_silver // comp_count

        # Наша цена (на 1 серебро дешевле конкурента)
        our_price_per_unit = price_per_unit - 1
        if our_price_per_unit < 1:
            our_price_per_unit = 1

        our_total = our_price_per_unit * my_count
        if our_total < DEFAULT_MIN_PRICE:
            our_total = DEFAULT_MIN_PRICE
            our_price_per_unit = max(1, our_total // my_count)

        gold = our_total // 100
        silver = our_total % 100

        # Кэш отключён - каждый бот сам проверяет рынок

        return gold, silver

    def try_create_lot(self, gold, silver):
        """
        Пытается создать лот на аукционе.

        Args:
            gold: Золото
            silver: Серебро

        Returns:
            str: "success", "low_price", или "error"
        """
        soup = self.client.soup()
        if not soup:
            return "error"

        # Находим форму
        form = soup.find("form")
        if not form:
            print("[AUCTION] Форма не найдена")
            return "error"

        # Собираем данные формы
        form_data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

        # Устанавливаем цены (одинаковые для bid и buyout)
        form_data["bidGold"] = str(gold)
        form_data["bidSilver"] = str(silver)
        form_data["buyoutGold"] = str(gold)
        form_data["buyoutSilver"] = str(silver)

        # Получаем action формы
        action = form.get("action", "")
        if not action:
            print("[AUCTION] Action формы не найден")
            return "error"

        action_url = urljoin(self.client.current_url, action)

        # Отправляем форму
        self.client.post(action_url, data=form_data)

        # Проверяем результат
        soup = self.client.soup()
        if not soup:
            return "error"

        # Проверяем ошибку низкой цены
        error = soup.select_one("span.feedbackPanelERROR")
        if error:
            text = error.get_text()
            if "ниже рыночной" in text.lower() or "низкая" in text.lower():
                return "low_price"
            print(f"[AUCTION] Ошибка: {text}")
            return "error"

        return "success"

    def sell_all(self):
        """
        Выставляет все подходящие предметы на аукцион.
        Логика как в Playwright версии.

        Returns:
            dict: Статистика {listed, disassembled, errors}
        """
        stats = {
            "listed": 0,
            "disassembled": 0,
            "errors": 0,
        }

        items_to_disassemble = []  # Названия предметов для разборки
        blacklist = load_auction_blacklist()

        for iteration in range(100):  # Защита от бесконечного цикла
            # Открываем рюкзак
            if not self.backpack.open_backpack():
                print("[AUCTION] Не удалось открыть рюкзак")
                break

            items = self.backpack.get_items()

            # Ищем предмет с кнопкой аукциона
            target = None
            for item in items:
                name = item["name"]

                # Пропускаем защищённые
                if item["is_protected"]:
                    continue

                # Пропускаем из списка для разборки
                if name in items_to_disassemble:
                    continue

                # Предметы из blacklist - разбираем, если не можем - выкидываем
                if name in blacklist:
                    print(f"[AUCTION] '{name}' в чёрном списке - разбираем")
                    if self.backpack.disassemble_item(item):
                        stats["disassembled"] += 1
                    elif "drop" in item["buttons"]:
                        print(f"[AUCTION] '{name}' нельзя разобрать - выкидываем")
                        if self.backpack.drop_item(item):
                            stats["disassembled"] += 1
                    continue

                # Нужна кнопка аукциона
                if "auction" not in item["buttons"]:
                    continue

                # Проверяем batch_size для крафтовых предметов
                batch_size = get_batch_size_for_item(name)
                item_count = item.get("count", 1)
                if item_count < batch_size:
                    # Не набралась партия - пропускаем
                    continue

                target = item
                break

            if not target:
                # Больше нет предметов для аукциона
                break

            name = target["name"]
            is_green = target["is_green"]
            difficulty = target.get("difficulty")  # None, "normal", "heroic", "brutal"

            # Предметы со сложностью normal/heroic - разбираем (только brutal продаём)
            if difficulty and difficulty != "brutal" and "disassemble" in target["buttons"]:
                print(f"[AUCTION] '{name}' сложность {difficulty} (не brutal) - разбираем")
                if self.backpack.disassemble_item(target):
                    stats["disassembled"] += 1
                continue

            # Зелёные предметы с кнопкой разборки - разбираем
            # Зелёные БЕЗ кнопки разборки - выставляем на аукцион
            if is_green and "disassemble" in target["buttons"]:
                print(f"[AUCTION] '{name}' зелёный с разборкой - разбираем")
                if self.backpack.disassemble_item(target):
                    stats["disassembled"] += 1
                continue

            # Переходим на страницу аукциона
            print(f"[AUCTION] Выставляю: {name}")
            auction_url = target["buttons"]["auction"]
            self.client.get(auction_url)
            time.sleep(0.5)

            # Получаем наше количество
            my_count = self.get_my_item_count()

            # Рассчитываем цену
            comp_gold, comp_silver, comp_count = self.get_competitor_min_price()

            # Рассчитываем цену (с учётом дефолтных цен для железа)
            gold, silver = self.calculate_price(my_count, item_name=name)

            if gold is None:
                if is_blacklist_exempt(name):
                    # Крафт/осколки - не блеклистим, пропускаем
                    print(f"[AUCTION] Нет конкурентов для '{name}' - пропускаем (exempt)")
                    continue
                # Неизвестный предмет без конкурентов - разбираем и добавляем в blacklist
                print(f"[AUCTION] Нет конкурентов для '{name}' - разбираем, добавляю в blacklist")
                add_to_auction_blacklist(name)
                items_to_disassemble.append(name)
                continue

            if comp_gold > 0 or comp_silver > 0:
                print(f"[AUCTION] Конкурент: {comp_gold}g {comp_silver}s за x{comp_count}")
            print(f"[AUCTION] Наш товар: x{my_count} -> ставим {gold}g {silver}s")

            # Создаём лот
            result = self.try_create_lot(gold, silver)

            if result == "success":
                print(f"[AUCTION] Лот создан!")
                stats["listed"] += 1
                # Записываем в статистику продаж
                record_listed(name, my_count, gold, silver, profile=self.profile)
                time.sleep(0.5)

            elif result == "low_price":
                if is_blacklist_exempt(name):
                    print(f"[AUCTION] Цена слишком низкая для '{name}' - пропускаем (exempt)")
                else:
                    print(f"[AUCTION] Цена слишком низкая - '{name}' для разборки, добавляю в blacklist")
                    add_to_auction_blacklist(name)
                    items_to_disassemble.append(name)

            else:
                print(f"[AUCTION] Ошибка при создании лота")
                stats["errors"] += 1

        # Разбираем предметы с низкой ценой
        if items_to_disassemble:
            print(f"[AUCTION] Разбираю {len(items_to_disassemble)} предметов с низкой ценой...")
            self.backpack.open_backpack()

            for name in items_to_disassemble:
                items = self.backpack.get_items()
                for item in items:
                    if item["name"] == name:
                        if "disassemble" in item["buttons"]:
                            if self.backpack.disassemble_item(item):
                                stats["disassembled"] += 1
                        elif "drop" in item["buttons"]:
                            if self.backpack.drop_item(item):
                                stats["disassembled"] += 1
                        break

        self.items_listed = stats["listed"]
        self.items_disassembled = stats["disassembled"]

        print(f"[AUCTION] Готово: выставлено {stats['listed']}, разобрано {stats['disassembled']}")
        return stats


def test_auction(client):
    """Тест модуля аукциона"""
    print("=" * 50)
    print("VMMO Auction Test")
    print("=" * 50)

    auction = AuctionClient(client)

    # Открываем рюкзак
    print("\n[*] Открываю рюкзак...")
    if auction.backpack.open_backpack():
        items = auction.backpack.get_items()

        # Ищем предметы с аукционом
        auction_items = [i for i in items if "auction" in i["buttons"] and not i["is_protected"]]
        print(f"[*] Предметов для аукциона: {len(auction_items)}")

        for item in auction_items[:5]:
            status = "зелёный" if item["is_green"] else "обычный"
            print(f"  - {item['name']} x{item['count']} ({status})")
    else:
        print("[ERR] Не удалось открыть рюкзак")


if __name__ == "__main__":
    from .client import VMMOClient

    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            exit(1)

    test_auction(client)
