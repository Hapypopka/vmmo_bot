# ============================================
# VMMO Mining Craft Module
# ============================================
# Автоматический крафт материалов горного дела:
#
# Цепочка железа:
#   Железная Руда -> Железо -> Железный Слиток -> Аукцион
#
# Цепочка бронзы:
#   Медная Руда -> Медь
#   Железная Руда + Медь -> Бронза -> Аукцион
# ============================================

import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from requests_bot.config import BASE_URL

try:
    from requests_bot.logger import log_debug, log_info, log_warning
except ImportError:
    def log_debug(msg): print(f"[DEBUG] {msg}")
    def log_info(msg): print(f"[INFO] {msg}")
    def log_warning(msg): print(f"[WARN] {msg}")

# Уведомления в Telegram
def _notify_craft_issue(profile: str, recipe_name: str, reason: str):
    """Отправляет уведомление о проблеме с крафтом в Telegram"""
    try:
        from requests_bot.telegram_bot import notify_sync
        message = f"[{profile}] Крафт: {recipe_name}\n{reason}\nВозможно рецепт не изучен!"
        notify_sync(message)
    except Exception as e:
        print(f"[CRAFT] Не удалось отправить уведомление: {e}")

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


class IronCraftClient:
    """Клиент для управления крафтом железа"""

    def __init__(self, client, backpack_client=None, profile: str = "unknown"):
        """
        Args:
            client: VMMOClient instance
            backpack_client: BackpackClient instance (для продажи на аукционе)
            profile: имя профиля (для кэша цен аукциона)
        """
        self.client = client
        self.backpack_client = backpack_client
        self.profile = profile

        # Целевые количества для крафта (тестовый режим - по 1)
        self.target_ore = 1       # сколько руды накопить
        self.target_iron = 1      # сколько железа сделать
        self.target_bars = 1      # сколько слитков сделать

        # Счётчики сделанного
        self.crafted_ore = 0
        self.crafted_iron = 0
        self.crafted_bars = 0

    def set_targets(self, ore=35, iron=30, bars=5):
        """Устанавливает целевые количества для полного цикла"""
        self.target_ore = ore
        self.target_iron = iron
        self.target_bars = bars

    def reset_counters(self):
        """Сбрасывает счётчики"""
        self.crafted_ore = 0
        self.crafted_iron = 0
        self.crafted_bars = 0

    def get_mining_inventory(self):
        """
        Получает количество всех материалов горного дела в инвентаре.

        Returns:
            dict: {"rawOre": int, "iron": int, "ironBar": int, "copperOre": int, "copper": int, "bronze": int, "platinum": int}
        """
        from requests_bot.backpack import BackpackClient

        backpack = BackpackClient(self.client)

        inventory = {
            "rawOre": 0,
            "iron": 0,
            "ironBar": 0,
            "copperOre": 0,
            "copper": 0,
            "copperBar": 0,
            "bronze": 0,
            "bronzeBar": 0,
            "platinum": 0,
            "platinumBar": 0,
            "thor": 0,
            "thorBar": 0,
            "twilightSteel": 0,
            "twilightAnthracite": 0,
        }

        # Открываем рюкзак и считаем предметы
        if not backpack.open_backpack():
            print("[CRAFT] Не удалось открыть рюкзак")
            return inventory

        # Проходим по всем страницам рюкзака
        for page in range(1, 5):  # максимум 4 страницы
            items = backpack.get_items()

            for item in items:
                name = item["name"]
                count = item.get("count", 1)

                # Проверяем каждый тип
                for item_id, item_name in ITEM_NAMES.items():
                    if name == item_name:
                        inventory[item_id] += count
                        break

            # Переходим на следующую страницу
            if not backpack.go_to_next_page(page):
                break

        # Сохраняем инвентарь в кэш для веб-панели
        self._save_inventory_cache(inventory)

        return inventory

    def _save_inventory_cache(self, inventory):
        """Сохраняет инвентарь в файл для веб-панели"""
        import json
        import os
        import time

        try:
            # Путь к файлу кэша
            script_dir = os.path.dirname(os.path.abspath(__file__))
            profiles_dir = os.path.join(os.path.dirname(script_dir), "profiles")
            cache_file = os.path.join(profiles_dir, self.profile, "craft_inventory.json")

            # Создаём директорию если нет
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)

            # Сохраняем с временной меткой
            data = {
                "inventory": inventory,
                "timestamp": time.time()
            }

            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            print(f"[CRAFT] Ошибка сохранения кэша инвентаря: {e}")

    def get_iron_inventory(self):
        """Обратная совместимость - возвращает только железные материалы"""
        full_inv = self.get_mining_inventory()
        return {
            "rawOre": full_inv["rawOre"],
            "iron": full_inv["iron"],
            "ironBar": full_inv["ironBar"],
        }

    def get_craft_status(self):
        """
        Проверяет текущий статус крафта на главной странице.

        Returns:
            dict: {
                "in_progress": bool,
                "ready": bool,
                "type": str,  # rawOre, iron, ironBar, copperOre, copper, bronze
                "repeat_url": str,
                "collect_url": str,
            }
        """
        # Загружаем главную страницу где виден виджет крафта
        self.client.get(f"{BASE_URL}/city")
        soup = self.client.soup()

        result = {
            "in_progress": False,
            "ready": False,
            "type": None,
            "repeat_url": None,
            "collect_url": None,
        }

        if not soup:
            return result

        def detect_craft_type(text):
            """Определяет тип крафта по тексту"""
            # Порядок важен! Сначала более специфичные
            if "Медная Руда" in text:
                return "copperOre"
            if "Железная Руда" in text:
                return "rawOre"
            if "Железный Слиток" in text or "Слиток" in text:
                return "ironBar"
            if "Платина" in text:
                return "platinum"
            if "Бронза" in text:
                return "bronze"
            if "Медь" in text:
                return "copper"
            if "Железо" in text:
                return "iron"
            return None

        # Ищем блок профессии (info-box с крафтом)
        info_boxes = soup.select("div.info-box")
        for box in info_boxes:
            box_text = box.get_text()

            # Крафт готов - ищем "Готово" или кнопку "Забрать"
            if "Готово" in box_text:
                result["ready"] = True
                result["in_progress"] = False
                result["type"] = detect_craft_type(box_text)

                # Ищем кнопки
                buttons = box.select("a.go-btn")
                for btn in buttons:
                    href = btn.get("href", "")
                    btn_text = btn.get_text()
                    if "craftAgain" in href:
                        result["repeat_url"] = href
                    elif "getCraftResult" in href or "Забрать" in btn_text:
                        result["collect_url"] = href

                return result

            # Крафт в процессе
            elif any(x in box_text.lower() for x in ["в процессе", "осталось", "мин", "сек"]):
                # Проверяем что это именно крафт горного дела
                mining_keywords = ["Железная Руда", "Железо", "Слиток", "Горное дело",
                                   "Медная Руда", "Медь", "Бронза", "Платина"]
                if any(x in box_text for x in mining_keywords):
                    result["in_progress"] = True
                    result["ready"] = False
                    result["type"] = detect_craft_type(box_text)
                    return result

        return result

    def collect_craft(self):
        """
        Забирает готовый крафт.

        Returns:
            str or None: Тип того что забрали (rawOre, iron, ironBar)
        """
        status = self.get_craft_status()

        if not status["ready"]:
            print("[CRAFT] Крафт ещё не готов")
            return None

        collect_url = status.get("collect_url")
        if not collect_url:
            print("[CRAFT] Не найдена кнопка 'Забрать'")
            return None

        # Валидация URL - защита от "none" и других мусорных значений
        if collect_url.lower() in ("none", "null", ""):
            print(f"[CRAFT] Невалидный URL: {collect_url}")
            return None

        craft_type = status.get("type")
        print(f"[CRAFT] Забираю {RECIPES.get(craft_type, {}).get('name', craft_type)}...")

        if not collect_url.startswith("http"):
            collect_url = urljoin(BASE_URL, collect_url)

        self.client.get(collect_url)
        print("[CRAFT] Забрано!")

        # Очищаем сохранённое время завершения
        from requests_bot.config import clear_craft_finish_time
        clear_craft_finish_time()

        # Увеличиваем счётчик
        if craft_type == "rawOre":
            self.crafted_ore += 1
        elif craft_type == "iron":
            self.crafted_iron += 1
        elif craft_type == "ironBar":
            self.crafted_bars += 1

        return craft_type

    def repeat_craft(self):
        """
        Повторяет текущий крафт (кнопка "Повторить").

        Returns:
            bool: True если успешно
        """
        status = self.get_craft_status()

        if not status["ready"]:
            print("[CRAFT] Крафт не готов для повтора")
            return False

        repeat_url = status.get("repeat_url")
        if not repeat_url:
            print("[CRAFT] Не найдена кнопка 'Повторить'")
            return False

        # Валидация URL - защита от "none" и других мусорных значений
        if repeat_url.lower() in ("none", "null", ""):
            print(f"[CRAFT] Невалидный URL повтора: {repeat_url}")
            return False

        craft_type = status.get("type")
        print(f"[CRAFT] Повторяю {RECIPES.get(craft_type, {}).get('name', craft_type)}...")

        if not repeat_url.startswith("http"):
            repeat_url = urljoin(BASE_URL, repeat_url)

        self.client.get(repeat_url)
        print("[CRAFT] Крафт запущен!")
        return True

    def start_craft(self, recipe_id):
        """
        Начинает новый крафт указанного типа.
        Флоу для руды/железа: /profs/startwork/X -> "Начать работу"
        Флоу для слитка: /profs/prof/miningMaster?level=2 -> "Создать" -> "Начать работу"

        Args:
            recipe_id: "rawOre", "iron", или "ironBar"

        Returns:
            bool: True если успешно
        """
        if recipe_id not in RECIPES:
            print(f"[CRAFT] Неизвестный рецепт: {recipe_id}")
            return False

        recipe = RECIPES[recipe_id]
        print(f"[CRAFT] Начинаю крафт: {recipe['name']}...")

        # Особый путь для рецептов 2+ уровня (через страницу профессии)
        if recipe.get("level", 1) >= 2:
            return self._start_craft_level2(recipe)

        # Обычный путь для руды/железа
        url = f"{BASE_URL}{recipe['start_url']}"
        self.client.get(url)

        soup = self.client.soup()
        if not soup:
            print("[CRAFT] Не удалось загрузить страницу рецепта")
            return False

        # Ищем кнопку "Начать работу"
        start_btn = None

        for a in soup.select("a.go-btn"):
            href = a.get("href", "")
            if "acceptWorkActionPanel-link" in href:
                start_btn = a
                break

        if not start_btn:
            for a in soup.select("a.go-btn"):
                if "Начать работу" in a.get_text():
                    start_btn = a
                    break

        if not start_btn:
            print("[CRAFT] Не найдена кнопка 'Начать работу'")
            page_text = soup.get_text().lower()
            known_reason = False
            if "обновлен" in page_text and "сервер" in page_text:
                print("[CRAFT] Сервер на обновлении - ждём...")
                known_reason = True
            elif "недостаточно" in page_text or "не хватает" in page_text:
                print("[CRAFT] Не хватает материалов!")
                known_reason = True
            elif "вход" in page_text or "авторизац" in page_text:
                print("[CRAFT] Сессия истекла - нужна переавторизация!")
                known_reason = True

            if not known_reason:
                _notify_craft_issue(self.profile, recipe['name'], "Не найдена кнопка 'Начать работу'")
            return False

        start_url = start_btn.get("href")
        if not start_url:
            print("[CRAFT] Кнопка без ссылки")
            return False

        if not start_url.startswith("http"):
            start_url = urljoin(BASE_URL, start_url)

        self.client.get(start_url)
        print(f"[CRAFT] Крафт {recipe['name']} запущен!")

        # Сохраняем время завершения крафта
        import time
        from requests_bot.config import set_craft_finish_time
        craft_time = recipe.get("craft_time", 300)
        finish_time = int(time.time()) + craft_time
        set_craft_finish_time(finish_time)
        print(f"[CRAFT] Завершится через {craft_time}с (в {time.strftime('%H:%M:%S', time.localtime(finish_time))})")

        return True

    def _start_craft_level2(self, recipe):
        """Запускает крафт для рецептов 2-го уровня и выше"""
        # Шаг 1: Переходим на страницу профессии
        prof_url = f"{BASE_URL}{recipe['prof_page']}"
        self.client.get(prof_url)

        soup = self.client.soup()
        if not soup:
            print("[CRAFT] Не удалось загрузить страницу профессии")
            return False

        # Шаг 2: Ищем кнопку "Создать" для нужного рецепта
        # Может быть на нескольких страницах пагинации (pageIndexReceiptpage=N)
        receipt_id = recipe.get("receipt", "ironBar")
        create_btn = None
        found_on_page = 1

        # Проверяем кэш - может уже знаем на какой странице рецепт
        cached_page = _RECIPE_PAGE_CACHE.get(receipt_id)
        if cached_page and cached_page > 1:
            # Сразу идём на закэшированную страницу
            cached_url = f"{prof_url}&pageIndexReceiptpage={cached_page}"
            self.client.get(cached_url)
            soup = self.client.soup()
            if soup:
                for a in soup.select("a.go-btn"):
                    href = a.get("href", "")
                    if f"receipt={receipt_id}" in href and "CAP_craftReceipt" in href:
                        create_btn = a
                        found_on_page = cached_page
                        break

            # Если не нашли на кэшированной странице - сбрасываем кэш и ищем заново
            if not create_btn:
                del _RECIPE_PAGE_CACHE[receipt_id]
                # Перезагружаем первую страницу
                self.client.get(prof_url)
                soup = self.client.soup()

        # Если не нашли в кэше - ищем по всем страницам
        if not create_btn:
            max_pages = 5
            for page_num in range(1, max_pages + 1):
                # Ищем кнопку на текущей странице
                for a in soup.select("a.go-btn"):
                    href = a.get("href", "")
                    if f"receipt={receipt_id}" in href and "CAP_craftReceipt" in href:
                        create_btn = a
                        found_on_page = page_num
                        break

                if create_btn:
                    break

                # Ищем ссылки пагинации (a.page с номером страницы)
                next_page_url = None
                for a in soup.select("a.page"):
                    href = a.get("href", "")
                    text = a.get_text(strip=True)
                    # Ищем следующую страницу по номеру
                    if text.isdigit() and int(text) == page_num + 1:
                        next_page_url = href
                        break
                    # Или по параметру pageIndexReceiptpage
                    if f"pageIndexReceiptpage={page_num + 1}" in href:
                        next_page_url = href
                        break

                if not next_page_url:
                    break  # Нет больше страниц

                # Валидация URL пагинации
                if next_page_url.lower() in ("none", "null"):
                    break

                # Переходим на следующую страницу
                if not next_page_url.startswith("http"):
                    next_page_url = urljoin(BASE_URL, next_page_url)

                self.client.get(next_page_url)
                soup = self.client.soup()
                if not soup:
                    break

        # Сохраняем в кэш если нашли не на первой странице
        if create_btn and found_on_page > 1:
            _RECIPE_PAGE_CACHE[receipt_id] = found_on_page

        if not create_btn:
            recipe_name = ITEM_NAMES.get(receipt_id, receipt_id)
            print(f"[CRAFT] Не найдена кнопка 'Создать' для {receipt_id}")
            # Отладка: выводим все go-btn на странице
            all_btns = soup.select("a.go-btn")
            if all_btns:
                print(f"[CRAFT] DEBUG: Найдено {len(all_btns)} кнопок go-btn:")
                for btn in all_btns[:5]:
                    print(f"  - href: {btn.get('href', '')[:80]}")
            # Ищем навигацию/пагинацию
            nav_links = soup.select("a[href*='page'], a[href*='offset'], .pagination a, .pager a, .nav a")
            if nav_links:
                print(f"[CRAFT] DEBUG: Найдены nav links ({len(nav_links)}):")
                for link in nav_links[:5]:
                    print(f"  - {link.get('href', '')[:60]} | text: {link.get_text(strip=True)[:20]}")
            # Уведомление - скорее всего рецепт не изучен
            _notify_craft_issue(self.profile, recipe_name, "Не найдена кнопка 'Создать'")
            return False

        create_url = create_btn.get("href")

        # Валидация URL
        if not create_url or create_url.lower() in ("none", "null"):
            print(f"[CRAFT] Невалидный URL 'Создать': {create_url}")
            return False

        if not create_url.startswith("http"):
            create_url = urljoin(BASE_URL, create_url)

        # Шаг 3: Нажимаем "Создать" -> переход на страницу startwork
        self.client.get(create_url)

        soup = self.client.soup()
        if not soup:
            print("[CRAFT] Не удалось загрузить страницу крафта")
            return False

        # Шаг 4: Ищем кнопку "Начать работу"
        start_btn = None
        for a in soup.select("a.go-btn"):
            href = a.get("href", "")
            text = a.get_text()
            if "acceptWorkActionPanel-link" in href or "Начать работу" in text:
                start_btn = a
                break

        if not start_btn:
            print("[CRAFT] Не найдена кнопка 'Начать работу'")
            page_text = soup.get_text().lower()
            if "недостаточно" in page_text or "не хватает" in page_text:
                print("[CRAFT] Не хватает материалов для слитка!")
            else:
                # Неизвестная причина - уведомляем
                _notify_craft_issue(self.profile, recipe['name'], "Не найдена кнопка 'Начать работу' (level 2+)")
            return False

        start_url = start_btn.get("href")

        # Валидация URL - защита от "none" и других мусорных значений
        if not start_url or start_url.lower() in ("none", "null"):
            print(f"[CRAFT] Невалидный URL 'Начать работу': {start_url}")
            return False

        if not start_url.startswith("http"):
            start_url = urljoin(BASE_URL, start_url)

        self.client.get(start_url)
        print(f"[CRAFT] Крафт {recipe['name']} запущен!")

        # Сохраняем время завершения крафта
        import time
        from requests_bot.config import set_craft_finish_time
        craft_time = recipe.get("craft_time", 300)
        finish_time = int(time.time()) + craft_time
        set_craft_finish_time(finish_time)
        print(f"[CRAFT] Завершится через {craft_time}с (в {time.strftime('%H:%M:%S', time.localtime(finish_time))})")

        return True

    def get_next_craft_type(self, check_inventory=False):
        """
        Определяет какой крафт делать следующим.

        Args:
            check_inventory: Если True - проверяет реальный инвентарь.
                            Если False - использует внутренние счётчики (быстрее).

        Returns:
            str or None: recipe_id или None если цикл завершён
        """
        if check_inventory:
            # Проверяем реальный инвентарь
            inv = self.get_iron_inventory()

            # Нужно: target_ore руды, из них target_iron уйдёт на железо
            # Логика: сколько нужно ещё скрафтить?
            # Для руды: нужно target_ore штук (7 для теста)
            # Для железа: нужно target_iron штук (6 для теста)
            # Для слитков: нужно target_bars штук (1 для теста)

            if inv["rawOre"] < self.target_ore:
                return "rawOre"
            if inv["iron"] < self.target_iron:
                return "iron"
            if inv["ironBar"] < self.target_bars:
                return "ironBar"
            return None
        else:
            # Используем внутренние счётчики (быстрее)
            if self.crafted_ore < self.target_ore:
                return "rawOre"
            if self.crafted_iron < self.target_iron:
                return "iron"
            if self.crafted_bars < self.target_bars:
                return "ironBar"
            return None

    def _get_wait_time(self):
        """Возвращает время ожидания в зависимости от текущего крафта"""
        next_type = self.get_next_craft_type()
        if next_type and next_type in RECIPES:
            return RECIPES[next_type].get("craft_time", 200)
        return 200  # дефолт 3+ мин

    def run_cycle(self):
        """
        Выполняет один шаг цикла крафта.

        Returns:
            str: "crafting", "waiting", "done", "error"
        """
        print(f"[CRAFT] === Цикл крафта (руда:{self.crafted_ore}/{self.target_ore}, "
              f"железо:{self.crafted_iron}/{self.target_iron}, "
              f"слитки:{self.crafted_bars}/{self.target_bars}) ===")

        status = self.get_craft_status()

        # Крафт в процессе - ждём
        if status["in_progress"] and not status["ready"]:
            return "waiting"

        # Крафт готов
        if status["ready"]:
            current_type = status["type"]
            next_type = self.get_next_craft_type()

            print(f"[CRAFT] Готов: {current_type}, следующий: {next_type}")

            # Если нужен тот же тип - повторяем
            if current_type == next_type:
                # Сначала забираем чтобы увеличить счётчик
                self.collect_craft()
                # Проверяем нужно ли ещё
                next_type = self.get_next_craft_type()
                if next_type == current_type:
                    # Начинаем новый крафт того же типа
                    self.start_craft(next_type)
                    return "crafting"
                elif next_type:
                    # Переходим к другому типу
                    self.start_craft(next_type)
                    return "crafting"
                else:
                    # Цикл завершён
                    return "done"
            else:
                # Нужен другой тип - забираем и начинаем новый
                self.collect_craft()
                if next_type:
                    self.start_craft(next_type)
                    return "crafting"
                else:
                    return "done"

        # Нет активного крафта - начинаем
        next_type = self.get_next_craft_type()
        if next_type:
            print(f"[CRAFT] Нет активного крафта, начинаем: {next_type}")
            if self.start_craft(next_type):
                return "crafting"
            else:
                return "error"
        else:
            return "done"

    def run_full_cycle(self):
        """
        Запускает полный цикл крафта до завершения.
        После завершения продаёт всё на аукционе.

        Returns:
            bool: True если успешно
        """
        print("=" * 50)
        print(f"[CRAFT] Полный цикл: {self.target_ore} руды -> "
              f"{self.target_iron} железа -> {self.target_bars} слитков")
        print("=" * 50)

        self.reset_counters()

        max_iterations = 1000  # защита от бесконечного цикла
        iteration = 0

        errors_in_row = 0

        while iteration < max_iterations:
            iteration += 1

            try:
                result = self.run_cycle()
                errors_in_row = 0  # сбрасываем счётчик ошибок
            except Exception as e:
                errors_in_row += 1
                print(f"[CRAFT] Ошибка соединения ({errors_in_row}/3): {e}")
                if errors_in_row >= 3:
                    print("[CRAFT] Слишком много ошибок подряд!")
                    return False
                time.sleep(10)
                continue

            if result == "done":
                print("[CRAFT] Цикл крафта завершён!")
                self.sell_all_iron()
                return True

            elif result == "error":
                print("[CRAFT] Ошибка крафта!")
                return False

            elif result == "waiting":
                # Ждём пока крафт завершится - используем время из рецепта
                wait_time = self._get_wait_time()
                print(f"[CRAFT] Ожидание {wait_time} сек...")
                time.sleep(wait_time)

            elif result == "crafting":
                # Крафт запущен, ждём
                wait_time = self._get_wait_time()
                print(f"[CRAFT] Крафт запущен, ждём {wait_time} сек...")
                time.sleep(wait_time)

        print("[CRAFT] Превышен лимит итераций!")
        return False

    def sell_all_mining(self, mode="all"):
        """
        Продаёт материалы горного дела на аукционе.

        Args:
            mode: "iron" - только железо/слитки
                  "bronze" - только медь/бронза
                  "platinum" - только жел.руда/платина
                  "all" - всё

        Использует AuctionClient для автоматического ценообразования.
        """
        print(f"[CRAFT] Продаю материалы на аукционе (режим: {mode})...")

        try:
            from requests_bot.auction import AuctionClient
            from requests_bot.backpack import BackpackClient

            backpack = BackpackClient(self.client)
            auction = AuctionClient(self.client, profile=self.profile)

            # Выбираем предметы в зависимости от режима
            # Каждый режим включает ВСЮ цепочку материалов (сырьё + промежуточные + финальные)
            if mode == "iron":
                sell_items = [
                    ITEM_NAMES["rawOre"],   # "Железная Руда"
                    ITEM_NAMES["iron"],     # "Железо"
                    ITEM_NAMES["ironBar"],  # "Железный Слиток"
                ]
            elif mode == "bronze":
                sell_items = [
                    ITEM_NAMES["copperOre"],  # "Медная Руда"
                    ITEM_NAMES["rawOre"],     # "Железная Руда"
                    ITEM_NAMES["copper"],     # "Медь"
                    ITEM_NAMES["bronze"],     # "Бронза"
                    ITEM_NAMES["bronzeBar"],  # "Бронзовый Слиток"
                ]
            elif mode == "platinum":
                sell_items = [
                    ITEM_NAMES["rawOre"],      # "Железная Руда"
                    ITEM_NAMES["platinum"],    # "Платина"
                    ITEM_NAMES["platinumBar"], # "Платиновый Слиток"
                ]
            elif mode == "copper":
                sell_items = [
                    ITEM_NAMES["copperOre"],  # "Медная Руда"
                    ITEM_NAMES["copper"],     # "Медь"
                    ITEM_NAMES["copperBar"],  # "Медный Слиток"
                ]
            elif mode == "copperBar":
                sell_items = [
                    ITEM_NAMES["copperOre"],  # "Медная Руда"
                    ITEM_NAMES["copper"],     # "Медь"
                    ITEM_NAMES["copperBar"],  # "Медный Слиток"
                ]
            elif mode == "thor":
                sell_items = [
                    ITEM_NAMES["rawOre"],   # "Железная Руда"
                    ITEM_NAMES["iron"],     # "Железо"
                    ITEM_NAMES["thor"],     # "Тор"
                    ITEM_NAMES["thorBar"],  # "Слиток Тора"
                ]
            elif mode == "twilight":
                sell_items = [
                    ITEM_NAMES["rawOre"],            # "Железная Руда"
                    ITEM_NAMES["iron"],              # "Железо"
                    ITEM_NAMES["ironBar"],           # "Железный Слиток"
                    ITEM_NAMES["thor"],              # "Тор"
                    ITEM_NAMES["thorBar"],           # "Слиток Тора"
                    ITEM_NAMES["platinum"],          # "Платина"
                    ITEM_NAMES["twilightSteel"],     # "Сумеречная Сталь"
                    ITEM_NAMES["twilightAnthracite"],# "Сумеречный Антрацит"
                ]
            else:  # all
                sell_items = list(ITEM_NAMES.values())

            sold_count = 0
            skipped_items = set()  # Предметы с низкой ценой - пропускаем

            # Минимальное количество для продажи
            # Берём из batch_size автокрафта, если не указано явно
            from requests_bot.config import get_setting, get_craft_items
            min_stack_config = get_setting("min_auction_stack", {})
            craft_items = get_craft_items()

            # Формируем маппинг item_id -> batch_size из автокрафта
            batch_sizes = {}
            for craft_item in craft_items:
                item_id = craft_item.get("item")
                batch_size = craft_item.get("batch_size", 5)
                batch_sizes[item_id] = batch_size

            # Минимальные размеры стаков для ВСЕХ крафтовых предметов
            # Приоритет: min_auction_stack из UI > batch_size из автокрафта > get_optimal_batch_size
            from requests_bot.craft_prices import get_optimal_batch_size

            MIN_STACK_SIZES = {}
            for item_id, item_name in ITEM_NAMES.items():
                # Сначала проверяем UI настройку min_auction_stack
                ui_setting = min_stack_config.get(item_id, 0)
                if ui_setting > 0:
                    MIN_STACK_SIZES[item_name] = ui_setting
                # Потом batch_size из автокрафта
                elif item_id in batch_sizes:
                    MIN_STACK_SIZES[item_name] = batch_sizes[item_id]
                # Используем get_optimal_batch_size как дефолт (учитывает время крафта)
                else:
                    MIN_STACK_SIZES[item_name] = get_optimal_batch_size(item_id)

            # Проходим пока есть предметы с кнопкой аукциона
            for _ in range(50):  # защита от бесконечного цикла
                if not backpack.open_backpack():
                    print("[CRAFT] Не удалось открыть рюкзак!")
                    break

                items = backpack.get_items()

                # DEBUG: показываем что видим в рюкзаке
                craft_items_found = [i for i in items if i["name"] in sell_items]
                if craft_items_found:
                    for ci in craft_items_found:
                        has_auction = "auction" in ci["buttons"]
                        min_stack = MIN_STACK_SIZES.get(ci["name"], 1)
                        print(f"[CRAFT-DEBUG] {ci['name']} x{ci['count']}, auction={has_auction}, min_stack={min_stack}, buttons={list(ci['buttons'].keys())}")

                # Ищем предмет с кнопкой аукциона (кроме пропущенных)
                target = None
                for item in items:
                    if item["name"] in sell_items and "auction" in item["buttons"]:
                        if item["name"] not in skipped_items:
                            # Проверяем минимальное количество для слитков
                            min_stack = MIN_STACK_SIZES.get(item["name"], 1)
                            item_count = item.get("count", 1)
                            if item_count >= min_stack:
                                target = item
                                break

                if not target:
                    # Проверяем следующие страницы
                    found_on_next = False
                    for page in range(2, 5):
                        if not backpack.go_to_next_page(page - 1):
                            break
                        items = backpack.get_items()
                        for item in items:
                            if item["name"] in sell_items and "auction" in item["buttons"]:
                                if item["name"] not in skipped_items:
                                    target = item
                                    found_on_next = True
                                    break
                        if found_on_next:
                            break

                if not target:
                    break

                name = target["name"]
                auction_url = target["buttons"]["auction"]

                print(f"[CRAFT] Выставляю на аукцион: {name}")

                # Переходим на страницу аукциона
                self.client.get(auction_url)
                time.sleep(0.5)

                # Получаем количество
                my_count = auction.get_my_item_count()

                # Пытаемся получить цену из кэша
                from requests_bot.craft_prices import get_cached_price
                cached_price = get_cached_price(name)

                if cached_price:
                    # Есть кэш - ставим цену на 1 серебро ниже ЗА ЕДИНИЦУ
                    # cached_price в золоте за 1 шт (например 0.39)
                    # Вычитаем 0.01 (1 серебро)
                    price_per_unit = max(0.01, cached_price - 0.01)

                    # Умножаем на количество для стопки
                    final_price = price_per_unit * my_count
                    gold = int(final_price)
                    silver = int((final_price - gold) * 100)
                    print(f"[CRAFT] Цена из кэша: {cached_price:.2f}з/шт → продаём {my_count} шт за {final_price:.2f}з ({gold}з {silver}с)")
                else:
                    # Нет кэша - используем старую логику
                    gold, silver = auction.calculate_price(my_count, item_name=name)

                    # Неизвестный предмет без конкурентов - не продаём
                    if gold is None:
                        print(f"[CRAFT] Нет конкурентов и нет дефолтной цены для '{name}', пропускаю")
                        skipped_items.add(name)
                        continue

                print(f"[CRAFT] x{my_count} за {gold}з {silver}с")

                # Создаём лот
                result = auction.try_create_lot(gold, silver)

                if result == "success":
                    print(f"[CRAFT] Выставлено!")
                    sold_count += 1
                elif result == "low_price":
                    print(f"[CRAFT] Цена слишком низкая, пропускаю '{name}'")
                    skipped_items.add(name)  # Больше не пытаемся продать этот тип
                else:
                    print(f"[CRAFT] Ошибка выставления")

                time.sleep(0.5)

            print(f"[CRAFT] Продажа завершена! Выставлено лотов: {sold_count}")
            return sold_count

        except Exception as e:
            print(f"[CRAFT] Ошибка продажи: {e}")
            return 0

    def sell_all_iron(self):
        """Обратная совместимость - продаёт только железные материалы"""
        return self.sell_all_mining(mode="iron")

    def run_smart_cycle(self):
        """
        Умный цикл крафта с проверкой инвентаря.

        В отличие от run_full_cycle(), этот метод:
        1. Проверяет инвентарь перед КАЖДЫМ крафтом
        2. Не спамит "повторить" - решает что делать дальше
        3. Продаёт когда все цели достигнуты

        Returns:
            bool: True если успешно
        """
        print("=" * 50)
        print(f"[CRAFT] Умный цикл: руда>={self.target_ore}, железо>={self.target_iron}, слитки>={self.target_bars}")
        print("=" * 50)

        max_iterations = 200  # защита от бесконечного цикла
        errors_in_row = 0

        for iteration in range(max_iterations):
            try:
                # Проверяем инвентарь и определяем что делать
                next_type = self.get_next_craft_type(check_inventory=True)

                if next_type is None:
                    print("[CRAFT] Все цели достигнуты!")
                    self.sell_all_iron()
                    return True

                # Проверяем статус текущего крафта
                status = self.get_craft_status()

                # Крафт в процессе - ждём
                if status["in_progress"] and not status["ready"]:
                    wait_time = RECIPES.get(status.get("type", "rawOre"), {}).get("craft_time", 200)
                    print(f"[CRAFT] Ждём завершения крафта {wait_time} сек...")
                    time.sleep(wait_time)
                    continue

                # Крафт готов - забираем и смотрим что дальше
                if status["ready"]:
                    self.collect_craft()

                    # Снова проверяем инвентарь
                    next_type = self.get_next_craft_type(check_inventory=True)
                    if next_type is None:
                        print("[CRAFT] Все цели достигнуты!")
                        self.sell_all_iron()
                        return True

                # Запускаем нужный крафт
                if not self.start_craft(next_type):
                    print(f"[CRAFT] Ошибка запуска крафта {next_type}")
                    errors_in_row += 1
                    if errors_in_row >= 3:
                        print("[CRAFT] Слишком много ошибок!")
                        return False
                    time.sleep(10)
                    continue

                errors_in_row = 0

                # Ждём завершения крафта
                wait_time = RECIPES[next_type]["craft_time"]
                print(f"[CRAFT] Крафт запущен, ждём {wait_time} сек...")
                time.sleep(wait_time)

            except Exception as e:
                errors_in_row += 1
                print(f"[CRAFT] Ошибка ({errors_in_row}/3): {e}")
                if errors_in_row >= 3:
                    return False
                time.sleep(10)

        print("[CRAFT] Превышен лимит итераций!")
        return False


class CyclicCraftClient(IronCraftClient):
    """
    Клиент для бесконечного цикла крафта.

    Работает со списком предметов из config.json:
    "craft_items": [
        {"item": "copper", "batch_size": 5},
        {"item": "iron", "batch_size": 10}
    ]

    Логика:
    1. Проверяет инвентарь - если накоплено >= batch_size → продаёт
    2. Проверяет статус крафта - если готов → забирает
    3. Если крафт не идёт → запускает новый крафт
    4. Цикл бесконечный - никогда не завершается
    """

    def __init__(self, client, backpack_client=None, profile: str = "unknown"):
        super().__init__(client, backpack_client, profile=profile)
        self._leftovers_checked = False  # Флаг проверки остатков при старте
        self._selected_recipe = None  # Рецепт выбирается ОДИН РАЗ при старте

    def _check_inventory_leftovers(self):
        """
        Проверяет есть ли в инвентаре остатки от предыдущего крафта.
        Если да - возвращает recipe_id для докрафтивания.

        Returns:
            tuple: (recipe_id, current_count, batch_size) или (None, 0, 0)
        """
        try:
            from requests_bot.craft_prices import load_craft_locks, get_optimal_batch_size

            locks = load_craft_locks()
            if self.profile not in locks:
                return None, 0, 0

            lock_info = locks[self.profile]
            current_recipe = lock_info.get("recipe_id")
            if not current_recipe:
                return None, 0, 0

            # Проверяем сколько уже есть в инвентаре
            inv = self.get_mining_inventory()
            current_count = inv.get(current_recipe, 0)

            if current_count > 0:
                batch_size = get_optimal_batch_size(current_recipe)
                item_name = ITEM_NAMES.get(current_recipe, current_recipe)
                print(f"[CRAFT] Найдены остатки от прошлой сессии: {item_name} x{current_count}/{batch_size}")
                return current_recipe, current_count, batch_size

            return None, 0, 0

        except Exception as e:
            print(f"[CRAFT] Ошибка проверки остатков: {e}")
            return None, 0, 0

    def do_cyclic_craft_step(self):
        """
        Выполняет один шаг бесконечного цикла крафта.

        Логика:
        0. При первом запуске проверяет остатки от прошлой сессии
        1. Проверяет инвентарь - если накоплено >= batch_size → продаёт
        2. Проверяет статус крафта - если готов → забирает
        3. Если крафт в процессе → ждёт
        4. Если крафт не идёт → определяет самый выгодный крафт из кэша цен
           и запускает его

        Returns:
            tuple: (is_active: bool, wait_seconds: int)
                   is_active=True если крафт активен
                   wait_seconds - сколько ждать до следующей проверки
        """
        from requests_bot.config import get_craft_items, get_setting

        items = get_craft_items()
        if not items:
            print("[CRAFT] Список автокрафта пуст")
            return False, 0

        # 0. При первом вызове - проверяем остатки от предыдущей сессии
        if not self._leftovers_checked:
            self._leftovers_checked = True
            leftover_recipe, leftover_count, leftover_batch = self._check_inventory_leftovers()

            if leftover_recipe and leftover_count > 0:
                item_name = ITEM_NAMES.get(leftover_recipe, leftover_recipe)

                if leftover_count >= leftover_batch:
                    # Достаточно - продаём сразу
                    print(f"[CRAFT] Остатки готовы к продаже: {item_name} x{leftover_count}")
                    self._sell_item_batch(leftover_recipe)
                    return True, 5
                else:
                    # Нужно докрафтить до batch_size
                    print(f"[CRAFT] Докрафтиваю остатки: {item_name} {leftover_count}/{leftover_batch}")
                    # Продолжаем с этим же рецептом (лок уже есть)

        # 1. Определяем лучший крафт и его оптимальный batch_size
        best_item_id = self._get_best_craft_item()

        # Получаем оптимальный batch_size на основе времени крафта
        try:
            from requests_bot.craft_prices import get_optimal_batch_size
            batch_size = get_optimal_batch_size(best_item_id)
        except Exception:
            batch_size = 5  # fallback

        # 2. Проверка инвентаря выбранного предмета
        inventory = self.get_mining_inventory()
        current_count = inventory.get(best_item_id, 0)
        item_name = ITEM_NAMES.get(best_item_id, best_item_id)

        # Сохраняем прогресс для веб-панели
        try:
            from requests_bot.craft_prices import update_craft_progress
            update_craft_progress(self.profile, best_item_id, current_count, batch_size)
        except Exception:
            pass

        if current_count >= batch_size:
            # Продать накопленное
            print(f"[CRAFT] Накоплено {item_name}: {current_count}/{batch_size} → продаю")
            self._sell_item_batch(best_item_id)
            return True, 5  # Проверить снова через 5 сек

        # 3. Проверка статуса крафта
        status = self.get_craft_status()

        if status["ready"]:
            # Забрать готовый крафт
            collected_type = self.collect_craft()
            if collected_type:
                item_name = ITEM_NAMES.get(collected_type, collected_type)
                print(f"[CRAFT] Забрано: {item_name}")
                # Очищаем время завершения крафта после забора
                from requests_bot.config import clear_craft_finish_time
                clear_craft_finish_time()
            # НЕ возвращаемся - идём дальше запускать новый крафт

        elif status["in_progress"]:
            # Ждать завершения
            craft_type = status.get("type")

            # Проверяем каждые 30 секунд вместо полного времени крафта
            # Это позволяет быстрее забрать готовый крафт
            return True, 30

        # 4. Запустить новый крафт
        # Определяем самый выгодный крафт из кэша цен (или используем fallback)
        item_id = self._get_best_craft_item()
        recipe = self._get_recipe_for_item(item_id)

        if recipe and self.start_craft(recipe):
            wait_time = RECIPES[recipe]["craft_time"]
            item_name = ITEM_NAMES.get(item_id, item_id)
            print(f"[CRAFT] Запуск крафта: {item_name} (рецепт: {recipe}, время: {wait_time}с)")
            return True, wait_time
        else:
            print(f"[CRAFT] Ошибка запуска крафта для {item_id}")
            return False, 60  # Повтор через минуту

    def _get_best_craft_item(self):
        """
        Определяет лучший предмет для крафта с учётом распределения между ботами.

        ВАЖНО: Рецепт выбирается ОДИН РАЗ при старте и кэшируется на всю сессию!
        Это убирает постоянные пересчёты квот и файловые операции.

        Returns:
            str: item_id для крафта
        """
        # Если рецепт уже выбран - возвращаем его без пересчётов
        if self._selected_recipe:
            return self._selected_recipe

        from requests_bot.config import get_craft_items, get_setting

        # Проверяем включён ли автовыбор
        auto_select = get_setting("auto_select_craft", True)

        if not auto_select:
            # Автовыбор отключён - используем первый из списка
            items = get_craft_items()
            if items:
                self._selected_recipe = items[0]["item"]
                item_name = ITEM_NAMES.get(self._selected_recipe, self._selected_recipe)
                print(f"[CRAFT] Выбран рецепт (ручной): {item_name}")
                return self._selected_recipe
            self._selected_recipe = "ironBar"
            return self._selected_recipe

        try:
            from requests_bot.craft_prices import (
                is_cache_expired, refresh_craft_prices_cache, acquire_craft_lock
            )

            # Обновляем кэш ТОЛЬКО при первом выборе
            if is_cache_expired():
                print("[CRAFT] Кэш цен устарел, обновляю...")
                refresh_craft_prices_cache(self.client)

            # Берём лок на рецепт (с учётом распределения)
            best_item = acquire_craft_lock(self.profile)

            if best_item:
                self._selected_recipe = best_item
                item_name = ITEM_NAMES.get(best_item, best_item)
                print(f"[CRAFT] Выбран рецепт (авто): {item_name} - крафтим всю сессию")
                return self._selected_recipe

        except Exception as e:
            print(f"[CRAFT] Ошибка автовыбора: {e}")
            import traceback
            traceback.print_exc()

        # Fallback - первый из списка конфига
        items = get_craft_items()
        if items:
            self._selected_recipe = items[0]["item"]
            item_name = ITEM_NAMES.get(self._selected_recipe, self._selected_recipe)
            print(f"[CRAFT] Fallback: {item_name} (первый из списка)")
            return self._selected_recipe

        self._selected_recipe = "ironBar"
        return self._selected_recipe

    def _sell_item_batch(self, item_id):
        """
        Продаёт все предметы указанного типа на аукционе.
        После продажи обновляет timestamp лока.

        Args:
            item_id: ID предмета для продажи
        """
        item_name = ITEM_NAMES.get(item_id, item_id)
        print(f"[CRAFT] Продажа накопленного: {item_name}")

        # Определяем режим продажи по цепочке крафта
        if item_id in ["copper", "copperOre", "copperBar"]:
            self.sell_all_mining(mode="copper")
        elif item_id in ["iron", "rawOre", "ironBar"]:
            self.sell_all_mining(mode="iron")
        elif item_id in ["bronze", "bronzeBar"]:
            self.sell_all_mining(mode="bronze")
        elif item_id in ["platinum", "platinumBar"]:
            self.sell_all_mining(mode="platinum")
        elif item_id in ["thor", "thorBar"]:
            self.sell_all_mining(mode="thor")
        elif item_id in ["twilightSteel", "twilightAnthracite"]:
            self.sell_all_mining(mode="twilight")
        else:
            self.sell_all_mining(mode="all")

        # Обновляем лок после продажи партии
        try:
            from requests_bot.craft_prices import refresh_craft_lock
            refresh_craft_lock(self.profile, item_id)
        except Exception as e:
            print(f"[CRAFT] Ошибка обновления лока: {e}")

        print(f"[CRAFT] Продажа завершена")

    def _get_recipe_for_item(self, item_id):
        """
        Возвращает recipe_id для крафта указанного предмета.

        Для некоторых предметов нужна цепочка:
        - iron: нужна rawOre сначала
        - ironBar: нужно iron сначала
        - copper: нужна copperOre сначала
        - bronze: нужны rawOre + copper
        - platinum: нужна rawOre

        Args:
            item_id: ID предмета для крафта

        Returns:
            str: recipe_id для запуска крафта
        """
        # Проверяем инвентарь
        inv = self.get_mining_inventory()

        if item_id == "iron":
            # Для железа нужна руда
            if inv["rawOre"] >= 2:
                return "iron"
            else:
                return "rawOre"

        elif item_id == "ironBar":
            # Для слитка нужно железо (7 штук)
            if inv["iron"] >= 7:
                return "ironBar"
            elif inv["rawOre"] >= 2:
                return "iron"
            else:
                return "rawOre"

        elif item_id == "copper":
            # Для меди нужна медная руда
            if inv["copperOre"] >= 2:
                return "copper"
            else:
                return "copperOre"

        elif item_id == "bronze":
            # Для бронзы нужны 3 жел.руды + 2 меди
            if inv["rawOre"] >= 3 and inv["copper"] >= 2:
                return "bronze"
            elif inv["copper"] < 2:
                if inv["copperOre"] >= 2:
                    return "copper"
                else:
                    return "copperOre"
            else:
                return "rawOre"

        elif item_id == "platinum":
            # Для платины нужны 25 жел.руды
            if inv["rawOre"] >= 25:
                return "platinum"
            else:
                return "rawOre"

        elif item_id == "copperBar":
            # Для медного слитка нужно 10 меди
            if inv["copper"] >= 10:
                return "copperBar"
            elif inv["copperOre"] >= 2:
                return "copper"
            else:
                return "copperOre"

        elif item_id == "bronzeBar":
            # Для бронзового слитка нужно 5 бронзы
            if inv["bronze"] >= 5:
                return "bronzeBar"
            elif inv["rawOre"] >= 3 and inv["copper"] >= 2:
                return "bronze"
            elif inv["copper"] < 2:
                if inv["copperOre"] >= 2:
                    return "copper"
                else:
                    return "copperOre"
            else:
                return "rawOre"

        elif item_id == "platinumBar":
            # Для платинового слитка нужно 5 платины
            if inv["platinum"] >= 5:
                return "platinumBar"
            elif inv["rawOre"] >= 25:
                return "platinum"
            else:
                return "rawOre"

        elif item_id == "thor":
            # Для тора нужно 5 жел.руды + 3 железа
            if inv["rawOre"] >= 5 and inv["iron"] >= 3:
                return "thor"
            elif inv["iron"] < 3:
                if inv["rawOre"] >= 2:
                    return "iron"
                else:
                    return "rawOre"
            else:
                return "rawOre"

        elif item_id == "thorBar":
            # Для слитка тора нужно 5 тора
            if inv["thor"] >= 5:
                return "thorBar"
            elif inv["rawOre"] >= 5 and inv["iron"] >= 3:
                return "thor"
            elif inv["iron"] < 3:
                if inv["rawOre"] >= 2:
                    return "iron"
                else:
                    return "rawOre"
            else:
                return "rawOre"

        elif item_id == "twilightSteel":
            # Для сумеречной стали нужно 3 жел.слитка + 2 тора + 5 платины
            if inv["ironBar"] >= 3 and inv["thor"] >= 2 and inv["platinum"] >= 5:
                return "twilightSteel"
            elif inv["platinum"] < 5:
                if inv["rawOre"] >= 25:
                    return "platinum"
                else:
                    return "rawOre"
            elif inv["thor"] < 2:
                if inv["rawOre"] >= 5 and inv["iron"] >= 3:
                    return "thor"
                elif inv["iron"] < 3:
                    if inv["rawOre"] >= 2:
                        return "iron"
                    else:
                        return "rawOre"
                else:
                    return "rawOre"
            elif inv["ironBar"] < 3:
                if inv["iron"] >= 7:
                    return "ironBar"
                elif inv["rawOre"] >= 2:
                    return "iron"
                else:
                    return "rawOre"

        elif item_id == "twilightAnthracite":
            # Для сумеречного антрацита нужно 3 жел.слитка + 2 слитка тора + 5 платины
            if inv["ironBar"] >= 3 and inv["thorBar"] >= 2 and inv["platinum"] >= 5:
                return "twilightAnthracite"
            elif inv["platinum"] < 5:
                if inv["rawOre"] >= 25:
                    return "platinum"
                else:
                    return "rawOre"
            elif inv["thorBar"] < 2:
                if inv["thor"] >= 5:
                    return "thorBar"
                elif inv["rawOre"] >= 5 and inv["iron"] >= 3:
                    return "thor"
                elif inv["iron"] < 3:
                    if inv["rawOre"] >= 2:
                        return "iron"
                    else:
                        return "rawOre"
                else:
                    return "rawOre"
            elif inv["ironBar"] < 3:
                if inv["iron"] >= 7:
                    return "ironBar"
                elif inv["rawOre"] >= 2:
                    return "iron"
                else:
                    return "rawOre"

        # Неизвестный предмет - пробуем напрямую
        if item_id in RECIPES:
            return item_id

        return None


def test_iron_craft(client):
    """Тест модуля крафта железа - полный цикл"""
    print("=" * 50)
    print("VMMO Iron Craft Test (Smart Cycle)")
    print("=" * 50)

    craft = IronCraftClient(client)

    # Тестовый режим: накопить минимум 7 руды, 6 железа, 1 слиток
    # После достижения целей - продать всё на аукционе
    craft.set_targets(ore=7, iron=6, bars=1)

    # Проверяем текущий инвентарь
    inv = craft.get_iron_inventory()
    print(f"Текущий инвентарь: руда={inv['rawOre']}, железо={inv['iron']}, слитки={inv['ironBar']}")

    # Проверяем статус крафта
    status = craft.get_craft_status()
    print(f"Craft status: {status}")

    # Запускаем умный цикл
    result = craft.run_smart_cycle()
    print(f"Smart cycle result: {result}")


if __name__ == "__main__":
    from requests_bot.client import VMMOClient
    from requests_bot.config import load_settings, set_profile, get_credentials

    set_profile("char2")
    load_settings()

    client = VMMOClient()
    username, password = get_credentials()

    if client.login(username, password):
        test_iron_craft(client)
