# ============================================
# VMMO Gold Transfer Module
# ============================================
# Передача золота между персонажами через аукцион
# Мейн выставляет Рубин за завышенную цену, альт покупает
# ============================================

import re
import time
import os
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .client import VMMOClient
from .mail import MailClient
from .config import RESOURCE_IDS, RESOURCE_NAMES, PROFILES_DIR, set_profile

BASE_URL = "https://vmmo.vten.ru"

# Глобальный флаг остановки
_stop_requested = False


def request_stop():
    """Запрашивает остановку текущего трансфера"""
    global _stop_requested
    _stop_requested = True


def clear_stop():
    """Сбрасывает флаг остановки"""
    global _stop_requested
    _stop_requested = False


def is_stop_requested() -> bool:
    """Проверяет запрошена ли остановка"""
    return _stop_requested


def get_profile_list():
    """Получает список всех профилей из файловой системы"""
    profiles = []
    if os.path.exists(PROFILES_DIR):
        for folder in sorted(os.listdir(PROFILES_DIR)):
            folder_path = os.path.join(PROFILES_DIR, folder)
            if os.path.isdir(folder_path) and folder.startswith("char"):
                config_path = os.path.join(folder_path, "config.json")
                if os.path.exists(config_path):
                    profiles.append(folder)
    return profiles

# Конфигурация трансфера
TRANSFER_CONFIG = {
    "reserve_gold": 10,          # сколько золота оставить альту
    "transfer_item": "ruby",     # ресурс для трансфера (всегда Рубин)
    # 2026-06-03: разгадан корень.
    # get_market_price брал bidGold/bidSilver из ФОРМЫ — это рекомендация
    # системы, а не реальная минималка. Например: форма пишет 11с, а на
    # самом аукционе самый дешёвый лот: 1000 рубинов за 70з 64с (7.06с/шт).
    # Сервер ставит лимит x100 от реальной минималки (~706с/шт), а наш
    # x100 от формы давал ~1100с/шт → сервер режет.
    # Юзер руками ставил 6з 95с = 695с (x98.4 от реальной) → прошло.
    #
    # Решение: новый метод get_actual_min_ruby_price_silver — парсит
    # реальные лоты с страницы аукциона. Берём x90 от него с safety=1.0.
    "price_multiplier": 100,
    "safety_factor": 1.0,
    # 2026-06-03: ступенька в лимите сервера.
    # Тест: amount=10 за 100з прошло, 200з — нет. amount=13 за 80з — режется.
    # Значит сервер ужесточает лимит per_unit между amount=10..13.
    # Решение: жёстко фиксируем 10 рубинов в лот, потолок 70з (= 10 * 7з/шт).
    "target_lot_amount": 10,
    "max_lot_gold": 70,
    "auction_fee": 0.05,         # комиссия 5%
    "retry_attempts": 3,         # попыток найти лот
    "retry_delay": 2,            # секунд между попытками
    # Останавливать весь трансфер при первой ошибке create_lot.
    # 2026-06-03: после нахождения формулы (max_lot_gold=80) — выключено.
    # Если лот не пройдёт по случайным причинам, бот идёт к следующему альту.
    # Включи если хочешь снова видеть стоп на первой ошибке для дебага.
    "stop_on_first_error": False,
}


class GoldTransferClient:
    """Клиент для передачи золота между персонажами"""

    def __init__(self, profile: str):
        """
        Args:
            profile: имя профиля (char1, char2, ...)
        """
        self.profile = profile
        # Устанавливаем профиль чтобы обновить пути к cookies
        set_profile(profile)
        self.client = VMMOClient()
        self.client.load_cookies()

    def get_gold_balance(self) -> int:
        """
        Получает баланс золота персонажа.

        Returns:
            int: количество золота (0 если не удалось получить)
        """
        # Открываем любую страницу с хедером (город)
        url = f"{BASE_URL}/city"
        self.client.get(url)
        time.sleep(0.3)

        soup = self.client.soup()
        if not soup:
            print(f"[TRANSFER] {self.profile}: не удалось загрузить страницу")
            return 0

        # Ищем div.header-gold-info
        gold_info = soup.select_one("div.header-gold-info")
        if not gold_info:
            print(f"[TRANSFER] {self.profile}: header-gold-info не найден")
            return 0

        # Ищем иконку золота и число после неё
        gold_icon = gold_info.select_one("span.i12-money_gold")
        if not gold_icon:
            print(f"[TRANSFER] {self.profile}: иконка золота не найдена")
            return 0

        # Число в следующем span
        next_span = gold_icon.find_next_sibling("span")
        if next_span:
            text = next_span.get_text(strip=True)
            if text.isdigit():
                gold = int(text)
                print(f"[TRANSFER] {self.profile}: баланс {gold}з")
                return gold

        print(f"[TRANSFER] {self.profile}: не удалось распарсить баланс")
        return 0

    def get_ruby_count(self) -> int:
        """
        Получает количество рубинов у персонажа.

        Returns:
            int: количество рубинов
        """
        ruby_id = RESOURCE_IDS.get("ruby", 5)

        # Открываем страницу выбора ресурсов для продажи
        url = f"{BASE_URL}/auction/create?category=resources&sub_resources=stones"
        self.client.get(url)
        time.sleep(0.3)

        soup = self.client.soup()
        if not soup:
            return 0

        # Ищем ссылку на resource/5 (Рубин)
        link = soup.find("a", href=re.compile(rf"/resource/{ruby_id}\b"))
        if link:
            text = link.get_text(strip=True)
            # Формат: "Рубин x500"
            match = re.search(r'[xх](\d+)', text, re.IGNORECASE)
            if match:
                count = int(match.group(1))
                print(f"[TRANSFER] {self.profile}: рубинов {count}")
                return count

        print(f"[TRANSFER] {self.profile}: рубины не найдены")
        return 0

    def get_market_price(self) -> int:
        """
        Получает рыночную цену рубина в серебре.
        Цена приходит предзаполненной в форме.

        Returns:
            int: цена в серебре (0 если ошибка)
        """
        ruby_id = RESOURCE_IDS.get("ruby", 5)

        # Переходим на страницу создания лота с рубином
        # Сначала выбираем рубин на странице категорий
        url = f"{BASE_URL}/auction/create?category=resources&sub_resources=stones"
        self.client.get(url)
        time.sleep(0.3)

        soup = self.client.soup()
        if not soup:
            return 0

        # Находим форму для рубина и отправляем её
        link = soup.find("a", href=re.compile(rf"/resource/{ruby_id}\b"))
        if not link:
            print(f"[TRANSFER] Рубин не найден на странице ресурсов")
            return 0

        form = link.find_parent("form")
        if not form:
            print(f"[TRANSFER] Форма для рубина не найдена")
            return 0

        # Собираем данные формы
        form_data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

        # Выставляем 1 рубин
        form_data["resourceAmount"] = "1"

        action = form.get("action", "")
        if not action:
            return 0

        action_url = urljoin(self.client.current_url, action)

        # Отправляем форму - переходим на страницу цены
        self.client.post(action_url, data=form_data)
        time.sleep(0.3)

        # Теперь парсим предзаполненную цену
        soup = self.client.soup()
        if not soup:
            return 0

        bid_gold = soup.find("input", {"name": "bidGold"})
        bid_silver = soup.find("input", {"name": "bidSilver"})

        gold = int(bid_gold.get("value", 0)) if bid_gold else 0
        silver = int(bid_silver.get("value", 0)) if bid_silver else 0

        market_price = gold * 100 + silver
        print(f"[TRANSFER] Рыночная цена рубина (из формы): {gold}з {silver}с = {market_price}с")

        return market_price

    def get_actual_min_ruby_price_silver(self) -> int:
        """
        Парсит РЕАЛЬНУЮ минимальную цену рубина (за 1 шт в серебре)
        среди существующих лотов на странице создания.

        Игра ставит лимит x100 от ЭТОЙ цены, а не от bidGold/bidSilver
        в форме. Если бот ставит цену с учётом реальной минималки —
        сервер не режет лот как "значительно выше рыночной".

        Returns:
            int: минимальная цена за 1 рубин в серебре, или 0 если не найдено
        """
        ruby_name = RESOURCE_NAMES.get("ruby", "Рубин")

        # 1. Открываем категорию stones — там сейчас только минералы по
        #    умолчанию, рубины надо искать.
        url = f"{BASE_URL}/auction?category=resources&sub_resources=stones"
        self.client.get(url)
        time.sleep(0.3)
        soup = self.client.soup()
        if not soup:
            return 0

        # 2. Ищем форму поиска и POST с именем "Рубин".
        search_form = soup.find("form", {"action": lambda x: x and "search" in x})
        if search_form:
            form_action = search_form.get("action", "")
            if not form_action.startswith("http"):
                form_action = urljoin(BASE_URL, form_action)
            name_input = search_form.find("input", {"type": "text"})
            input_name = name_input.get("name", "name") if name_input else "name"
            self.client.post(form_action, data={input_name: ruby_name})
            time.sleep(0.3)
            soup = self.client.soup()
            if not soup:
                return 0
        else:
            print(f"[TRANSFER] Форма поиска не найдена на /auction")

        # 3. Парсим лоты. По умолчанию сортировка по цене — на первой
        #    странице самые дешёвые, этого достаточно для минимума.
        lots = soup.select("div.list-el")
        min_per_unit = None
        ruby_lots_seen = 0
        for lot in lots:
            name_el = lot.select_one("div.e-name") or lot.select_one("span.e-name")
            if not name_el:
                continue
            name_text = name_el.get_text(strip=True)
            if ruby_name not in name_text:
                continue
            ruby_lots_seen += 1

            # Количество: div.e-count → "x100"
            count_el = lot.select_one("div.e-count, span.e-count")
            count = 0
            if count_el:
                m = re.search(r'[xх](\d+)', count_el.get_text(strip=True), re.IGNORECASE)
                if m:
                    count = int(m.group(1))
            if count == 0:
                continue

            # Цена выкупа: a.go-btn._auction (для чужих) или span.go-btn._auction
            # (для своих) — оба задают рыночный уровень.
            buy_btn = lot.select_one("a.go-btn._auction, span.go-btn._auction")
            if not buy_btn:
                continue
            gold, silver = self._parse_button_price(buy_btn)
            price_silver = gold * 100 + silver
            if price_silver == 0:
                continue

            per_unit = price_silver / count
            if min_per_unit is None or per_unit < min_per_unit:
                min_per_unit = per_unit

        if min_per_unit is None:
            print(f"[TRANSFER] Не удалось распарсить лоты рубинов (lots={len(lots)}, рубинов={ruby_lots_seen})")
            return 0

        result = int(min_per_unit)
        print(f"[TRANSFER] Реальная минималка рубина на аукционе: {result}с/шт (из {ruby_lots_seen} лотов)")
        return result

    def create_lot(self, amount: int, price_silver: int) -> bool:
        """
        Выставляет рубины на аукцион за указанную цену.

        Args:
            amount: количество рубинов
            price_silver: цена в серебре

        Returns:
            bool: успешно ли создан лот
        """
        ruby_id = RESOURCE_IDS.get("ruby", 5)
        ruby_name = RESOURCE_NAMES.get("ruby", "Рубин")

        print(f"[TRANSFER] Выставляю {ruby_name} x{amount} за {price_silver}с...")

        # Переходим на страницу камней
        url = f"{BASE_URL}/auction/create?category=resources&sub_resources=stones"
        self.client.get(url)
        time.sleep(0.3)

        soup = self.client.soup()
        if not soup:
            print(f"[TRANSFER] Не удалось загрузить страницу")
            return False

        # Находим форму рубина
        link = soup.find("a", href=re.compile(rf"/resource/{ruby_id}\b"))
        if not link:
            print(f"[TRANSFER] Рубин не найден")
            return False

        form = link.find_parent("form")
        if not form:
            print(f"[TRANSFER] Форма не найдена")
            return False

        # Собираем данные
        form_data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

        form_data["resourceAmount"] = str(amount)

        action = form.get("action", "")
        if not action:
            return False

        action_url = urljoin(self.client.current_url, action)

        # Отправляем - переходим на страницу цены
        self.client.post(action_url, data=form_data)
        time.sleep(0.3)

        # Устанавливаем цену и создаём лот
        return self._set_price_and_create(price_silver)

    def _set_price_and_create(self, price_silver: int) -> bool:
        """
        Устанавливает цену и создаёт лот.

        Args:
            price_silver: цена в серебре

        Returns:
            bool: успех
        """
        soup = self.client.soup()
        if not soup:
            return False

        form = soup.find("form")
        if not form:
            print(f"[TRANSFER] Форма цены не найдена")
            return False

        # Конвертируем серебро в золото/серебро
        gold = price_silver // 100
        silver = price_silver % 100

        # Собираем данные формы
        form_data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

        # Устанавливаем цены (bid = buyout)
        form_data["bidGold"] = str(gold)
        form_data["bidSilver"] = str(silver)
        form_data["buyoutGold"] = str(gold)
        form_data["buyoutSilver"] = str(silver)

        action = form.get("action", "")
        if not action:
            return False

        action_url = urljoin(self.client.current_url, action)

        print(f"[TRANSFER] Создаю лот за {gold}з {silver}с...")

        # Отправляем
        self.client.post(action_url, data=form_data)
        time.sleep(0.3)

        # Проверяем результат
        soup = self.client.soup()
        if not soup:
            return False

        # Проверяем ошибку
        error = soup.select_one("span.feedbackPanelERROR")
        if error:
            text = error.get_text()
            print(f"[TRANSFER] Ошибка: {text}")
            return False

        print(f"[TRANSFER] Лот создан успешно")
        return True

    def find_and_buy_lot(self, price_silver: int) -> bool:
        """
        Ищет лот рубина по ТОЧНОЙ цене и покупает его.
        Использует поиск по названию и пагинацию.

        Args:
            price_silver: точная цена в серебре

        Returns:
            bool: успешно ли куплен лот
        """
        ruby_name = RESOURCE_NAMES.get("ruby", "Рубин")
        target_gold = price_silver // 100
        target_silver = price_silver % 100

        print(f"[TRANSFER] Ищу лот {ruby_name} за {target_gold}з {target_silver}с...")

        for attempt in range(TRANSFER_CONFIG["retry_attempts"]):
            # Шаг 1: Открываем аукцион - ресурсы - камни
            url = f"{BASE_URL}/auction?category=resources&sub_resources=stones"
            print(f"[TRANSFER] Открываю: {url}")
            self.client.get(url)
            time.sleep(0.3)

            # Шаг 2: Ищем форму поиска и вводим "Рубин"
            soup = self.client.soup()
            if not soup:
                print(f"[TRANSFER] Не удалось получить страницу аукциона!")
                continue

            # Находим форму поиска
            search_form = soup.find("form", {"action": lambda x: x and "search" in x})
            if search_form:
                # Получаем action URL
                form_action = search_form.get("action", "")
                print(f"[TRANSFER] Форма поиска найдена, action: {form_action}")
                if not form_action.startswith("http"):
                    form_action = urljoin(BASE_URL, form_action)

                # Находим имя поля ввода
                name_input = search_form.find("input", {"type": "text"})
                input_name = name_input.get("name", "name") if name_input else "name"

                # Отправляем поиск
                print(f"[TRANSFER] Поиск по названию: {ruby_name}, поле: {input_name}")
                self.client.post(form_action, data={input_name: ruby_name})
                time.sleep(0.3)
            else:
                print(f"[TRANSFER] Форма поиска НЕ найдена!")

            # Шаг 3: Сначала перейти на ПОСЛЕДНЮЮ страницу (дорогие лоты там)
            soup = self.client.soup()
            if not soup:
                print(f"[TRANSFER] Не удалось получить страницу после поиска!")
                continue

            # Проверяем сколько лотов нашли
            lots = soup.select("div.list-el")
            print(f"[TRANSFER] Найдено лотов на странице: {len(lots)}")

            last_page_url = self._find_last_page_url(soup)
            if last_page_url:
                print(f"[TRANSFER] Перехожу на последнюю страницу: {last_page_url}")
                if not last_page_url.startswith("http"):
                    last_page_url = urljoin(BASE_URL, last_page_url)
                self.client.get(last_page_url)
                time.sleep(0.3)
            else:
                print(f"[TRANSFER] Пагинация не найдена, только одна страница")

            # Шаг 4: Перебираем страницы с конца
            max_pages = 10  # Максимум страниц для просмотра
            for page_num in range(max_pages):
                soup = self.client.soup()
                if not soup:
                    print(f"[TRANSFER] Не удалось получить страницу!")
                    break

                current_page = self._get_current_page_number(soup)
                lots = soup.select("div.list-el")
                print(f"[TRANSFER] Страница {current_page}, лотов: {len(lots)}")

                # Ищем лот на текущей странице
                result = self._find_lot_on_page(soup, ruby_name, target_gold, target_silver)
                if result:
                    buyout_url = result
                    print(f"[TRANSFER] Лот найден! URL: {buyout_url}")
                    if not buyout_url.startswith("http"):
                        buyout_url = urljoin(BASE_URL, buyout_url)
                    return self._buy_lot(buyout_url)

                # Ищем ссылку на ПРЕДЫДУЩУЮ страницу (идём с конца)
                if current_page <= 1:
                    print(f"[TRANSFER] Дошли до первой страницы, лот не найден")
                    break

                prev_page_url = self._find_page_url(soup, current_page - 1)
                if not prev_page_url:
                    print(f"[TRANSFER] Не нашли ссылку на страницу {current_page - 1}")
                    break

                print(f"[TRANSFER] Перехожу на страницу {current_page - 1}")
                if not prev_page_url.startswith("http"):
                    prev_page_url = urljoin(BASE_URL, prev_page_url)
                self.client.get(prev_page_url)
                time.sleep(0.3)

            # Лот не найден на всех страницах - ждём и пробуем снова
            print(f"[TRANSFER] Лот не найден, попытка {attempt + 1}/{TRANSFER_CONFIG['retry_attempts']}")
            time.sleep(TRANSFER_CONFIG["retry_delay"])

        print(f"[TRANSFER] Лот не найден после {TRANSFER_CONFIG['retry_attempts']} попыток")
        return False

    def _find_lot_on_page(self, soup, ruby_name: str, target_gold: int, target_silver: int) -> str | None:
        """
        Ищет лот на странице по точной цене.

        Returns:
            str | None: URL кнопки выкупа или None
        """
        lots = soup.select("div.list-el")
        print(f"[TRANSFER] Проверяю {len(lots)} лотов, ищу {target_gold}з {target_silver}с")

        for i, lot in enumerate(lots):
            # Проверяем что это рубин
            name_el = lot.select_one("div.e-name")
            lot_name = name_el.get_text(strip=True) if name_el else "?"

            if not name_el or ruby_name not in name_el.get_text():
                continue

            # Ищем кнопку выкупа (a, не span - span это наш собственный лот)
            buy_btn = lot.select_one("a.go-btn._auction")
            if not buy_btn:
                # Проверяем есть ли span (свой лот)
                own_lot = lot.select_one("span.go-btn._auction")
                if own_lot:
                    print(f"[TRANSFER]   Лот #{i+1}: {lot_name} - СВОЙ ЛОТ (span)")
                else:
                    print(f"[TRANSFER]   Лот #{i+1}: {lot_name} - нет кнопки выкупа")
                continue

            # Проверяем что это именно "выкупить" а не что-то другое
            btn_text = buy_btn.get_text(strip=True).lower()
            if "выкупить" not in btn_text:
                print(f"[TRANSFER]   Лот #{i+1}: {lot_name} - кнопка '{btn_text}' (не выкупить)")
                continue

            # Парсим цену из кнопки
            lot_gold, lot_silver = self._parse_button_price(buy_btn)
            print(f"[TRANSFER]   Лот #{i+1}: {lot_name} - {lot_gold}з {lot_silver}с")

            # Проверяем ТОЧНОЕ совпадение цены
            if lot_gold == target_gold and lot_silver == target_silver:
                href = buy_btn.get("href", "")
                print(f"[TRANSFER] СОВПАДЕНИЕ! href={href}")
                return href

        print(f"[TRANSFER] Лот с ценой {target_gold}з {target_silver}с не найден на странице")
        return None

    def _find_last_page_url(self, soup) -> str | None:
        """
        Ищет ссылку на последнюю страницу пагинации.

        Returns:
            str | None: URL последней страницы или None
        """
        pager = soup.select_one("div.b-page")
        if not pager:
            return None

        # Сначала ищем кнопку ">" (paginator-last) - она ведёт на последнюю страницу
        last_btn = pager.select_one("a.page.next")
        if last_btn:
            href = last_btn.get("href", "")
            if "paginator-last" in href:
                return href

        # Если нет кнопки ">", берём последнюю числовую ссылку
        page_links = pager.select("a.page")
        if not page_links:
            return None

        # Фильтруем только числовые страницы (не ">" кнопки)
        for link in reversed(page_links):
            text = link.get_text(strip=True)
            if text.isdigit():
                return link.get("href", "")

        return None

    def _get_current_page_number(self, soup) -> int:
        """
        Определяет номер текущей страницы.

        Returns:
            int: номер текущей страницы (1 если не удалось определить)
        """
        pager = soup.select_one("div.b-page")
        if not pager:
            return 1

        # Текущая страница - это span.page (не ссылка a.page)
        current = pager.select_one("span.page")
        if current:
            text = current.get_text(strip=True)
            if text.isdigit():
                return int(text)

        return 1

    def _find_page_url(self, soup, page_number: int) -> str | None:
        """
        Ищет ссылку на конкретную страницу пагинации.

        Args:
            soup: BeautifulSoup объект
            page_number: номер страницы

        Returns:
            str | None: URL страницы или None
        """
        pager = soup.select_one("div.b-page")
        if not pager:
            return None

        # Ищем ссылку на нужную страницу
        page_links = pager.select("a.page")
        for link in page_links:
            title = link.get("title", "")
            if f"страницу {page_number}" in title.lower():
                return link.get("href", "")

        return None

    def _parse_button_price(self, button) -> tuple:
        """
        Парсит цену из кнопки выкупа.

        Args:
            button: BeautifulSoup element кнопки

        Returns:
            tuple: (gold, silver)
        """
        gold = 0
        silver = 0

        gold_icon = button.select_one("span.i12-money_gold")
        silver_icon = button.select_one("span.i12-money_silver")

        if gold_icon:
            next_span = gold_icon.find_next_sibling("span")
            if next_span:
                text = next_span.get_text(strip=True)
                if text.isdigit():
                    gold = int(text)

        if silver_icon:
            next_span = silver_icon.find_next_sibling("span")
            if next_span:
                text = next_span.get_text(strip=True)
                if text.isdigit():
                    silver = int(text)

        return gold, silver

    def _buy_lot(self, buyout_url: str) -> bool:
        """
        Покупает лот по URL.
        После клика на "выкупить" появляется диалог подтверждения,
        нужно кликнуть на "Да, точно" (confirmLink).

        Args:
            buyout_url: URL кнопки выкупа

        Returns:
            bool: успех
        """
        print(f"[TRANSFER] Покупаю лот: {buyout_url}")

        # Шаг 1: Кликаем на кнопку "выкупить" - появится диалог подтверждения
        resp = self.client.get(buyout_url)
        time.sleep(0.5)

        soup = self.client.soup()
        if not soup:
            print(f"[TRANSFER] Нет ответа после клика на выкупить!")
            return False

        # Шаг 2: Ищем кнопку "Да, точно" (confirmLink) в диалоге подтверждения
        confirm_btn = soup.select_one("a.go-btn[href*='confirmLink']")
        if not confirm_btn:
            # Попробуем найти по тексту
            for btn in soup.select("a.go-btn"):
                btn_text = btn.get_text(strip=True)
                if "Да, точно" in btn_text:
                    confirm_btn = btn
                    break

        if confirm_btn:
            confirm_url = confirm_btn.get("href", "")
            print(f"[TRANSFER] Найдена кнопка подтверждения: {confirm_url}")

            if not confirm_url.startswith("http"):
                confirm_url = urljoin(BASE_URL, confirm_url)

            # Шаг 3: Кликаем на "Да, точно"
            resp = self.client.get(confirm_url)
            time.sleep(0.5)

            soup = self.client.soup()
            if not soup:
                print(f"[TRANSFER] Нет ответа после подтверждения!")
                return False
        else:
            print(f"[TRANSFER] Кнопка подтверждения НЕ найдена!")
            # Выводим HTML для отладки
            page_text = soup.get_text()[:500]
            print(f"[TRANSFER] Текст страницы: {page_text}")
            return False

        # Шаг 4: Проверяем результат
        page_text = soup.get_text()

        # Проверяем ошибки
        error = soup.select_one("span.feedbackPanelERROR")
        if error:
            text = error.get_text()
            print(f"[TRANSFER] Ошибка покупки: {text}")
            return False

        # Проверяем успех - ищем feedbackPanel
        feedback_info = soup.select_one("span.feedbackPanelINFO")
        feedback_success = soup.select_one("span.feedbackPanelSUCCESS")

        if feedback_info:
            text = feedback_info.get_text()
            print(f"[TRANSFER] FeedbackINFO: {text}")
            if "куплен" in text.lower():
                print(f"[TRANSFER] Лот куплен успешно!")
                return True

        if feedback_success:
            text = feedback_success.get_text()
            print(f"[TRANSFER] FeedbackSUCCESS: {text}")
            return True

        # Проверяем успех по тексту
        if "Лот куплен" in page_text or "успешно куплен" in page_text.lower():
            print(f"[TRANSFER] Лот куплен успешно!")
            return True

        # Проверяем типичные ошибки
        if "недостаточно" in page_text.lower() or "not enough" in page_text.lower():
            print(f"[TRANSFER] Недостаточно золота!")
            return False

        if "лот не найден" in page_text.lower() or "lot not found" in page_text.lower():
            print(f"[TRANSFER] Лот уже куплен кем-то!")
            return False

        # Если вернулись на аукцион после подтверждения - скорее всего успех
        current_url = self.client.current_url
        if "/auction" in current_url:
            print(f"[TRANSFER] Вернулись на аукцион после подтверждения - считаем успех")
            return True

        print(f"[TRANSFER] Неизвестный результат покупки")
        print(f"[TRANSFER] URL: {current_url}")
        print(f"[TRANSFER] Текст: {page_text[:300]}")

        return False

    def collect_mail(self) -> dict:
        """
        Собирает золото из почты.

        Returns:
            dict: {"gold": N, "silver": N}
        """
        mail_client = MailClient(self.client)
        stats = mail_client.check_and_collect()
        return {
            "gold": stats.get("gold", 0),
            "silver": stats.get("silver", 0)
        }


class GoldTransfer:
    """Главный класс для трансфера золота"""

    def __init__(self):
        self.config = TRANSFER_CONFIG
        self.log = []

    def get_all_balances(self) -> dict:
        """
        Получает балансы всех профилей.

        Returns:
            dict: {
                "char1": {"name": "nza", "gold": 150, "ruby": 500},
                ...
            }
        """
        import json

        profiles = get_profile_list()
        balances = {}

        for profile in profiles:
            # Читаем конфиг напрямую
            config_path = os.path.join(PROFILES_DIR, profile, "config.json")
            char_name = profile
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    char_name = config.get("username", config.get("login", profile))
                except Exception:
                    pass

            try:
                client = GoldTransferClient(profile)
                gold = client.get_gold_balance()
                ruby = client.get_ruby_count()

                balances[profile] = {
                    "name": char_name,
                    "gold": gold,
                    "ruby": ruby,
                    "can_transfer": gold > self.config["reserve_gold"]
                }
            except Exception as e:
                print(f"[TRANSFER] Ошибка получения баланса {profile}: {e}")
                balances[profile] = {
                    "name": char_name,
                    "gold": 0,
                    "ruby": 0,
                    "can_transfer": False,
                    "error": str(e)
                }

        return balances

    def transfer(self, main_profile: str, transfers: list) -> dict:
        """
        Выполняет трансфер золота от альтов к мейну.

        Args:
            main_profile: профиль-получатель
            transfers: список трансферов [{"profile": "char2", "amount": 40}, ...]

        Returns:
            dict: {
                "success": True,
                "total_received": 57,
                "details": [...]
            }
        """
        # Сбрасываем флаг остановки в начале
        clear_stop()

        results = {
            "success": True,
            "total_transferred": 0,
            "total_received": 0,
            "details": []
        }

        # Получаем рыночную цену рубина.
        # Приоритет: реальная минимальная с аукциона.
        # Fallback: bidGold/bidSilver из формы.
        main_client = GoldTransferClient(main_profile)

        def fetch_market_and_max():
            """Возвращает (market_price, max_per_ruby, source)."""
            am = main_client.get_actual_min_ruby_price_silver()
            if am > 0:
                src = "реальная минималка"
                mp = am
            else:
                mp = main_client.get_market_price()
                src = "форма (fallback)"
            if mp <= 0:
                return 0, 0, src
            raw = mp * self.config["price_multiplier"]
            sf = self.config.get("safety_factor", 1.0)
            return mp, int(raw * sf), src

        market_price, max_per_ruby, price_source = fetch_market_and_max()
        if market_price <= 0:
            results["success"] = False
            results["error"] = "Не удалось получить рыночную цену рубина"
            return results

        safety = self.config.get("safety_factor", 1.0)
        self._log(
            f"Рыночная цена ({price_source}): {market_price}с, "
            f"макс за рубин: {max_per_ruby}с = {max_per_ruby // 100}з "
            f"(x{self.config['price_multiplier']} * safety={safety})"
        )

        # Счётчик лотов — перечитываем рынок каждые refresh_market_every лотов.
        # Рынок волатилен (другие игроки выставляют дешевле, бот ставит дороже —
        # отбой). При фейле сразу обновляем минималку.
        refresh_every = self.config.get("refresh_market_every", 30)
        lot_counter = 0

        # Проверяем хватает ли рубинов у мейна для всех трансферов
        total_silver_needed = sum(t["amount"] * 100 for t in transfers)
        rubies_needed_total = (total_silver_needed + max_per_ruby - 1) // max_per_ruby
        ruby_count = main_client.get_ruby_count()

        self._log(f"Всего нужно: {total_silver_needed // 100}з = {rubies_needed_total} рубин(ов)")
        self._log(f"У мейна рубинов: {ruby_count}")

        if ruby_count < rubies_needed_total:
            max_can_transfer = ruby_count * max_per_ruby // 100
            self._log(f"⚠️ ВНИМАНИЕ: рубинов хватит только на {max_can_transfer}з!")
            results["warning"] = f"Рубинов ({ruby_count}) хватит только на {max_can_transfer}з из {total_silver_needed // 100}з"

        if ruby_count < 1:
            results["success"] = False
            results["error"] = f"У мейна нет рубинов! Закинь рубины на {main_profile}"
            return results

        for transfer in transfers:
            # Проверяем флаг остановки перед каждым альтом
            if is_stop_requested():
                self._log("Трансфер остановлен пользователем")
                results["stopped"] = True
                break

            alt_profile = transfer["profile"]
            amount_gold = transfer["amount"]
            amount_silver = amount_gold * 100  # конвертируем в серебро

            detail = {
                "profile": alt_profile,
                "requested": amount_gold,
                "transferred": 0,
                "status": "pending"
            }

            self._log(f"Начинаю трансфер от {alt_profile}: {amount_gold}з")

            transferred_silver = 0

            # Цикл: пока есть что передавать
            while amount_silver > 0:
                # Проверяем флаг остановки в каждой итерации
                if is_stop_requested():
                    self._log(f"Трансфер остановлен (передано {transferred_silver // 100}з от {alt_profile})")
                    detail["status"] = "stopped"
                    break

                # Проверяем сколько рубинов у мейна
                main_client = GoldTransferClient(main_profile)
                ruby_count = main_client.get_ruby_count()

                if ruby_count < 1:
                    self._log(f"У мейна нет рубинов!")
                    detail["status"] = "error"
                    detail["error"] = "У мейна нет рубинов"
                    break

                # Рынок волатилен — каждые refresh_every лотов перечитываем
                # минималку и пересчитываем max_per_ruby.
                if lot_counter > 0 and lot_counter % refresh_every == 0:
                    new_mp, new_max, src = fetch_market_and_max()
                    if new_mp > 0 and new_max != max_per_ruby:
                        self._log(
                            f"♻ Рынок обновился ({src}): {market_price}→{new_mp}с, "
                            f"макс за рубин: {max_per_ruby}→{new_max}с"
                        )
                        market_price, max_per_ruby = new_mp, new_max

                # Сервер похоже анти-флудит одинаковые лоты подряд.
                # Рандомизируем количество и цену в безопасных пределах.
                import random as _random
                target_amount = self.config.get("target_lot_amount", 10)
                max_lot_silver = self.config.get("max_lot_gold", 70) * 100

                # Рандомное количество: 8..12 (но не больше чем есть)
                rubies_to_use = min(_random.randint(8, 12), ruby_count)
                # Рандомизируем верхнюю границу: 0.7..1.0 от max_lot_silver
                # → лоты 49..70з. Sequence будет выглядеть менее монотонной.
                rand_cap = int(max_lot_silver * _random.uniform(0.7, 1.0))
                lot_price = min(amount_silver, rand_cap, rubies_to_use * max_per_ruby)

                # Если остаток к переводу совсем маленький — берём пропорционально.
                if amount_silver < target_amount * max_per_ruby:
                    rubies_to_use = max(1, (amount_silver + max_per_ruby - 1) // max_per_ruby)
                    rubies_to_use = min(rubies_to_use, ruby_count, target_amount)
                    lot_price = min(amount_silver, rubies_to_use * max_per_ruby)

                # Лёгкий рандомный sleep ДО создания лота — антифлуд имитация.
                time.sleep(_random.uniform(0.3, 1.0))

                self._log(f"Выставляю {rubies_to_use} рубин(ов) за {lot_price}с ({lot_price // 100}з)")
                lot_counter += 1

                # Мейн выставляет рубины
                if not main_client.create_lot(rubies_to_use, lot_price):
                    self._log(f"Не удалось создать лот")
                    # Рынок мог дёрнуться — сразу перечитываем минималку и
                    # пробуем тот же лот ещё раз с пересчитанной ценой.
                    self._log("♻ Перечитываю рынок и пробую снова...")
                    new_mp, new_max, src = fetch_market_and_max()
                    if new_mp > 0:
                        self._log(f"Новая минималка ({src}): {market_price}→{new_mp}с, макс/рубин: {max_per_ruby}→{new_max}с")
                        market_price, max_per_ruby = new_mp, new_max
                        # Пересчитываем лот с новой ценой (тот же target_amount).
                        rubies2 = min(target_amount, ruby_count)
                        lot_price2 = min(amount_silver, max_lot_silver, rubies2 * max_per_ruby)
                        if amount_silver < target_amount * max_per_ruby:
                            rubies2 = max(1, (amount_silver + max_per_ruby - 1) // max_per_ruby)
                            rubies2 = min(rubies2, ruby_count, target_amount)
                            lot_price2 = min(amount_silver, rubies2 * max_per_ruby)
                        self._log(f"Повтор: {rubies2} рубин(ов) за {lot_price2}с ({lot_price2 // 100}з)")
                        if main_client.create_lot(rubies2, lot_price2):
                            self._log("✓ Лот создан после перечитки рынка")
                            rubies_to_use = rubies2
                            lot_price = lot_price2
                            # Продолжаем как обычно — покупаем альтом
                        else:
                            # Анти-флуд: попробуем агрессивнее — пауза + сниженные цены
                            self._log("⏸ Ещё один fail. Жду 30с и пробую с пониженной ценой...")
                            time.sleep(30)
                            import random as _rnd
                            rubies3 = _rnd.randint(8, 10)
                            # Существенно более дешёвый лот (40-55з), чтобы прокатить
                            lot_price3 = min(
                                amount_silver,
                                _rnd.randint(40, 55) * 100,
                                rubies3 * max_per_ruby,
                            )
                            self._log(f"3-я попытка: {rubies3} рубин(ов) за {lot_price3}с ({lot_price3 // 100}з)")
                            if main_client.create_lot(rubies3, lot_price3):
                                self._log("✓ Лот создан после паузы")
                                rubies_to_use = rubies3
                                lot_price = lot_price3
                            else:
                                detail["status"] = "error"
                                detail["error"] = "Не удалось создать лот (3 попытки)"
                                if self.config.get("stop_on_first_error", False):
                                    self._log("⛔ STOP: ошибка после 3 попыток — останавливаю")
                                    request_stop()
                                break
                    else:
                        detail["status"] = "error"
                        detail["error"] = "Не удалось создать лот"
                        if self.config.get("stop_on_first_error", False):
                            self._log("⛔ STOP: первая ошибка создания лота — останавливаю весь трансфер")
                            request_stop()
                        break

                # Альт покупает по точной цене
                time.sleep(1)  # даём время на появление лота
                alt_client = GoldTransferClient(alt_profile)

                if not alt_client.find_and_buy_lot(lot_price):
                    self._log(f"Альт не смог купить лот")
                    detail["status"] = "partial"
                    detail["error"] = "Не удалось купить лот"
                    if self.config.get("stop_on_first_error", False):
                        self._log("⛔ STOP: первая ошибка покупки лота — останавливаю весь трансфер")
                        request_stop()
                    break

                # Успех - уменьшаем остаток
                amount_silver -= lot_price
                transferred_silver += lot_price

                # Помечаем лот перегона, чтобы приход денег НЕ считался доходом
                # в статистике продаж (record_sale сматчит по сумме).
                try:
                    from .sales_tracker import record_transfer
                    record_transfer(lot_price // 100, lot_price % 100, profile=main_profile)
                except Exception:
                    pass

                self._log(f"Передано {lot_price // 100}з, осталось {amount_silver // 100}з")

                time.sleep(0.5)

            # Итог по альту
            detail["transferred"] = transferred_silver // 100
            detail["received"] = int(transferred_silver * (1 - self.config["auction_fee"])) // 100

            if detail["status"] == "pending":
                detail["status"] = "ok"

            results["details"].append(detail)
            results["total_transferred"] += detail["transferred"]
            results["total_received"] += detail["received"]

        # Мейн собирает почту
        self._log("Мейн собирает почту...")
        main_client = GoldTransferClient(main_profile)
        mail_stats = main_client.collect_mail()
        results["mail_collected"] = mail_stats

        self._log(f"Итого: передано {results['total_transferred']}з, получено ~{results['total_received']}з")

        return results

    def _log(self, message: str):
        """Логирует сообщение"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        print(log_entry)
        self.log.append(log_entry)


def get_balances() -> dict:
    """Утилита для получения балансов всех профилей"""
    transfer = GoldTransfer()
    return transfer.get_all_balances()


def transfer_gold(main_profile: str, transfers: list) -> dict:
    """
    Утилита для выполнения трансфера.

    Args:
        main_profile: профиль-получатель
        transfers: [{"profile": "char2", "amount": 40}, ...]

    Returns:
        dict: результаты
    """
    transfer = GoldTransfer()
    return transfer.transfer(main_profile, transfers)
