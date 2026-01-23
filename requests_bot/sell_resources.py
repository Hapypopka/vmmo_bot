# ============================================
# VMMO Resource Selling Module
# ============================================
# Автоматическая продажа ресурсов на аукционе
# Минерал, Череп, Сапфир, Рубин
# ============================================

import re
import time
import json
import os
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .config import (
    get_resource_sell_settings,
    is_resource_selling_enabled,
    RESOURCE_NAMES,
    RESOURCE_IDS,
)

BASE_URL = "https://vmmo.vten.ru"

# Кэш цен для координации между ботами (30 минут TTL)
PRICE_CACHE_FILE = "/home/claude/vmmo_bot/price_cache.json"
PRICE_CACHE_TTL_MINUTES = 30


def load_price_cache():
    """Загружает кэш цен из файла"""
    try:
        if os.path.exists(PRICE_CACHE_FILE):
            with open(PRICE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[SELL] Ошибка загрузки кэша цен: {e}")
    return {}


def save_price_cache(cache):
    """Сохраняет кэш цен в файл"""
    try:
        with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[SELL] Ошибка сохранения кэша цен: {e}")


def get_cached_price(resource_key):
    """
    Получает закэшированную цену для ресурса.

    Returns:
        float: цена за единицу в серебре, или 0 если кэш устарел/не существует
    """
    cache = load_price_cache()
    entry = cache.get(resource_key)

    if not entry:
        return 0

    # Проверяем TTL
    try:
        cached_time = datetime.fromisoformat(entry.get("time", ""))
        age_minutes = (datetime.now() - cached_time).total_seconds() / 60

        if age_minutes > PRICE_CACHE_TTL_MINUTES:
            print(f"[SELL] Кэш цены {resource_key} устарел ({age_minutes:.0f} мин)")
            return 0

        price = entry.get("price", 0)
        print(f"[SELL] Используем кэшированную цену {resource_key}: {price:.2f}с/шт (возраст {age_minutes:.0f} мин)")
        return price
    except Exception as e:
        print(f"[SELL] Ошибка парсинга кэша: {e}")
        return 0


def set_cached_price(resource_key, price):
    """Сохраняет цену в кэш"""
    cache = load_price_cache()
    cache[resource_key] = {
        "price": price,
        "time": datetime.now().isoformat()
    }
    save_price_cache(cache)
    print(f"[SELL] Цена {resource_key} сохранена в кэш: {price:.2f}с/шт")


class ResourceSellerClient:
    """Клиент для продажи ресурсов на аукционе"""

    def __init__(self, client):
        """
        Args:
            client: VMMOClient instance
        """
        self.client = client
        self.sold_count = 0

    def get_current_resources(self):
        """
        Получает текущее количество ресурсов со страницы создания лота.

        Returns:
            dict: {"mineral": 1234, "skull": 567, ...} или пустой dict
        """
        # Открываем страницу выбора ресурсов для продажи
        url = f"{BASE_URL}/auction/create?category=resources&sub_resources=stones"
        self.client.get(url)
        time.sleep(0.3)

        soup = self.client.soup()
        if not soup:
            return {}

        resources = {}

        # Каждый ресурс в отдельной форме, ищем по ссылке на resource/N
        for res_key, res_id in RESOURCE_IDS.items():
            # Ищем ссылку на resource/ID
            link = soup.find("a", href=re.compile(rf"/resource/{res_id}\b"))
            if link:
                # Количество в span внутри ссылки
                text = link.get_text(strip=True)
                # Формат: "Минерал x19610"
                match = re.search(r'[xх](\d+)', text, re.IGNORECASE)
                if match:
                    resources[res_key] = int(match.group(1))

        return resources

    def sell_resource(self, resource_key, amount):
        """
        Выставляет ресурс на аукцион.

        Args:
            resource_key: mineral, skull, sapphire, ruby
            amount: количество для продажи

        Returns:
            bool: успешно ли выставлен лот
        """
        res_id = RESOURCE_IDS.get(resource_key)
        res_name = RESOURCE_NAMES.get(resource_key)

        if not res_id:
            print(f"[SELL] Неизвестный ресурс: {resource_key}")
            return False

        print(f"[SELL] Продаю {res_name} x{amount}...")

        # Открываем страницу выбора камней
        url = f"{BASE_URL}/auction/create?category=resources&sub_resources=stones"
        self.client.get(url)
        time.sleep(0.3)

        soup = self.client.soup()
        if not soup:
            print("[SELL] Не удалось загрузить страницу")
            return False

        # Ищем форму для нужного ресурса
        # Ищем ссылку на resource/ID и находим родительскую форму
        link = soup.find("a", href=re.compile(rf"/resource/{res_id}\b"))
        if not link:
            print(f"[SELL] Ресурс {res_name} не найден на странице")
            return False

        # Ищем родительскую форму
        form = link.find_parent("form")
        if not form:
            print(f"[SELL] Форма для {res_name} не найдена")
            return False

        # Собираем данные формы
        form_data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

        # Устанавливаем количество
        form_data["resourceAmount"] = str(amount)

        # URL формы
        action = form.get("action", "")
        if not action:
            print("[SELL] Action формы не найден")
            return False

        action_url = urljoin(self.client.current_url, action)

        # Отправляем форму - переходим на страницу установки цены
        self.client.post(action_url, data=form_data)
        time.sleep(0.3)

        # Теперь мы на странице установки цены
        # Сначала проверяем кэш цен (чтобы боты не перебивали друг друга)
        price_per_unit = get_cached_price(resource_key)

        if price_per_unit == 0:
            # Кэш пустой или устарел - парсим конкурента
            price_per_unit = self._get_competitor_price_per_unit()

            if price_per_unit == 0:
                # Нет конкурентов - ставим дефолтную цену ~1с за минерал
                price_per_unit = 1.0
                print(f"[SELL] Нет конкурентов, ставлю {price_per_unit}с/шт")

            # Сохраняем в кэш для других ботов
            set_cached_price(resource_key, price_per_unit)

        # Считаем цену за наш стак (на 1 серебро дешевле за весь стак)
        total_silver = int(price_per_unit * amount) - 1
        if total_silver < 1:
            total_silver = 1

        gold = total_silver // 100
        silver = total_silver % 100
        print(f"[SELL] Цена за {amount} шт: {gold}з {silver}с ({price_per_unit:.2f}с/шт - 1с)")

        # Создаём лот
        result = self._create_lot(gold, silver)

        if result == "success":
            print(f"[SELL] Лот создан: {res_name} x{amount}")
            self.sold_count += 1
            return True
        elif result == "low_price":
            print(f"[SELL] Цена слишком низкая для {res_name}")
        else:
            print(f"[SELL] Ошибка создания лота: {result}")

        return False

    def _get_competitor_price_per_unit(self):
        """
        Получает цену за единицу ресурса у конкурента.

        Returns:
            float: цена в серебре за 1 единицу (0 если нет конкурентов)
        """
        soup = self.client.soup()
        if not soup:
            return 0

        # Ищем лоты конкурентов - div.list-el с кнопкой покупки (a.go-btn)
        all_lots = soup.select("div.list-el")

        for lot in all_lots:
            # Кнопка выкупа - только у конкурентов
            buy_btn = lot.select_one("a.go-btn._auction")
            if not buy_btn:
                continue

            # Парсим количество в лоте (e-count -> potion-count -> x100)
            count_div = lot.select_one("div.e-count div.potion-count")
            if not count_div:
                continue

            count_text = count_div.get_text(strip=True)
            count_match = re.search(r'[xх](\d+)', count_text, re.IGNORECASE)
            if not count_match:
                continue

            lot_count = int(count_match.group(1))
            if lot_count == 0:
                continue

            # Парсим цену из кнопки
            # Структура: <span class="i12-money_gold"></span><span>1</span> ... <span class="i12-money_silver"></span><span>62</span>
            gold = 0
            silver = 0

            gold_icon = buy_btn.select_one("span.i12-money_gold")
            silver_icon = buy_btn.select_one("span.i12-money_silver")

            # Ищем число сразу после иконки золота
            if gold_icon:
                next_span = gold_icon.find_next_sibling("span")
                if next_span:
                    text = next_span.get_text(strip=True)
                    if text.isdigit():
                        gold = int(text)

            # Ищем число сразу после иконки серебра
            if silver_icon:
                next_span = silver_icon.find_next_sibling("span")
                if next_span:
                    text = next_span.get_text(strip=True)
                    if text.isdigit():
                        silver = int(text)

            # Считаем цену за единицу в серебре
            total_silver = gold * 100 + silver
            price_per_unit = total_silver / lot_count

            print(f"[SELL] Конкурент: {lot_count} шт за {gold}з {silver}с = {price_per_unit:.2f}с/шт")
            return price_per_unit

        return 0

    def _create_lot(self, gold, silver):
        """
        Создаёт лот с указанной ценой.

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
            print("[SELL] Форма цены не найдена")
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

        # URL формы
        action = form.get("action", "")
        if not action:
            print("[SELL] Action формы цены не найден")
            return "error"

        action_url = urljoin(self.client.current_url, action)

        # Отправляем форму
        self.client.post(action_url, data=form_data)
        time.sleep(0.3)

        # Проверяем результат
        soup = self.client.soup()
        if not soup:
            return "error"

        # Проверяем ошибку
        error = soup.select_one("span.feedbackPanelERROR")
        if error:
            text = error.get_text()
            print(f"[SELL] Сервер вернул ошибку: {text}")
            if "ниже рыночной" in text.lower() or "низкая" in text.lower():
                return "low_price"
            return "error"

        # Проверяем успех - должны попасть на страницу "Мои лоты" или увидеть подтверждение
        page_text = soup.get_text()
        if "Лот успешно" in page_text or "создан" in page_text.lower():
            return "success"

        # Проверяем URL - если мы на странице лотов, значит успех
        if "/auction/my" in self.client.current_url or "/auction" in self.client.current_url:
            return "success"

        return "success"

    def sell_all(self):
        """
        Продаёт все ресурсы согласно настройкам.

        Логика:
        - Для каждого ресурса проверяем: current >= reserve + stack
        - Если да, продаём (current - reserve) // stack стаков

        Returns:
            dict: {"sold": N, "errors": N}
        """
        if not is_resource_selling_enabled():
            return {"sold": 0, "errors": 0}

        stats = {"sold": 0, "errors": 0}
        settings = get_resource_sell_settings()

        # Получаем текущие количества
        current_resources = self.get_current_resources()
        if not current_resources:
            print("[SELL] Не удалось получить ресурсы")
            return stats

        for res_key, res_settings in settings.items():
            if not res_settings.get("enabled", False):
                continue

            stack = res_settings.get("stack", 1000)
            reserve = res_settings.get("reserve", 200)
            current = current_resources.get(res_key, 0)
            res_name = RESOURCE_NAMES.get(res_key, res_key)

            # Сколько стаков можно продать?
            available = current - reserve
            if available < stack:
                continue  # Недостаточно для продажи - не логируем

            stacks_to_sell = available // stack
            print(f"[SELL] {res_name}: {current}, продаём {stacks_to_sell} x {stack}")

            for i in range(stacks_to_sell):
                if self.sell_resource(res_key, stack):
                    stats["sold"] += 1
                else:
                    stats["errors"] += 1
                    break  # Прекращаем если ошибка

                time.sleep(0.5)

                # Обновляем ресурсы после каждой продажи
                current_resources = self.get_current_resources()

        self.sold_count = stats["sold"]
        if stats["sold"] > 0 or stats["errors"] > 0:
            print(f"[SELL] Итого продано: {stats['sold']}, ошибок: {stats['errors']}")
        return stats


def sell_resources(client):
    """
    Главная функция продажи ресурсов.

    Args:
        client: VMMOClient instance

    Returns:
        dict: {"sold": N, "errors": N}
    """
    seller = ResourceSellerClient(client)
    return seller.sell_all()
