# ============================================
# VMMO Event Dungeon (requests version)
# ============================================
# Ивенты:
# - Сталкер Адского Кладбища (HellStalker)
# - Новогодний: Логово Демона Мороза (NYLairFrost_2026)
# ============================================

import os
import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Используем логгер бота для записи в лог-файл
try:
    from requests_bot.logger import log_debug, log_info, log_error
except ImportError:
    # Fallback если запускается отдельно
    log_debug = log_info = log_error = print

from requests_bot.config import SCRIPT_DIR

BASE_URL = "https://vmmo.vten.ru"

# Кэш КД ивентов
_event_cooldown_until = 0
_ny_event_cooldown_until = 0

# КД NY ивента после победы (дефолт 6 часов, но парсится с сервера)
NY_EVENT_COOLDOWN_DEFAULT = 6 * 60 * 60  # 21600 секунд

# Дефолтный КД при ошибках парсинга (30 минут)
DEFAULT_FALLBACK_COOLDOWN = 1800

# Конфигурация ивент-данжей
# difficulty: impossible=Брутал, hard=Героик, normal=Нормал
EVENT_DUNGEONS = {
    "NYLairFrost_2026": {
        "name": "Логово Демона Мороза",
        "id": "dng:NYLairFrost_2026",
        "difficulty": "impossible",  # Брутал
        "url": "/dungeon/lobby/NYLairFrost_2026?1=impossible",
    },
    "SurtCaves": {
        "name": "Пещеры Сурта",
        "id": "dng:SurtCaves",
        "difficulty": "normal",  # Нормал
        "url": "/dungeon/lobby/SurtCaves?1=normal",
    },
    "DarknessComing": {
        "name": "Предвестник Тьмы",
        "id": "dng:DarknessComing",
        "difficulty": "impossible",  # Брутал
        "url": "/dungeon/lobby/DarknessComing?1=impossible",
    },
    "NYIceCastle_2026": {
        "name": "Ледяная Цитадель",
        "id": "dng:NYIceCastle_2026",
        "difficulty": "impossible",  # Брутал
        "url": "/dungeon/lobby/NYIceCastle_2026?1=impossible",
    },
}

# Кэш КД для каждого данжена
_event_cooldowns = {}


def set_ny_event_cooldown(client=None, seconds=None):
    """
    Устанавливает КД NY ивента (вызывать после победы).
    Если передан client - парсит реальное КД со страницы /dungeons.
    Иначе использует seconds или дефолт.
    """
    global _ny_event_cooldown_until

    # Пробуем получить реальное КД с сервера
    if client is not None and seconds is None:
        try:
            log_debug("[NY-EVENT] Парсим реальное КД с /dungeons...")
            client.get("/dungeons")
            html = client.current_page

            # Ищем блок с NYLairFrost_2026 и класс _cd
            dungeon_pattern = re.search(
                r'<div class="map-item-c map-item _dungeons([^"]*)"[^>]*>.*?title="dng:NYLairFrost_2026"',
                html, re.DOTALL
            )

            if dungeon_pattern and "_cd" in dungeon_pattern.group(1):
                block = dungeon_pattern.group(0)
                time_match = re.search(r'<span class="map-item-name">([^<]+)</span>', block)
                if time_match:
                    cd_text = time_match.group(1).strip()
                    seconds = parse_cooldown_to_seconds(cd_text)
                    log_info(f"[NY-EVENT] Реальное КД с сервера: {cd_text} ({seconds}s)")
        except Exception as e:
            log_error(f"[NY-EVENT] Ошибка парсинга КД: {e}")

    # Если не получили - используем дефолт
    if seconds is None:
        seconds = NY_EVENT_COOLDOWN_DEFAULT
        log_debug(f"[NY-EVENT] Используем дефолтное КД: {seconds // 3600}ч")

    _ny_event_cooldown_until = time.time() + seconds
    log_info(f"[NY-EVENT] КД установлен: {seconds // 3600}ч {(seconds % 3600) // 60}м")


def parse_cooldown_to_seconds(cd_text):
    """Парсит время КД из строки типа '33 мин 58 сек' или '1 ч 5 мин'"""
    seconds = 0

    h_match = re.search(r'(\d+)\s*ч', cd_text)
    if h_match:
        seconds += int(h_match.group(1)) * 3600

    m_match = re.search(r'(\d+)\s*мин', cd_text)
    if m_match:
        seconds += int(m_match.group(1)) * 60

    s_match = re.search(r'(\d+)\s*сек', cd_text)
    if s_match:
        seconds += int(s_match.group(1))

    return seconds


class EventDungeonClient:
    """Клиент для ивентового данжена"""

    def __init__(self, client):
        self.client = client
        self.event_cooldown_until = 0

    def check_event_available(self):
        """
        Проверяет, доступен ли ивент "Сталкер Адского Кладбища".
        Возвращает (available: bool, widget_url: str или None)
        """
        print("[EVENT] Проверяю доступность ивента...")

        # Переходим в город
        resp = self.client.get("/city")
        soup = self.client.soup()
        if not soup:
            return False, None

        # Ищем виджет ивента HellStalker
        event_widget = soup.select_one('a.city-menu-l-link[href*="HellStalker"]')
        if not event_widget:
            print("[EVENT] Виджет ивента не найден")
            return False, None

        # Проверяем таймер
        timer = event_widget.select_one(".city-menu-timer")
        if timer:
            timer_text = timer.get_text(strip=True)
            print(f"[EVENT] Ивент 'Сталкер' доступен! Осталось: {timer_text}")

        href = event_widget.get("href")
        # Защита от javascript: URLs
        if href and href.startswith("javascript"):
            href = None
        event_url = urljoin(BASE_URL, href) if href else None

        return True, event_url

    def enter_event_page(self, event_url=None):
        """
        Переходит на страницу ивента.
        Возвращает True если успешно.
        """
        if not event_url:
            # Пробуем найти виджет
            available, event_url = self.check_event_available()
            if not available or not event_url:
                return False

        print(f"[EVENT] Перехожу на страницу ивента...")
        resp = self.client.get(event_url)
        return resp.status_code == 200

    def find_dungeon_button(self):
        """
        Находит кнопку данжена "Перевал Мертвецов" (EventCemetery).
        Возвращает URL или None.
        """
        soup = self.client.soup()
        if not soup:
            return None

        # Ищем виджет данжена EventCemetery
        dungeon_btn = soup.select_one('a.event-map-widget[href*="EventCemetery"]')
        if not dungeon_btn:
            # Пробуем другие варианты
            dungeon_btn = soup.select_one('a[href*="EventCemetery"]')

        if dungeon_btn:
            href = dungeon_btn.get("href")
            # Фильтруем javascript ссылки
            if href and not href.startswith("javascript") and href != "#":
                return urljoin(self.client.current_url, href)

        return None

    def check_dungeon_cooldown(self):
        """
        Проверяет КД данжена на текущей странице.
        Возвращает (on_cooldown: bool, cd_seconds: int)
        """
        html = self.client.current_page

        # Ищем текст о КД
        if "Ты сможешь войти через" in html:
            cd_match = re.search(r"войти через\s+(.+?)\.", html)
            if cd_match:
                cd_text = cd_match.group(1)
                cd_seconds = parse_cooldown_to_seconds(cd_text)
                print(f"[EVENT] Данжен на КД: {cd_text} (~{cd_seconds}с)")
                return True, cd_seconds

        return False, 0

    def find_enter_button(self):
        """Находит кнопку 'Войти' на странице данжена"""
        soup = self.client.soup()
        if not soup:
            return None

        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if text == "Войти":
                href = btn.get("href")
                # Фильтруем javascript ссылки
                if href and not href.startswith("javascript") and href != "#":
                    return urljoin(self.client.current_url, href)

        return None

    def find_start_combat_button(self):
        """Находит кнопку 'Начать бой!' на странице лобби"""
        soup = self.client.soup()
        if not soup:
            return None

        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if "Начать бой" in text:
                href = btn.get("href")
                # Фильтруем javascript ссылки
                if href and not href.startswith("javascript") and href != "#":
                    return urljoin(self.client.current_url, href)

        # Пробуем Wicket AJAX
        wicket_match = re.search(r'"u":"([^"]*linkStartCombat[^"]*)"', self.client.current_page)
        if wicket_match:
            return wicket_match.group(1)

        return None

    def enter_event_dungeon(self):
        """
        Полный flow входа в ивентовый данжен.
        Возвращает: "entered", "on_cooldown", "not_available", "error"
        """
        global _event_cooldown_until

        # Проверяем кэш КД
        now = time.time()
        if now < _event_cooldown_until:
            remaining = int(_event_cooldown_until - now)
            print(f"[EVENT] Ивент на КД (кэш), осталось ~{remaining // 60}м")
            return "on_cooldown", remaining

        # Проверяем и ремонтируем снаряжение перед входом
        try:
            if self.client.repair_equipment():
                print("[EVENT] Снаряжение отремонтировано перед ивентом")
        except Exception as e:
            print(f"[EVENT] Ошибка проверки ремонта: {e}")

        # 1. Проверяем доступность ивента
        available, event_url = self.check_event_available()
        if not available:
            return "not_available", 0

        # 2. Переходим на страницу ивента
        if not self.enter_event_page(event_url):
            return "error", 0

        time.sleep(1)

        # 3. Ищем кнопку данжена
        dungeon_url = self.find_dungeon_button()
        if not dungeon_url:
            print("[EVENT] Кнопка данжена не найдена")
            return "error", 0

        print(f"[EVENT] Нажимаю на 'Перевал Мертвецов'...")
        self.client.get(dungeon_url)
        time.sleep(1)

        # 4. Проверяем КД
        on_cooldown, cd_seconds = self.check_dungeon_cooldown()
        if on_cooldown:
            _event_cooldown_until = now + cd_seconds
            return "on_cooldown", cd_seconds

        # 5. Нажимаем "Войти"
        enter_url = self.find_enter_button()
        if not enter_url:
            print("[EVENT] Кнопка 'Войти' не найдена")
            return "error", 0

        print("[EVENT] Нажимаю 'Войти'...")
        self.client.get(enter_url)
        time.sleep(2)

        # 6. Нажимаем "Начать бой!"
        start_url = self.find_start_combat_button()
        if not start_url:
            print("[EVENT] Кнопка 'Начать бой' не найдена")
            return "error", 0

        print("[EVENT] Нажимаю 'Начать бой!'...")
        self.client.get(start_url)
        time.sleep(2)

        # 7. Проверяем что попали в бой
        if "/combat" in self.client.current_url:
            print("[EVENT] Успешно вошли в бой!")
            return "entered", 0

        print(f"[EVENT] Неожиданный URL: {self.client.current_url}")
        return "error", 0


class NYEventDungeonClient:
    """Клиент для новогоднего ивента - Логово Демона Мороза"""

    DUNGEON_ID = "dng:NYLairFrost_2026"
    # Сложности в URL: impossible=Брутал, hard=Героик, normal=Нормал
    LANDING_URL = "/dungeon/lobby/NYLairFrost_2026?1=impossible"

    def __init__(self, client):
        self.client = client
        self.cooldown_until = 0

    def check_dungeon_cooldown(self):
        """
        Проверяет КД данжена через страницу /dungeons.
        Ивенты на вкладке tier-event.
        Возвращает (on_cooldown: bool, cd_seconds: int)
        """
        global _ny_event_cooldown_until

        log_debug("[NY-EVENT] check_dungeon_cooldown() вызван")

        # Проверяем кэш
        now = time.time()
        if now < _ny_event_cooldown_until:
            remaining = int(_ny_event_cooldown_until - now)
            log_debug(f"[NY-EVENT] Логово Демона Мороза на КД (кэш): {remaining // 60}м")
            return True, remaining

        # Загружаем страницу данжей
        log_debug("[NY-EVENT] Загружаю /dungeons...")
        self.client.get("/dungeons")
        html = self.client.current_page
        log_debug(f"[NY-EVENT] Получено {len(html)} байт HTML")

        # Ищем блок с NYLairFrost_2026
        # Формат: <div class="map-item-c map-item _dungeons _cd">...<div title="dng:NYLairFrost_2026"
        # Если есть класс _cd - значит на КД
        # Время в <span class="map-item-name">2ч 07м</span>

        # Проверяем есть ли данжен на странице
        if 'title="dng:NYLairFrost_2026"' not in html:
            log_debug("[NY-EVENT] Данжен NYLairFrost_2026 не найден на странице /dungeons")
            # Это нормально - ивент может быть недоступен. Пробуем идти напрямую
            return False, 0

        log_debug("[NY-EVENT] Данжен NYLairFrost_2026 найден на странице")

        # Ищем блок с этим данженом и проверяем _cd
        # Паттерн: от map-item-c до title="dng:NYLairFrost_2026"
        dungeon_pattern = re.search(
            r'<div class="map-item-c map-item _dungeons([^"]*)"[^>]*>.*?title="dng:NYLairFrost_2026"',
            html, re.DOTALL
        )

        if dungeon_pattern:
            classes = dungeon_pattern.group(1)
            log_debug(f"[NY-EVENT] Классы блока: '{classes}'")
            if "_cd" in classes:
                # На КД - ищем время
                block = dungeon_pattern.group(0)
                time_match = re.search(r'<span class="map-item-name">([^<]+)</span>', block)
                if time_match:
                    cd_text = time_match.group(1).strip()
                    cd_seconds = parse_cooldown_to_seconds(cd_text)
                    log_debug(f"[NY-EVENT] Логово Демона Мороза на КД: {cd_text}")
                    _ny_event_cooldown_until = now + cd_seconds
                    return True, cd_seconds
                else:
                    # КД есть, но время не найдено - ставим 30 мин
                    log_debug("[NY-EVENT] Логово Демона Мороза на КД (время неизвестно)")
                    _ny_event_cooldown_until = now + DEFAULT_FALLBACK_COOLDOWN
                    return True, DEFAULT_FALLBACK_COOLDOWN
        else:
            log_debug("[NY-EVENT] Regex не нашёл блок с данженом")

        log_info("[NY-EVENT] Логово Демона Мороза готово!")
        return False, 0

    def enter_dungeon(self):
        """
        Входит в Логово Демона Мороза.
        Возвращает: "entered", "on_cooldown", "error"
        """
        global _ny_event_cooldown_until

        log_debug("[NY-EVENT] enter_dungeon() вызван")

        # Проверяем КД
        try:
            on_cd, cd_sec = self.check_dungeon_cooldown()
            if on_cd:
                return "on_cooldown", cd_sec
        except Exception as e:
            log_error(f"[NY-EVENT] Ошибка в check_dungeon_cooldown: {e}")
            import traceback
            traceback.print_exc()
            return "error", 0

        # Проверяем и ремонтируем снаряжение
        try:
            if self.client.repair_equipment():
                log_debug("[NY-EVENT] Снаряжение отремонтировано")
        except Exception as e:
            log_error(f"[NY-EVENT] Ошибка ремонта: {e}")

        # Переходим в lobby напрямую (КД проверяется по ответу)
        log_info("[NY-EVENT] Захожу в Логово Демона Мороза...")
        resp = self.client.get(self.LANDING_URL)
        current_url = self.client.current_url
        log_debug(f"[NY-EVENT] URL после перехода: {current_url}")

        # Проверяем на КД - если редирект на /city или /dungeons
        if "/city" in current_url or "/dungeons" in current_url:
            # Проверяем HTML на сообщение о КД
            html = self.client.current_page
            if "cooldown" in html.lower() or "перезарядк" in html.lower() or "недоступ" in html.lower():
                log_debug("[NY-EVENT] Данжен на КД (по редиректу)")
                _ny_event_cooldown_until = time.time() + DEFAULT_FALLBACK_COOLDOWN
                return "on_cooldown", DEFAULT_FALLBACK_COOLDOWN
            log_debug(f"[NY-EVENT] Редирект на {current_url}, возможно КД")
            return "on_cooldown", DEFAULT_FALLBACK_COOLDOWN

        # Если попали на landing - нужно обработать награды и войти
        if "/landing/" in current_url:
            log_debug("[NY-EVENT] Попали на landing page...")
            soup = self.client.soup()

            # Собираем все кнопки для логирования
            all_btns = {}
            for btn in soup.select("a.go-btn"):
                text = btn.get_text(strip=True)
                href = btn.get("href", "")
                if text and href:
                    all_btns[text] = href
                log_debug(f"[NY-EVENT] Кнопка: '{text}' -> {href[:50] if href else 'None'}...")

            # Сначала забираем награду если есть
            if "Забрать" in all_btns:
                href = all_btns["Забрать"]
                if href and not href.startswith("javascript"):
                    log_debug("[NY-EVENT] Забираю награду...")
                    self.client.get(urljoin(current_url, href))
                    time.sleep(1)
                    # Обновляем страницу
                    soup = self.client.soup()
                    current_url = self.client.current_url

            # Открываем сундук если есть (кнопка начинается с "Открыть")
            for text, href in all_btns.items():
                if text.startswith("Открыть") and href and not href.startswith("javascript"):
                    log_debug(f"[NY-EVENT] Открываю сундук: {text}...")
                    self.client.get(urljoin(current_url, href))
                    time.sleep(1)
                    break

            # Ищем кнопку "Войти", "Создать группу" или "Повторить"
            enter_btn = None
            soup = self.client.soup()  # Обновляем после возможных действий
            for btn in soup.select("a.go-btn"):
                text = btn.get_text(strip=True)
                href = btn.get("href", "")
                if text in ["Войти", "Создать группу", "Повторить"] and href and not href.startswith("javascript"):
                    enter_btn = urljoin(self.client.current_url, href)
                    log_debug(f"[NY-EVENT] Нашли кнопку: '{text}'")
                    break

            if not enter_btn:
                # Пробуем через Wicket
                match = re.search(r'"u":"([^"]*(?:enterLink|createPartyLink|repeatLink)[^"]*)"', self.client.current_page)
                if match:
                    enter_btn = match.group(1)

            if enter_btn:
                log_debug(f"[NY-EVENT] Нажимаю кнопку входа на landing: {enter_btn[:60]}...")
                self.client.get(enter_btn)
                time.sleep(1)
                current_url = self.client.current_url
                log_debug(f"[NY-EVENT] URL после нажатия: {current_url}")
            else:
                log_error("[NY-EVENT] Кнопка входа на landing не найдена")
                return "error", 0

        if "/lobby/" not in current_url and "/standby/" not in current_url:
            log_error(f"[NY-EVENT] Не удалось зайти в lobby: {current_url}")
            return "error", 0

        log_debug(f"[NY-EVENT] В lobby! URL: {current_url}")

        # Ищем кнопку входа в lobby
        soup = self.client.soup()
        enter_url = None

        # Логируем все кнопки go-btn для отладки
        go_btns = soup.select("a.go-btn")
        log_debug(f"[NY-EVENT] Найдено {len(go_btns)} кнопок go-btn")
        for btn in go_btns:
            text = btn.get_text(strip=True)
            href = btn.get("href", "")[:60] if btn.get("href") else "None"
            log_debug(f"[NY-EVENT] go-btn: '{text}' -> {href}")

        # Ищем кнопку "Войти" или "Начать бой" по тексту
        for btn in go_btns:
            text = btn.get_text(strip=True)
            href = btn.get("href", "")
            if text in ["Войти", "Начать бой!", "Начать бой"] and href and not href.startswith("javascript"):
                enter_url = urljoin(self.client.current_url, href)
                log_debug(f"[NY-EVENT] Нашли кнопку по тексту: '{text}'")
                break

        # Если не нашли по тексту - ищем ILinkListener
        if not enter_url:
            for link in soup.select("a"):
                href = link.get("href", "")
                if "ILinkListener" in href and ("enterLink" in href or "createPartyOrEnterLink" in href or "linkStartCombat" in href):
                    enter_url = urljoin(self.client.current_url, href)
                    log_debug(f"[NY-EVENT] Нашли ILinkListener: {href[:60]}")
                    break

        if not enter_url:
            # Пробуем через Wicket AJAX
            match = re.search(r'"u":"([^"]*(?:enterLink|createPartyOrEnterLink|linkStartCombat)[^"]*)"', self.client.current_page)
            if match:
                enter_url = match.group(1)
                log_debug(f"[NY-EVENT] Нашли Wicket AJAX: {enter_url[:60]}")

        if not enter_url:
            log_error("[NY-EVENT] Кнопка входа не найдена в lobby")
            # Сохраним HTML для отладки
            log_debug(f"[NY-EVENT] HTML length: {len(self.client.current_page)}")
            return "error", 0

        log_debug("[NY-EVENT] Вхожу в данжен...")
        self.client.get(enter_url)
        time.sleep(1)

        # Проверяем lobby/standby
        if "/lobby/" in self.client.current_url or "/standby/" in self.client.current_url:
            # Ищем кнопку "Начать бой"
            match = re.search(r'"u":"([^"]*linkStartCombat[^"]*)"', self.client.current_page)
            if match:
                log_debug("[NY-EVENT] Начинаю бой...")
                self.client.get(match.group(1))
                time.sleep(1)

        # Проверяем что в бою
        if "/combat" in self.client.current_url:
            log_info("[NY-EVENT] Успешно вошли в бой!")
            return "entered", 0

        log_error(f"[NY-EVENT] Неожиданный URL: {self.client.current_url}")
        return "error", 0


def try_ny_event_dungeon(client):
    """
    Пробует войти в новогодний данжен Логово Демона Мороза.
    Возвращает: "entered", "on_cooldown", "error"
    """
    log_debug("[NY-EVENT] try_ny_event_dungeon() вызван")
    try:
        ny_client = NYEventDungeonClient(client)
        return ny_client.enter_dungeon()
    except Exception as e:
        log_error(f"[NY-EVENT] Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        return "error", 0


class GenericEventDungeonClient:
    """Универсальный клиент для ивент-данжей"""

    def __init__(self, client, dungeon_key):
        """
        Args:
            client: VMMOClient
            dungeon_key: Ключ из EVENT_DUNGEONS (например "SurtCaves")
        """
        self.client = client
        self.dungeon_key = dungeon_key
        self.config = EVENT_DUNGEONS.get(dungeon_key)
        if not self.config:
            raise ValueError(f"Unknown dungeon: {dungeon_key}")

        self.dungeon_id = self.config["id"]
        self.dungeon_name = self.config["name"]
        self.landing_url = self.config["url"]

    def check_cooldown(self):
        """
        Проверяет КД данжена.
        Возвращает (on_cooldown: bool, cd_seconds: int)
        """
        global _event_cooldowns

        log_debug(f"[EVENT] Проверяю КД для {self.dungeon_name}...")

        # Проверяем кэш
        now = time.time()
        cached_until = _event_cooldowns.get(self.dungeon_key, 0)
        if now < cached_until:
            remaining = int(cached_until - now)
            log_debug(f"[EVENT] {self.dungeon_name} на КД (кэш): {remaining // 60}м")
            return True, remaining

        # Загружаем страницу данжей (ивент-вкладка загружается автоматически через JS,
        # но в HTML все данжены должны быть)
        self.client.get("/dungeons")
        html = self.client.current_page

        # Ищем блок с нашим данженом
        if f'title="{self.dungeon_id}"' not in html:
            log_debug(f"[EVENT] Данжен {self.dungeon_id} не найден на странице, считаем на КД")
            return True, 300  # Вернём 5 минут КД по умолчанию

        # Ищем блок с классом _cd
        pattern = rf'<div class="map-item-c map-item _dungeons([^"]*)"[^>]*>.*?title="{self.dungeon_id}"'
        dungeon_match = re.search(pattern, html, re.DOTALL)

        if dungeon_match and "_cd" in dungeon_match.group(1):
            # На КД - ищем время
            block = dungeon_match.group(0)
            time_match = re.search(r'<span class="map-item-name">([^<]+)</span>', block)
            if time_match:
                cd_text = time_match.group(1).strip()
                cd_seconds = parse_cooldown_to_seconds(cd_text)
                log_debug(f"[EVENT] {self.dungeon_name} на КД: {cd_text}")
                _event_cooldowns[self.dungeon_key] = now + cd_seconds
                return True, cd_seconds
            else:
                log_debug(f"[EVENT] {self.dungeon_name} на КД (время неизвестно)")
                _event_cooldowns[self.dungeon_key] = now + DEFAULT_FALLBACK_COOLDOWN
                return True, DEFAULT_FALLBACK_COOLDOWN

        log_info(f"[EVENT] {self.dungeon_name} готов!")
        return False, 0

    def enter_dungeon(self):
        """
        Входит в данжен.
        Возвращает: ("entered", 0), ("on_cooldown", seconds), ("error", 0)
        """
        global _event_cooldowns

        log_debug(f"[EVENT] Вход в {self.dungeon_name}...")

        # Проверяем КД
        on_cd, cd_sec = self.check_cooldown()
        if on_cd:
            return "on_cooldown", cd_sec

        # Ремонтируем снаряжение
        try:
            if self.client.repair_equipment():
                log_debug(f"[EVENT] Снаряжение отремонтировано")
        except Exception as e:
            log_debug(f"[EVENT] Ошибка ремонта: {e}")

        # Переходим в lobby
        log_info(f"[EVENT] Захожу в {self.dungeon_name}...")
        self.client.get(self.landing_url)
        current_url = self.client.current_url
        log_debug(f"[EVENT] URL: {current_url}")

        # Редирект на город = КД
        if "/city" in current_url or "/dungeons" in current_url:
            log_debug(f"[EVENT] Редирект - возможно КД")
            _event_cooldowns[self.dungeon_key] = time.time() + DEFAULT_FALLBACK_COOLDOWN
            return "on_cooldown", DEFAULT_FALLBACK_COOLDOWN

        # Обработка landing page
        if "/landing/" in current_url:
            log_debug(f"[EVENT] На landing page...")
            soup = self.client.soup()

            # Собираем награды если есть
            for btn in soup.select("a.go-btn"):
                text = btn.get_text(strip=True)
                href = btn.get("href", "")
                if text == "Забрать" and href and not href.startswith("javascript"):
                    log_debug(f"[EVENT] Забираю награду...")
                    self.client.get(urljoin(current_url, href))
                    time.sleep(1)
                    soup = self.client.soup()
                    break

            # Открываем сундук если есть
            for btn in soup.select("a.go-btn"):
                text = btn.get_text(strip=True)
                href = btn.get("href", "")
                if text.startswith("Открыть") and href and not href.startswith("javascript"):
                    log_debug(f"[EVENT] Открываю: {text}")
                    self.client.get(urljoin(self.client.current_url, href))
                    time.sleep(1)
                    break

            # Ищем кнопку входа
            enter_btn = None
            soup = self.client.soup()
            for btn in soup.select("a.go-btn"):
                text = btn.get_text(strip=True)
                href = btn.get("href", "")
                if text in ["Войти", "Создать группу", "Повторить"] and href and not href.startswith("javascript"):
                    enter_btn = urljoin(self.client.current_url, href)
                    log_debug(f"[EVENT] Кнопка: '{text}'")
                    break

            if not enter_btn:
                match = re.search(r'"u":"([^"]*(?:enterLink|createPartyLink|repeatLink)[^"]*)"', self.client.current_page)
                if match:
                    enter_btn = match.group(1)

            if enter_btn:
                self.client.get(enter_btn)
                time.sleep(1)
                current_url = self.client.current_url
            else:
                log_error(f"[EVENT] Кнопка входа не найдена на landing")
                return "error", 0

        # Проверяем что в lobby
        if "/lobby/" not in current_url and "/standby/" not in current_url:
            log_error(f"[EVENT] Не в lobby: {current_url}")
            return "error", 0

        # Ищем кнопку входа в lobby
        soup = self.client.soup()
        enter_url = None

        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            href = btn.get("href", "")
            if text in ["Войти", "Начать бой!", "Начать бой"] and href and not href.startswith("javascript"):
                enter_url = urljoin(self.client.current_url, href)
                break

        if not enter_url:
            for link in soup.select("a"):
                href = link.get("href", "")
                if "ILinkListener" in href and ("enterLink" in href or "createPartyOrEnterLink" in href or "linkStartCombat" in href):
                    enter_url = urljoin(self.client.current_url, href)
                    break

        if not enter_url:
            match = re.search(r'"u":"([^"]*(?:enterLink|createPartyOrEnterLink|linkStartCombat)[^"]*)"', self.client.current_page)
            if match:
                enter_url = match.group(1)

        if not enter_url:
            log_error(f"[EVENT] Кнопка входа не найдена в lobby")
            return "error", 0

        self.client.get(enter_url)
        time.sleep(1)

        # Начинаем бой если нужно
        if "/lobby/" in self.client.current_url or "/standby/" in self.client.current_url:
            match = re.search(r'"u":"([^"]*linkStartCombat[^"]*)"', self.client.current_page)
            if match:
                log_debug(f"[EVENT] Начинаю бой...")
                self.client.get(match.group(1))
                time.sleep(1)

        if "/combat" in self.client.current_url:
            log_info(f"[EVENT] Вошли в {self.dungeon_name}!")
            return "entered", 0

        log_error(f"[EVENT] Неожиданный URL: {self.client.current_url}")
        return "error", 0


def set_event_cooldown(dungeon_key, client=None, seconds=None):
    """
    Устанавливает КД для ивент-данжена после победы.
    Парсит реальное КД с сервера если передан client.
    """
    global _event_cooldowns

    config = EVENT_DUNGEONS.get(dungeon_key)
    if not config:
        return

    dungeon_id = config["id"]
    dungeon_name = config["name"]

    # Парсим реальное КД
    if client is not None and seconds is None:
        try:
            log_debug(f"[EVENT] Парсим КД для {dungeon_name}...")
            client.get("/dungeons")
            html = client.current_page

            pattern = rf'<div class="map-item-c map-item _dungeons([^"]*)"[^>]*>.*?title="{dungeon_id}"'
            match = re.search(pattern, html, re.DOTALL)

            if match and "_cd" in match.group(1):
                block = match.group(0)
                time_match = re.search(r'<span class="map-item-name">([^<]+)</span>', block)
                if time_match:
                    cd_text = time_match.group(1).strip()
                    seconds = parse_cooldown_to_seconds(cd_text)
                    log_info(f"[EVENT] {dungeon_name} КД: {cd_text}")
        except Exception as e:
            log_error(f"[EVENT] Ошибка парсинга КД: {e}")

    if seconds is None:
        seconds = NY_EVENT_COOLDOWN_DEFAULT

    _event_cooldowns[dungeon_key] = time.time() + seconds
    log_info(f"[EVENT] {dungeon_name} КД установлен: {seconds // 3600}ч {(seconds % 3600) // 60}м")


def try_event_dungeon_generic(client, dungeon_key):
    """
    Пробует войти в указанный ивент-данжен.
    Returns: ("entered", 0), ("on_cooldown", seconds), ("error", 0)
    """
    try:
        dungeon_client = GenericEventDungeonClient(client, dungeon_key)
        return dungeon_client.enter_dungeon()
    except Exception as e:
        log_error(f"[EVENT] Ошибка {dungeon_key}: {e}")
        import traceback
        traceback.print_exc()
        return "error", 0


def get_available_event_dungeons():
    """Возвращает список ключей доступных ивент-данжей"""
    return list(EVENT_DUNGEONS.keys())


class EquipmentClient:
    """Клиент для экипировки предметов"""

    def __init__(self, client):
        self.client = client

    def find_item_in_backpack(self, item_name):
        """
        Ищет предмет в рюкзаке по имени.
        Возвращает URL предмета или None.
        """
        resp = self.client.get("/user/rack")
        soup = self.client.soup()
        if not soup:
            return None

        # Ищем предмет по названию
        for item_link in soup.select("a[href*='item']"):
            text = item_link.get_text(strip=True)
            if item_name.lower() in text.lower():
                href = item_link.get("href")
                if href and not href.startswith("javascript"):
                    return urljoin(BASE_URL, href)

        return None

    def equip_item(self, item_name):
        """
        Надевает предмет по имени.
        Возвращает True если успешно или предмет уже надет.
        """
        print(f"[EQUIP] Ищу '{item_name}' в рюкзаке...")

        item_url = self.find_item_in_backpack(item_name)
        if not item_url:
            print(f"[EQUIP] {item_name} не найден (возможно уже надет)")
            return True

        # Открываем страницу предмета
        self.client.get(item_url)
        soup = self.client.soup()
        if not soup:
            return False

        # Ищем кнопку "Надеть"
        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if text == "Надеть":
                href = btn.get("href")
                if href and not href.startswith("javascript"):
                    equip_url = urljoin(self.client.current_url, href)
                    print(f"[EQUIP] Надеваю {item_name}...")
                    self.client.get(equip_url)
                    print(f"[EQUIP] {item_name} надет!")
                    return True

        print(f"[EQUIP] Кнопка 'Надеть' не найдена для {item_name}")
        return True  # Продолжаем - возможно уже надет

    def equip_stalker_seal(self):
        """Надевает Печать Сталкера для ивента"""
        return self.equip_item("Печать Сталкера")

    def equip_tikuan_crystal(self):
        """Надевает Треснутый Кристалл Тикуана для обычных данженов"""
        return self.equip_item("Треснутый Кристалл Тикуана")


def try_event_dungeon(client):
    """
    Пробует войти в ивентовый данжен.
    Возвращает: "entered", "on_cooldown", "not_available", "error"
    """
    event_client = EventDungeonClient(client)
    equip_client = EquipmentClient(client)

    # Проверяем доступность
    available, _ = event_client.check_event_available()
    if not available:
        return "not_available", 0

    # Надеваем Печать Сталкера
    equip_client.equip_stalker_seal()

    # Пробуем войти
    result, cd_seconds = event_client.enter_event_dungeon()

    if result == "on_cooldown":
        # Надеваем Кристалл Тикуана для обычных данженов
        print("[EVENT] Ивент на КД - надеваю Кристалл Тикуана")
        equip_client.equip_tikuan_crystal()

    return result, cd_seconds


def test_event():
    """Тест модуля ивента"""
    from requests_bot.client import VMMOClient

    print("=" * 50)
    print("VMMO Event Dungeon Test")
    print("=" * 50)

    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            return

    # Тестируем
    event_client = EventDungeonClient(client)

    # 1. Проверяем доступность
    available, event_url = event_client.check_event_available()
    print(f"\n[RESULT] Ивент доступен: {available}")
    if event_url:
        print(f"[RESULT] URL: {event_url}")

    if not available:
        print("[INFO] Ивент не активен - тест завершён")
        return

    # 2. Переходим на страницу ивента
    print("\n[*] Перехожу на страницу ивента...")
    event_client.enter_event_page(event_url)

    # 3. Ищем данжен
    dungeon_url = event_client.find_dungeon_button()
    print(f"[RESULT] Кнопка данжена: {dungeon_url}")

    if dungeon_url:
        print("\n[*] Нажимаю на данжен...")
        client.get(dungeon_url)

        # 4. Проверяем КД
        on_cd, cd_sec = event_client.check_dungeon_cooldown()
        print(f"[RESULT] На КД: {on_cd}, секунд: {cd_sec}")

        if not on_cd:
            # 5. Ищем кнопку входа
            enter_url = event_client.find_enter_button()
            print(f"[RESULT] Кнопка 'Войти': {enter_url}")


if __name__ == "__main__":
    test_event()
