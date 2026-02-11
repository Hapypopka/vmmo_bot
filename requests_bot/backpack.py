# ============================================
# VMMO Backpack Module (requests version)
# ============================================
# Управление рюкзаком: просмотр, разборка, выброс
# ============================================

import re
import json
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from requests_bot.config import (
    BASE_URL, AUCTION_BLACKLIST_FILE, BACKPACK_THRESHOLD, get_protected_items
)

# Чёрный список аукциона - вечный (без TTL)

try:
    from requests_bot.logger import log_debug, log_info, log_warning, log_backpack
except ImportError:
    # Fallback если запускается напрямую
    def log_debug(msg): print(f"[DEBUG] {msg}")
    def log_info(msg): print(f"[INFO] {msg}")
    def log_warning(msg): print(f"[WARN] {msg}")
    def log_backpack(msg): print(f"[BACKPACK] {msg}")


def is_protected_item(item_name):
    """Проверяет, защищён ли предмет от продажи/разборки (динамически загружает список)"""
    protected_items = get_protected_items()
    for protected in protected_items:
        if protected.lower() in item_name.lower():
            return True
    return False


def load_auction_blacklist():
    """
    Загружает чёрный список аукциона.
    Формат: {"item_name": timestamp, ...}
    Чёрный список вечный - предметы не удаляются автоматически.
    """
    try:
        with open(AUCTION_BLACKLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    # Миграция: если старый формат (список), конвертируем
    if isinstance(data, list):
        now = time.time()
        new_data = {item: now for item in data}
        save_auction_blacklist_raw(new_data)
        return list(new_data.keys())

    return list(data.keys())


def save_auction_blacklist_raw(data):
    """Сохраняет чёрный список аукциона (raw dict)"""
    with open(AUCTION_BLACKLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_auction_blacklist(blacklist):
    """Сохраняет чёрный список аукциона (для совместимости)"""
    # Загружаем текущие данные чтобы сохранить timestamps
    try:
        with open(AUCTION_BLACKLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                data = {}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    # Обновляем только новые записи
    now = time.time()
    for item in blacklist:
        if item not in data:
            data[item] = now

    save_auction_blacklist_raw(data)


def add_to_auction_blacklist(item_name):
    """Добавляет предмет в чёрный список аукциона с timestamp"""
    try:
        with open(AUCTION_BLACKLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                # Миграция старого формата
                data = {item: time.time() for item in data}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    if item_name not in data:
        data[item_name] = time.time()
        save_auction_blacklist_raw(data)
        print(f"[BLACKLIST] Добавлен: {item_name} (TTL: 24ч)")


class BackpackClient:
    """Клиент для работы с рюкзаком"""

    def __init__(self, client):
        """
        Args:
            client: VMMOClient instance
        """
        self.client = client
        self.items_disassembled = 0
        self.items_dropped = 0
        self.bonuses_opened = 0

    def get_backpack_count(self):
        """
        Получает текущее количество предметов в рюкзаке.

        Returns:
            tuple: (current, total) или (0, 28) при ошибке
        """
        soup = self.client.soup()
        if not soup:
            return 0, 28

        # Ищем счетчик в меню
        rack_link = soup.select_one("a.main-menu-link._rack .link-text")
        if rack_link:
            text = rack_link.get_text(strip=True)
            match = re.match(r'(\d+)/(\d+)', text)
            if match:
                return int(match.group(1)), int(match.group(2))

        # Альтернативный селектор
        counter = soup.select_one("span.sp_rack_count")
        if counter:
            text = counter.get_text(strip=True)
            match = re.match(r'(\d+)/(\d+)', text)
            if match:
                return int(match.group(1)), int(match.group(2))

        return 0, 28

    def need_cleanup(self):
        """Проверяет, нужна ли очистка рюкзака"""
        current, total = self.get_backpack_count()
        return current >= BACKPACK_THRESHOLD

    def is_full(self):
        """Проверяет, полон ли рюкзак"""
        current, total = self.get_backpack_count()
        return current >= total

    def open_backpack(self):
        """Открывает рюкзак"""
        # Сначала загружаем страницу с меню
        self.client.get("/city")
        soup = self.client.soup()

        # Ищем ссылку на рюкзак
        rack_link = soup.select_one("a.main-menu-link._rack")
        if rack_link:
            href = rack_link.get("href")
            if href:
                self.client.get(urljoin(BASE_URL, href))
                return True

        # Альтернативный путь - прямой URL
        self.client.get("/rack")
        return "rack" in self.client.current_url.lower()

    def get_items(self):
        """
        Получает список предметов в рюкзаке.

        Returns:
            list: Список словарей с информацией о предметах
        """
        soup = self.client.soup()
        if not soup:
            return []

        items = []

        # Пробуем разные селекторы для предметов
        item_divs = soup.select("div.p10")
        if not item_divs:
            # Альтернативный селектор
            item_divs = soup.select("div.item-block")
        if not item_divs:
            item_divs = soup.select("div.rack-item")

        log_debug(f"[BACKPACK] Найдено item_divs: {len(item_divs)}")

        # Если ничего не нашли - диагностика
        if not item_divs:
            log_debug(f"[BACKPACK] Предметы не найдены! URL: {self.client.current_url}")
            # Ищем любые кнопки a.go-btn для диагностики
            all_buttons = soup.select("a.go-btn")
            log_debug(f"[BACKPACK] Всего a.go-btn на странице: {len(all_buttons)}")
            for btn in all_buttons[:5]:
                log_debug(f"[BACKPACK] Кнопка: {btn.get_text(strip=True)[:30]}")
        else:
            # Показываем структуру первого item_div для диагностики
            first_div = item_divs[0]
            first_btns = first_div.select("a.go-btn")
            log_debug(f"[BACKPACK] Первый item_div имеет {len(first_btns)} кнопок a.go-btn")
            for btn in first_btns:
                log_debug(f"[BACKPACK] - btn: '{btn.get_text(strip=True)}' href={btn.get('href', 'NO_HREF')[:50] if btn.get('href') else 'NO_HREF'}")

        for item_div in item_divs:
            # Название предмета
            name_link = item_div.select_one("span.e-name a")
            if not name_link:
                continue

            name = name_link.get_text(strip=True)
            classes = name_link.get("class", [])

            # Количество
            count = 1
            count_span = item_div.select_one("span.e-count")
            if count_span:
                text = count_span.get_text(strip=True)
                # Формат: " x2" или "x10" (русская или латинская x)
                match = re.search(r'[xх](\d+)', text, re.IGNORECASE)
                if match:
                    count = int(match.group(1))

            # Качество (зелёный = iGood, легендарный = iLegendary)
            is_green = "iGood" in classes
            is_legendary = "iLegendary" in classes

            # Сложность предмета (normal/hard/impossible) - из иконки
            # <img src="/images/icons/item_impossible.png"> = brutal
            # <img src="/images/icons/item_hard.png"> = heroic
            # <img src="/images/icons/item_normal.png"> = normal
            # Иконка может быть внутри ссылки или в item_div
            difficulty = None
            difficulty_img = item_div.select_one("img[src*='item_impossible'], img[src*='item_hard'], img[src*='item_normal']")
            if difficulty_img:
                src = difficulty_img.get("src", "")
                if "item_impossible" in src:
                    difficulty = "brutal"
                elif "item_hard" in src:
                    difficulty = "heroic"
                elif "item_normal" in src:
                    difficulty = "normal"

            # Кнопки действий
            buttons = {}
            all_btn_texts = []  # DEBUG
            for btn in item_div.select("a.go-btn"):
                btn_text = btn.get_text(strip=True)
                all_btn_texts.append(btn_text)  # DEBUG
                href = btn.get("href")
                if href:
                    full_url = urljoin(self.client.current_url, href)
                    if "аукцион" in btn_text.lower():
                        buttons["auction"] = full_url
                    elif "разобрать" in btn_text.lower():
                        buttons["disassemble"] = full_url
                    elif "выкинуть" in btn_text.lower():
                        buttons["drop"] = full_url
                    elif "открыть" in btn_text.lower():
                        buttons["open"] = full_url

            # DEBUG: если нет кнопок, показываем что было
            if not buttons and all_btn_texts:
                log_debug(f"[BACKPACK] '{name[:20]}' btns raw: {all_btn_texts}")

            # DEBUG: логируем сложность для предметов с аукционом
            if difficulty and "auction" in buttons:
                log_debug(f"[BACKPACK] '{name[:25]}' difficulty={difficulty}")

            items.append({
                "name": name,
                "count": count,
                "is_green": is_green,
                "is_legendary": is_legendary,
                "is_protected": is_protected_item(name) or is_legendary,  # Легендарные = защищены
                "difficulty": difficulty,  # None, "normal", "heroic", "brutal"
                "buttons": buttons,
            })

        return items

    def disassemble_item(self, item):
        """
        Разбирает предмет.

        Args:
            item: Словарь с информацией о предмете

        Returns:
            bool: Успешно ли
        """
        if "disassemble" not in item["buttons"]:
            return False

        url = item["buttons"]["disassemble"]
        self.client.get(url)

        # Ищем кнопку подтверждения "Да, точно"
        soup = self.client.soup()
        confirm_url = None

        # Ищем ссылку с текстом "Да, точно"
        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if "да" in text.lower() and "точно" in text.lower():
                href = btn.get("href")
                if href:
                    confirm_url = href if href.startswith("http") else urljoin(self.client.current_url, href)
                    break

        if confirm_url:
            self.client.get(confirm_url)
            log_backpack(f"Разобрано: {item['name']}")
            self.items_disassembled += 1
            return True

        log_warning(f"[BACKPACK] Кнопка подтверждения не найдена для: {item['name']}")
        return False

    def drop_item(self, item):
        """
        Выбрасывает предмет.

        Args:
            item: Словарь с информацией о предмете

        Returns:
            bool: Успешно ли
        """
        if "drop" not in item["buttons"]:
            return False

        url = item["buttons"]["drop"]
        self.client.get(url)

        # Ищем кнопку подтверждения "Да, точно"
        soup = self.client.soup()
        confirm_url = None

        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if "да" in text.lower() and "точно" in text.lower():
                href = btn.get("href")
                if href:
                    confirm_url = href if href.startswith("http") else urljoin(self.client.current_url, href)
                    break

        if confirm_url:
            self.client.get(confirm_url)
            log_backpack(f"Выброшено: {item['name']}")
            self.items_dropped += 1
            return True

        log_warning(f"[BACKPACK] Кнопка подтверждения не найдена для выброса: {item['name']}")
        return False

    def open_bonus(self, item):
        """
        Открывает бонусный предмет.

        Args:
            item: Словарь с информацией о предмете

        Returns:
            bool: Успешно ли
        """
        if "open" not in item["buttons"]:
            return False

        url = item["buttons"]["open"]
        self.client.get(url)
        self.bonuses_opened += 1
        return True

    def open_all_bonuses(self):
        """Открывает все бонусы и сундуки в рюкзаке"""
        if not self.open_backpack():
            return 0

        # Ключевые слова для открываемых предметов
        openable_keywords = ["бонус", "сундук", "ларец", "ящик", "шкатулка"]

        opened = 0
        for _ in range(50):  # Защита от бесконечного цикла
            items = self.get_items()
            # Ищем предметы с кнопкой "open" и подходящим названием
            openable_items = []
            for item in items:
                if "open" not in item["buttons"]:
                    continue
                name_lower = item["name"].lower()
                if any(kw in name_lower for kw in openable_keywords):
                    openable_items.append(item)

            if not openable_items:
                break

            item = openable_items[0]
            log_backpack(f"Открываю: {item['name']}")
            if self.open_bonus(item):
                opened += 1
            else:
                break

        return opened

    def disassemble_all(self, skip_green=True, skip_open=False):
        """
        Разбирает все предметы с кнопкой разборки.

        Args:
            skip_green: Пропускать зелёные предметы
            skip_open: Не открывать рюкзак (уже на нужной странице)

        Returns:
            int: Количество разобранных
        """
        if not skip_open:
            if not self.open_backpack():
                return 0

        disassembled = 0
        blacklist = load_auction_blacklist()

        for _ in range(100):  # Защита
            items = self.get_items()
            log_debug(f"[BACKPACK] Предметов на странице: {len(items)}")

            # DEBUG: показываем ВСЕ предметы
            for i, item in enumerate(items):
                btns = list(item["buttons"].keys())
                flags = []
                if item["is_protected"]:
                    flags.append("PROTECTED")
                if item["is_green"]:
                    flags.append("GREEN")
                if item["is_legendary"]:
                    flags.append("LEGENDARY")
                log_debug(f"[BACKPACK] [{i}] {item['name'][:30]} | btns={btns} | {','.join(flags)}")

            # Ищем предмет для разборки
            target = None
            for item in items:
                if item["is_protected"]:
                    continue
                if skip_green and item["is_green"]:
                    continue
                if "disassemble" not in item["buttons"]:
                    continue
                target = item
                break

            if not target:
                log_debug("[BACKPACK] Не найден предмет для разборки!")
                break

            log_backpack(f"Разбираю: {target['name']}")
            if self.disassemble_item(target):
                disassembled += 1
            else:
                break

        return disassembled

    def drop_green_unusable(self):
        """
        Выбрасывает зелёные предметы без кнопок аукциона/разборки.

        Returns:
            int: Количество выброшенных
        """
        if not self.open_backpack():
            return 0

        dropped = 0

        for _ in range(50):
            items = self.get_items()

            # Ищем зелёный предмет без полезных кнопок
            target = None
            for item in items:
                if item["is_protected"]:
                    continue
                if not item["is_green"]:
                    continue
                if "auction" in item["buttons"] or "disassemble" in item["buttons"]:
                    continue
                if "drop" not in item["buttons"]:
                    continue
                target = item
                break

            if not target:
                break

            log_backpack(f"Выбрасываю: {target['name']}")
            if self.drop_item(target):
                dropped += 1
            else:
                break

        return dropped

    def drop_unusable(self, skip_open=False):
        """
        Выбрасывает ВСЕ предметы (не только зелёные) без кнопок аукциона/разборки.
        Например: Изумительная пылинка, Золотой Оберег и т.п.

        Args:
            skip_open: Не открывать рюкзак (уже на нужной странице)

        Returns:
            int: Количество выброшенных
        """
        if not skip_open:
            if not self.open_backpack():
                return 0

        dropped = 0

        for _ in range(50):
            items = self.get_items()

            # Ищем любой предмет без полезных кнопок
            target = None
            for item in items:
                if item["is_protected"]:
                    continue
                # Пропускаем если есть полезные кнопки
                if "auction" in item["buttons"] or "disassemble" in item["buttons"]:
                    continue
                if "drop" not in item["buttons"]:
                    continue
                target = item
                break

            if not target:
                break

            log_backpack(f"Выбрасываю (мусор): {target['name']}")
            if self.drop_item(target):
                dropped += 1
            else:
                break

        return dropped

    def go_to_next_page(self, current_page=1):
        """
        Переходит на следующую страницу рюкзака.

        Args:
            current_page: Текущая страница

        Returns:
            bool: Успешно ли
        """
        soup = self.client.soup()
        if not soup:
            return False

        next_page = current_page + 1
        for link in soup.select("a.page"):
            title = link.get("title", "")
            if f"страницу {next_page}" in title:
                href = link.get("href")
                if href:
                    self.client.get(urljoin(self.client.current_url, href))
                    return True

        return False

    def cleanup(self, max_pages=3, profile: str = "unknown"):
        """
        Полная очистка рюкзака.

        1. Открывает бонусы
        2. Выставляет на аукцион (через AuctionClient)
        3. Разбирает предметы
        4. Выбрасывает зелёные без пользы

        Args:
            max_pages: Максимум страниц для обработки
            profile: имя профиля (для кэша цен аукциона)

        Returns:
            dict: Статистика {bonuses, disassembled, dropped, auctioned}
        """
        stats = {
            "bonuses": 0,
            "disassembled": 0,
            "dropped": 0,
            "auctioned": 0,
        }

        log_backpack("Начинаю очистку рюкзака...")

        # 1. Сначала открываем бонусы на всех страницах
        for page in range(1, max_pages + 1):
            if page > 1:
                if not self.go_to_next_page(page - 1):
                    break
                log_debug(f"[BACKPACK] Страница {page} (бонусы)")

            opened = self.open_all_bonuses()
            stats["bonuses"] += opened

        # 2. Выставляем на аукцион (аукцион сам обрабатывает все страницы)
        try:
            from requests_bot.auction import AuctionClient
            auction = AuctionClient(self.client, profile=profile)
            auction_stats = auction.sell_all()
            stats["auctioned"] = auction_stats.get("listed", 0)
            stats["disassembled"] += auction_stats.get("disassembled", 0)
        except Exception as e:
            log_warning(f"[BACKPACK] Ошибка аукциона: {e}")

        # 3. Разбираем оставшееся и выбрасываем мусор
        for page in range(1, max_pages + 1):
            if not self.open_backpack():
                break
            if page > 1:
                if not self.go_to_next_page(page - 1):
                    break
                log_debug(f"[BACKPACK] Страница {page} (разборка)")

            # Разбираем (включая зелёные) — skip_open чтобы не сбрасывать страницу
            disassembled = self.disassemble_all(skip_green=False, skip_open=True)
            stats["disassembled"] += disassembled

            # Выбрасываем ВСЕ бесполезные предметы (не только зелёные)
            dropped = self.drop_unusable(skip_open=True)
            stats["dropped"] += dropped

        log_backpack(f"Очистка завершена: бонусов {stats['bonuses']}, аукцион {stats['auctioned']}, разобрано {stats['disassembled']}, выброшено {stats['dropped']}")
        return stats

    def cleanup_if_needed(self, max_pages=3):
        """
        Очищает рюкзак если нужно (превышен порог).

        Returns:
            dict or None: Статистика или None если очистка не нужна
        """
        # Загружаем страницу для получения счетчика
        self.client.get("/city")

        if not self.need_cleanup():
            current, total = self.get_backpack_count()
            log_debug(f"[BACKPACK] Очистка не нужна ({current}/{total})")
            return None

        current, total = self.get_backpack_count()
        log_backpack(f"Нужна очистка ({current}/{total}, порог {BACKPACK_THRESHOLD})")

        return self.cleanup(max_pages)


def test_backpack(client):
    """Тест модуля рюкзака"""
    print("=" * 50)
    print("VMMO Backpack Test")
    print("=" * 50)

    backpack = BackpackClient(client)

    # Проверяем счетчик
    client.get("/city")
    current, total = backpack.get_backpack_count()
    print(f"[*] Рюкзак: {current}/{total}")
    print(f"[*] Нужна очистка: {backpack.need_cleanup()}")

    # Открываем рюкзак
    print("\n[*] Открываю рюкзак...")
    if backpack.open_backpack():
        items = backpack.get_items()
        print(f"[*] Предметов на странице: {len(items)}")

        for item in items[:10]:  # Первые 10
            status = []
            if item["is_green"]:
                status.append("зелёный")
            if item["is_protected"]:
                status.append("защищён")
            buttons = list(item["buttons"].keys())

            print(f"  - {item['name']} x{item['count']} [{', '.join(status)}] -> {buttons}")
    else:
        print("[ERR] Не удалось открыть рюкзак")


if __name__ == "__main__":
    import argparse
    from .client import VMMOClient

    parser = argparse.ArgumentParser(description="VMMO Backpack Manager")
    parser.add_argument("--cleanup", action="store_true", help="Реально очистить рюкзак (аукцион + разборка)")
    parser.add_argument("--disassemble", action="store_true", help="Только разобрать предметы")
    parser.add_argument("--auction", action="store_true", help="Только выставить на аукцион")
    args = parser.parse_args()

    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            exit(1)

    if args.cleanup:
        # Полная очистка: аукцион + разборка
        from .auction import AuctionClient

        print("=" * 50)
        print("VMMO Backpack Cleanup")
        print("=" * 50)

        backpack = BackpackClient(client)
        auction = AuctionClient(client)

        # Сначала на аукцион
        print("\n[1] Выставляю на аукцион...")
        auction_stats = auction.sell_all()

        # Потом разборка
        print("\n[2] Разбираю оставшееся...")
        backpack.open_backpack()
        disassembled = backpack.disassemble_all(skip_green=False)

        # Выбрасываем зелёный мусор
        print("\n[3] Выбрасываю зелёный мусор...")
        dropped = backpack.drop_green_unusable()

        print("\n" + "=" * 50)
        print("РЕЗУЛЬТАТ:")
        print(f"  Выставлено на аукцион: {auction_stats['listed']}")
        print(f"  Разобрано: {auction_stats['disassembled'] + disassembled}")
        print(f"  Выброшено: {dropped}")
        print("=" * 50)

    elif args.disassemble:
        print("=" * 50)
        print("VMMO Backpack - Разборка")
        print("=" * 50)

        backpack = BackpackClient(client)
        backpack.open_backpack()
        disassembled = backpack.disassemble_all(skip_green=False)
        print(f"\n[RESULT] Разобрано: {disassembled}")

    elif args.auction:
        from .auction import AuctionClient

        print("=" * 50)
        print("VMMO Backpack - Аукцион")
        print("=" * 50)

        auction = AuctionClient(client)
        stats = auction.sell_all()
        print(f"\n[RESULT] Выставлено: {stats['listed']}, разобрано: {stats['disassembled']}")

    else:
        test_backpack(client)
