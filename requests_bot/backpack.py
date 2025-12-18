# ============================================
# VMMO Backpack Module (requests version)
# ============================================
# Управление рюкзаком: просмотр, разборка, выброс
# ============================================

import re
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin

try:
    from requests_bot.logger import log_debug, log_info, log_warning, log_backpack
except ImportError:
    # Fallback если запускается напрямую
    def log_debug(msg): print(f"[DEBUG] {msg}")
    def log_info(msg): print(f"[INFO] {msg}")
    def log_warning(msg): print(f"[WARN] {msg}")
    def log_backpack(msg): print(f"[BACKPACK] {msg}")

BASE_URL = "https://vmmo.vten.ru"
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Защищённые предметы - не продавать и не разбирать
PROTECTED_ITEMS = [
    "Железо",
    "Железная Руда",
    "Железный Слиток",
    "Осколок Грёз",
    "Осколок Порядка",
    "Осколок Рассвета",
    "Осколок Ночи",
    "Осколок Тени",
    "Осколок Хаоса",
    "Треснутый Кристалл Тикуана",
    "Печать Сталкера",
    "Печать Сталкера I",
    "Печать Сталкера II",
    "Печать Сталкера III",
    "Ледяной Кристалл",
    "Уголь Эфирного Древа",
]

# Порог для очистки рюкзака
BACKPACK_THRESHOLD = 15


def is_protected_item(item_name):
    """Проверяет, защищён ли предмет от продажи/разборки"""
    for protected in PROTECTED_ITEMS:
        if protected.lower() in item_name.lower():
            return True
    return False


def load_auction_blacklist():
    """Загружает чёрный список аукциона"""
    path = os.path.join(SCRIPT_DIR, "auction_blacklist.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_auction_blacklist(blacklist):
    """Сохраняет чёрный список аукциона"""
    path = os.path.join(SCRIPT_DIR, "auction_blacklist.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blacklist, f, ensure_ascii=False, indent=2)


def add_to_auction_blacklist(item_name):
    """Добавляет предмет в чёрный список аукциона"""
    blacklist = load_auction_blacklist()
    if item_name not in blacklist:
        blacklist.append(item_name)
        save_auction_blacklist(blacklist)
        print(f"[BLACKLIST] Добавлен: {item_name}")


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

        for item_div in soup.select("div.p10"):
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

            # Качество (зелёный = iGood)
            is_green = "iGood" in classes

            # Кнопки действий
            buttons = {}
            for btn in item_div.select("a.go-btn"):
                btn_text = btn.get_text(strip=True)
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

            items.append({
                "name": name,
                "count": count,
                "is_green": is_green,
                "is_protected": is_protected_item(name),
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
        """Открывает все бонусы в рюкзаке"""
        if not self.open_backpack():
            return 0

        opened = 0
        for _ in range(50):  # Защита от бесконечного цикла
            items = self.get_items()
            bonus_items = [i for i in items if "бонус" in i["name"].lower() and "open" in i["buttons"]]

            if not bonus_items:
                break

            item = bonus_items[0]
            log_backpack(f"Открываю: {item['name']}")
            if self.open_bonus(item):
                opened += 1
            else:
                break

        return opened

    def disassemble_all(self, skip_green=True):
        """
        Разбирает все предметы с кнопкой разборки.

        Args:
            skip_green: Пропускать зелёные предметы

        Returns:
            int: Количество разобранных
        """
        if not self.open_backpack():
            return 0

        disassembled = 0
        blacklist = load_auction_blacklist()

        for _ in range(100):  # Защита
            items = self.get_items()
            log_debug(f"[BACKPACK] Предметов на странице: {len(items)}")

            # Ищем предмет для разборки
            target = None
            for item in items:
                if item["is_protected"]:
                    continue
                if skip_green and item["is_green"]:
                    continue
                if "disassemble" not in item["buttons"]:
                    continue
                # Зелёные и из blacklist - разбираем
                if item["is_green"] or item["name"] in blacklist:
                    target = item
                    break
                target = item
                break

            if not target:
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

    def cleanup(self, max_pages=3):
        """
        Полная очистка рюкзака.

        1. Открывает бонусы
        2. Разбирает предметы
        3. Выбрасывает зелёные без пользы

        Args:
            max_pages: Максимум страниц для обработки

        Returns:
            dict: Статистика {bonuses, disassembled, dropped}
        """
        stats = {
            "bonuses": 0,
            "disassembled": 0,
            "dropped": 0,
        }

        log_backpack("Начинаю очистку рюкзака...")

        for page in range(1, max_pages + 1):
            if page > 1:
                if not self.go_to_next_page(page - 1):
                    break
                log_debug(f"[BACKPACK] Страница {page}")

            # Открываем бонусы
            opened = self.open_all_bonuses()
            stats["bonuses"] += opened

            # Разбираем (включая зелёные)
            disassembled = self.disassemble_all(skip_green=False)
            stats["disassembled"] += disassembled

            # Выбрасываем бесполезные зелёные
            dropped = self.drop_green_unusable()
            stats["dropped"] += dropped

        log_backpack(f"Очистка завершена: бонусов {stats['bonuses']}, разобрано {stats['disassembled']}, выброшено {stats['dropped']}")
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
