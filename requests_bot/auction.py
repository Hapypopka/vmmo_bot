# ============================================
# VMMO Auction Module (requests version)
# ============================================
# Выставление предметов на аукцион
# ============================================

import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .backpack import (
    BackpackClient,
    is_protected_item,
    load_auction_blacklist,
    add_to_auction_blacklist,
)

BASE_URL = "https://vmmo.vten.ru"

# Минимальная цена по умолчанию (в серебре)
DEFAULT_MIN_PRICE = 5


class AuctionClient:
    """Клиент для работы с аукционом"""

    def __init__(self, client):
        """
        Args:
            client: VMMOClient instance
        """
        self.client = client
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

        # Ищем первый лот конкурента
        competitor = soup.select_one("div.list-el.first") or soup.select_one("div.list-el")
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
        if not buy_btn:
            return 0, 0, 0

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

    def calculate_price(self, my_count):
        """
        Рассчитывает цену для нашего лота.

        Args:
            my_count: Количество нашего товара

        Returns:
            tuple: (gold, silver)
        """
        comp_gold, comp_silver, comp_count = self.get_competitor_min_price()

        if comp_count == 0 or (comp_gold == 0 and comp_silver == 0):
            # Конкурентов нет - минимальная цена
            return 0, DEFAULT_MIN_PRICE

        # Цена за единицу в серебре
        total_silver = comp_gold * 100 + comp_silver
        price_per_unit = total_silver // comp_count

        # Наша цена
        our_total = (price_per_unit * my_count) - 1
        if our_total < DEFAULT_MIN_PRICE:
            our_total = DEFAULT_MIN_PRICE

        gold = our_total // 100
        silver = our_total % 100

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

                # Предметы из blacklist - разбираем
                if name in blacklist:
                    print(f"[AUCTION] '{name}' в чёрном списке - разбираем")
                    if self.backpack.disassemble_item(item):
                        stats["disassembled"] += 1
                    continue

                # Нужна кнопка аукциона
                if "auction" not in item["buttons"]:
                    continue

                target = item
                break

            if not target:
                # Больше нет предметов для аукциона
                break

            name = target["name"]
            is_green = target["is_green"]

            # Зелёные предметы с кнопкой разборки - разбираем
            # Зелёные БЕЗ кнопки разборки - выставляем на аукцион
            if is_green and "disassemble" in target["buttons"]:
                print(f"[AUCTION] '{name}' зелёный с разборкой - разбираем")
                disassemble_url = target["buttons"]["disassemble"]
                self.client.get(disassemble_url)
                # Ищем кнопку подтверждения
                soup = self.client.soup()
                for btn in soup.select("a.go-btn"):
                    text = btn.get_text(strip=True)
                    if "да" in text.lower() and "точно" in text.lower():
                        href = btn.get("href")
                        if href:
                            confirm_url = href if href.startswith("http") else urljoin(self.client.current_url, href)
                            self.client.get(confirm_url)
                            print(f"[AUCTION] Разобрано: {name}")
                            stats["disassembled"] += 1
                            break
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

            if comp_gold > 0 or comp_silver > 0:
                # Есть конкуренты
                comp_total = comp_gold * 100 + comp_silver
                price_per_unit = comp_total // comp_count
                our_total = (price_per_unit * my_count) - 1
                our_total = max(DEFAULT_MIN_PRICE, our_total)
                gold = our_total // 100
                silver = our_total % 100
                print(f"[AUCTION] Конкурент: {comp_gold}g {comp_silver}s за x{comp_count} -> {price_per_unit}s/шт")
                print(f"[AUCTION] Наш товар: x{my_count} -> ставим {gold}g {silver}s")
            else:
                # Нет конкурентов
                gold = 0
                silver = DEFAULT_MIN_PRICE
                print(f"[AUCTION] Нет конкурентов - минимальная цена {silver}s")

            # Создаём лот
            result = self.try_create_lot(gold, silver)

            if result == "success":
                print(f"[AUCTION] Лот создан!")
                stats["listed"] += 1
                time.sleep(0.5)

            elif result == "low_price":
                print(f"[AUCTION] Цена слишком низкая - '{name}' для разборки")
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
