# ============================================
# VMMO Event Dungeon (requests version)
# ============================================
# Ивент "Сталкер Адского Кладбища"
# ============================================

import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://vmmo.vten.ru"

# Кэш КД ивента
_event_cooldown_until = 0


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
