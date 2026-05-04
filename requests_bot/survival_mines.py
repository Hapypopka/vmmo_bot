# ============================================
# VMMO Survival Mines (Заброшенная Шахта)
# ============================================
# Бой в режиме выживания до 31 волны
# ============================================

import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from requests_bot.config import BASE_URL, get_skill_cooldowns, GCD, LOOT_COLLECT_INTERVAL
from requests_bot.parsers import parse_ajax_urls

# URLs
SURVIVALS_URL = f"{BASE_URL}/survivals"
SURVIVAL_MINES_LOBBY_URL = f"{BASE_URL}/dungeon/lobby/survMines"
GUILD_BONUS_URL = f"{BASE_URL}/guild/bonus/10211"
CITY_URL = f"{BASE_URL}/city"

# Настройки
MAX_WAVE = 31  # На 31 волне выходим


class SurvivalMinesClient:
    """Клиент для Заброшенной Шахты (Survival Mines)"""

    def __init__(self, client):
        self.client = client
        self.skill_cooldowns = {}  # {pos: last_use_time}
        self.last_gcd_time = 0

        # Для сбора лута через refresher
        self.refresher_url = None
        self.loot_take_url = None
        self.collected_loot = set()
        self.attack_count = 0

    def _setup_refresher_url(self):
        """Настраивает refresher URL для сбора лута"""
        html = self.client.current_page
        if not html:
            return

        # Ищем page_id
        page_id_match = re.search(r'ptxPageId\s*=\s*(\d+)', html)
        if not page_id_match:
            print("[MINES] page_id не найден для refresher")
            return

        page_id = page_id_match.group(1)

        # Формируем refresher URL
        # Формат: /dungeon/combat/survMines?{pageId}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher
        self.refresher_url = f"{BASE_URL}/dungeon/combat/survMines?{page_id}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher"

        # Ищем loot_take_url
        loot_match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", html)
        if loot_match:
            self.loot_take_url = loot_match.group(1)

        print(f"[MINES] Refresher настроен: page_id={page_id}")
        self.collected_loot.clear()
        self.attack_count = 0

    def _collect_loot_via_refresher(self):
        """Собирает лут через refresher endpoint"""
        if not self.refresher_url:
            return 0

        try:
            resp = self.client.session.get(self.refresher_url, timeout=10)
            if resp.status_code != 200:
                return 0

            response_text = resp.text

            # Обновляем loot_take_url если пришёл новый
            loot_url_match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", response_text)
            if loot_url_match:
                self.loot_take_url = loot_url_match.group(1)

            # Ищем dropLoot события
            if "dropLoot" not in response_text:
                return 0

            # Парсим ID лута
            loot_ids = re.findall(r"id:\s*'(\d+)'", response_text)

            if not loot_ids or not self.loot_take_url:
                return 0

            collected = 0
            for loot_id in loot_ids:
                if loot_id not in self.collected_loot:
                    take_url = self.loot_take_url + loot_id
                    try:
                        self.client.session.get(take_url, timeout=5)
                        self.collected_loot.add(loot_id)
                        collected += 1
                        print(f"[MINES LOOT] Собран: {loot_id}")
                    except Exception as e:
                        print(f"[MINES LOOT ERROR] {e}")

            return collected

        except Exception as e:
            print(f"[MINES REFRESHER ERROR] {e}")
            return 0

    def get_character_level(self):
        """Получает текущий уровень персонажа"""
        resp = self.client.get(f"{BASE_URL}/user")
        if not resp:
            return 0

        soup = self.client.soup()
        if not soup:
            return 0

        # Ищем уровень в меню: <span class="main-menu-lvl">47 ур.</span>
        lvl_span = soup.select_one(".main-menu-lvl")
        if lvl_span:
            text = lvl_span.get_text(strip=True)  # "47 ур."
            import re
            match = re.search(r'(\d+)', text)
            if match:
                return int(match.group(1))

        # Fallback: ищем в заголовке "Happypoq , 47 ур."
        title = soup.select_one(".page-title-text")
        if title:
            text = title.get_text()
            import re
            match = re.search(r'(\d+)\s*ур\.', text)
            if match:
                return int(match.group(1))

        return 0

    def check_guild_bonus_active(self):
        """Проверяет активен ли бонус гильдии (Сила+Здоровье) через профиль персонажа"""
        # Смотрим на странице профиля наличие бонуса гильдии
        resp = self.client.get(f"{BASE_URL}/user")
        if not resp:
            return False

        html = self.client.current_page
        if not html:
            return False

        # Ищем текст "Гильдейский Бонус" с иконками strength и health
        # <a href="...">Гильдейский Бонус</a> (<img src=".../strength.png">...<img src=".../health.png">...)
        if "Гильдейский Бонус" in html and "strength.png" in html and "health.png" in html:
            print("[MINES] Бонус гильдии (Сила+Здоровье) активен")
            return True

        print("[MINES] Бонус гильдии НЕ активен")
        return False

    def activate_guild_bonus(self):
        """Активирует бонус гильдии (Сила+Здоровье) за серебро - САМЫЙ ДЕШЁВЫЙ"""
        print("[MINES] Активирую бонус гильдии (Сила+Здоровье)...")

        # Переходим на вкладку buffType=2 (Сила+Здоровье)
        resp = self.client.get(f"{GUILD_BONUS_URL}?buffType=2")
        if not resp:
            print("[MINES] Не удалось открыть страницу бонуса гильдии")
            return False

        soup = self.client.soup()
        if not soup:
            return False

        # Ищем ссылку на покупку с иконками strength.png И health.png (НЕ armor!)
        # buffTimePack-2 = самый дешёвый (90 серебра, +135%)
        # buffTimePack-1 = средний (180 серебра, +140%)
        # buffTimePack-0 = дорогой (270 серебра, +145%)
        # Берём ПОСЛЕДНИЙ найденный - он самый дешёвый
        buy_link = None
        for link in soup.select("a.tile-link[href*='buyLink']"):
            link_html = str(link)
            # Нужен именно strength + health, НЕ armor
            has_strength = "strength.png" in link_html
            has_health = "health.png" in link_html
            has_armor = "armor.png" in link_html

            if has_strength and has_health and not has_armor:
                buy_link = link  # Сохраняем последний найденный (самый дешёвый)

        if not buy_link:
            print("[MINES] Кнопка покупки бонуса Сила+Здоровье не найдена")
            return False

        buy_url = buy_link.get("href", "")
        if not buy_url.startswith("http"):
            buy_url = urljoin(BASE_URL, buy_url)

        print(f"[MINES] Покупаю бонус Сила+Здоровье (самый дешёвый)...")
        resp = self.client.get(buy_url)

        if resp and "bonus" in resp.url:
            print("[MINES] Бонус гильдии активирован!")
            return True

        print("[MINES] Ошибка активации бонуса")
        return False

    def enter_lobby(self):
        """Заходит в лобби Заброшенной Шахты"""
        print("[MINES] Захожу в лобби Заброшенной Шахты...")

        resp = self.client.get(SURVIVAL_MINES_LOBBY_URL)
        if not resp:
            print("[MINES] Не удалось открыть лобби")
            return False

        if "/dungeon/lobby/survMines" in resp.url:
            print("[MINES] В лобби шахты")
            return True
        elif "/dungeon/combat/survMines" in resp.url:
            print("[MINES] Уже в бою!")
            return True

        print(f"[MINES] Неожиданный URL: {resp.url}")
        return False

    def start_fight(self):
        """Нажимает кнопку 'Начать бой!'"""
        html = self.client.current_page
        if not html:
            return False

        # Ищем AJAX URL для linkStartCombat (кнопка "Начать бой!")
        ajax_urls = self._parse_ajax_urls(html)

        # Ищем URL содержащий linkStartCombat
        start_url = None
        for element_id, url in ajax_urls.items():
            if "linkStartCombat" in url:
                start_url = url
                print(f"[MINES] Найден linkStartCombat: {element_id}")
                break

        if start_url:
            print("[MINES] Нажимаю 'Начать бой!' (AJAX)")
            resp = self._make_ajax_request(start_url)
            time.sleep(2)
            self.client.get(self.client.current_url)
            return "/dungeon/combat/survMines" in self.client.current_url

        # Fallback: ищем обычную ссылку
        soup = self.client.soup()
        if soup:
            start_btn = soup.select_one("a.go-btn._main")
            if start_btn:
                href = start_btn.get("href", "")
                if href and not href.startswith("javascript"):
                    if not href.startswith("http"):
                        href = urljoin(BASE_URL, href)
                    print(f"[MINES] Нажимаю 'Начать бой!' (link)")
                    self.client.get(href)
                    return "/dungeon/combat/survMines" in self.client.current_url

        # Сохраняем HTML для дебага
        try:
            import os
            debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug_mines_lobby.html")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(self.client.current_page or "")
            print(f"[MINES] DEBUG: saved to {debug_path}")
            print(f"[MINES] DEBUG: current URL = {self.client.current_url}")
        except Exception:
            pass

        print("[MINES] Кнопка 'Начать бой!' не найдена")
        return False

    def _parse_ajax_urls(self, html):
        """Извлекает Wicket AJAX URLs (используя централизованный парсер)"""
        return parse_ajax_urls(html)

    def _make_ajax_request(self, url):
        """AJAX запрос"""
        if not url or url.startswith("javascript"):
            return None

        if not url.startswith("http"):
            url = urljoin(self.client.current_url, url)

        base_path = self.client.current_url.split("?")[0].replace(BASE_URL, "")
        headers = {
            "Wicket-Ajax": "true",
            "Wicket-Ajax-BaseURL": base_path.lstrip("/"),
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml, text/xml, */*; q=0.01",
            "Referer": self.client.current_url,
        }
        return self.client.session.get(url, headers=headers)

    def get_current_wave(self):
        """Получает текущий номер волны"""
        soup = self.client.soup()
        if not soup:
            return 0

        # <div class="survival-info">Волна <span class="survival-info-num">1</span></div>
        wave_span = soup.select_one(".survival-info-num")
        if wave_span:
            try:
                return int(wave_span.get_text(strip=True))
            except ValueError:
                pass
        return 0

    def get_attack_url(self):
        """Получает URL атаки"""
        urls = self._parse_ajax_urls(self.client.current_page)
        return urls.get("ptx_combat_rich2_attack_link")

    def get_skill_urls(self):
        """Получает URLs скиллов"""
        urls = self._parse_ajax_urls(self.client.current_page)
        skills = {}
        for element_id, url in urls.items():
            if "skillBlock" in url and "skillLink" in url:
                match = re.search(r'skills-(\d+)-skillBlock', url)
                if match:
                    skill_pos = int(match.group(1)) + 1
                    skills[skill_pos] = url
        return skills

    def use_skill_if_ready(self, skill_cds=None):
        """Использует готовый скилл"""
        now = time.time()

        # GCD
        if (now - self.last_gcd_time) < GCD:
            return False

        # Дефолтные КД если не заданы
        if skill_cds is None:
            skill_cds = {1: 15.5, 2: 60.0}

        skill_urls = self.get_skill_urls()

        for pos in sorted(skill_urls.keys()):
            # Проверяем КД
            skill_cd = skill_cds.get(pos, 15.0)
            last_use = self.skill_cooldowns.get(pos, 0)
            if (now - last_use) < skill_cd:
                continue

            # Скилл готов
            resp = self._make_ajax_request(skill_urls[pos])
            if resp and resp.status_code == 200:
                print(f"[MINES] Скилл {pos} использован")
                self.skill_cooldowns[pos] = now
                self.last_gcd_time = now
                self.client.get(self.client.current_url)
                return True

        return False

    def attack(self, skill_cds=None):
        """Атакует"""
        action_url = self.get_attack_url()

        if not action_url:
            return False

        resp = self._make_ajax_request(action_url)
        if resp and resp.status_code == 200:
            self.client.get(self.client.current_url)
            return True
        return False

    def _check_death(self):
        """Проверяет умер ли персонаж"""
        html = self.client.current_page
        if not html:
            return False

        if "battlefield-modal" in html and "_fail" in html:
            return True
        if "_death-hero" in html:
            return True

        death_texts = ["вы погибли", "ты пала в сражении", "ты пал в сражении"]
        html_lower = html.lower()
        if any(text in html_lower for text in death_texts):
            return True

        return False

    def go_to_city(self):
        """Выходит в город"""
        print("[MINES] Выхожу в город...")
        resp = self.client.get(CITY_URL)
        if resp and "/city" in resp.url:
            print("[MINES] В городе!")
            return True
        return False

    def fight_until_wave(self, max_wave=MAX_WAVE, skill_cds=None):
        """
        Бой в шахте до указанной волны.

        Returns:
            str: "completed" (дошли до волны), "died" (погибли), "error"
        """
        print(f"[MINES] Бой до волны {max_wave}...")

        last_wave = 0
        attacks = 0
        no_progress = 0

        # Настраиваем refresher для сбора лута
        self._setup_refresher_url()

        while True:
            try:
                # Обновляем страницу
                self.client.get(self.client.current_url)

                # Проверяем смерть
                if self._check_death():
                    print("[MINES] Персонаж погиб!")
                    # Финальный сбор лута перед выходом
                    self._collect_loot_via_refresher()
                    return "died"

                # Проверяем волну
                wave = self.get_current_wave()
                if wave != last_wave:
                    print(f"[MINES] Волна {wave}")
                    last_wave = wave
                    no_progress = 0

                # Достигли цели?
                if wave >= max_wave:
                    print(f"[MINES] Достигли волны {wave} >= {max_wave}, выходим!")
                    # Финальный сбор лута
                    self._collect_loot_via_refresher()
                    return "completed"

                # Используем скилл
                self.use_skill_if_ready(skill_cds)

                # Атакуем
                if self.attack():
                    attacks += 1
                    no_progress = 0

                    # Сбор лута каждые 3 атаки
                    self.attack_count += 1
                    if self.attack_count % LOOT_COLLECT_INTERVAL == 0:
                        self._collect_loot_via_refresher()

                    if attacks % 50 == 0:
                        print(f"[MINES] Атак: {attacks}, волна: {wave}")
                else:
                    no_progress += 1
                    if no_progress > 50:
                        print("[MINES] Нет прогресса, что-то не так")
                        # Финальный сбор лута
                        self._collect_loot_via_refresher()
                        return "error"

                time.sleep(1.5)

            except Exception as e:
                print(f"[MINES] Ошибка: {e}")
                return "error"

    def run_session(self, skill_cds=None, max_wave=MAX_WAVE, max_level=None):
        """
        Полная сессия в шахте:
        1. Проверяем уровень (если задан max_level)
        2. Проверяем/активируем бонус гильдии
        3. Заходим в шахту
        4. Бьёмся до 31 волны
        5. Выходим в город

        Returns:
            str: "success", "died", "max_level_reached", "error"
        """
        print("=" * 50)
        print("[MINES] Начинаю сессию в Заброшенной Шахте")

        # 0. Проверяем уровень персонажа
        if max_level is not None:
            level = self.get_character_level()
            print(f"[MINES] Текущий уровень: {level}, максимальный: {max_level}")
            if level >= max_level:
                print(f"[MINES] Достигнут уровень {level} >= {max_level}, останавливаемся!")
                return "max_level_reached"
        print("=" * 50)

        # 1. Бонус гильдии
        if not self.check_guild_bonus_active():
            if not self.activate_guild_bonus():
                print("[MINES] Не удалось активировать бонус, продолжаем без него")

        # 2. Заходим в лобби
        if not self.enter_lobby():
            print("[MINES] Не удалось войти в лобби")
            return False

        # 3. Начинаем бой (если ещё не в бою)
        if "/dungeon/combat/survMines" not in self.client.current_url:
            if not self.start_fight():
                print("[MINES] Не удалось начать бой")
                return False

        # Уведомляем в Telegram что вошли в шахту
        try:
            from requests_bot.config import get_profile_username
            try:
                from requests_bot.telegram_bot import notify_sync as telegram_notify
            except ImportError:
                telegram_notify = lambda msg: None
            username = get_profile_username()
            log_info(f"⛏️ [{username}] Вошёл в Заброшенную Шахту (до волны {max_wave})")
        except Exception:
            pass

        # 4. Бьёмся до нужной волны
        result = self.fight_until_wave(max_wave, skill_cds)

        # 5. Выходим в город
        self.go_to_city()

        # Логируем результат
        try:
            if result == "completed":
                log_info(f"✅ [{username}] Шахта завершена (волна {max_wave})")
            elif result == "died":
                log_warning(f"💀 [{username}] Погиб в шахте!")
        except Exception:
            pass

        if result == "completed":
            print("[MINES] Сессия завершена успешно!")
            return True
        elif result == "died":
            print("[MINES] Погибли в шахте")
            return False
        else:
            print("[MINES] Сессия завершена с ошибкой")
            return False


def fight_in_survival_mines(client, skill_cds=None, max_wave=MAX_WAVE, max_level=None):
    """Удобная функция для вызова из main

    Returns:
        str: "success", "died", "max_level_reached", "error"
    """
    mines = SurvivalMinesClient(client)
    return mines.run_session(skill_cds, max_wave, max_level)


def test_survival_mines():
    """Тест шахты"""
    from requests_bot.client import VMMOClient

    print("=" * 50)
    print("VMMO Survival Mines Test")
    print("=" * 50)

    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            return

    mines = SurvivalMinesClient(client)

    # Проверяем бонус
    print("\n[TEST] Проверка бонуса гильдии...")
    has_bonus = mines.check_guild_bonus_active()
    print(f"Бонус активен: {has_bonus}")

    # Заходим в лобби
    print("\n[TEST] Вход в лобби...")
    if mines.enter_lobby():
        print("[OK] В лобби")
    else:
        print("[ERR] Ошибка входа")
        return

    print("\n[TEST] Тест завершён (бой не начат)")


# ============================================
# Module-level helper для использования из других модулей
# ============================================

def ensure_guild_bonus(client) -> bool:
    """Проверяет и активирует гильдийский бонус Сила+Здоровье.

    Используется не только в Survival Mines, но и перед event-party
    (FireTower) — пати без бонуса в брутале/героике уходит до конца.

    Returns:
        True если бонус активен (или был активирован),
        False если активация не удалась (нет серебра/нет гильдии/ошибка).
    """
    smc = SurvivalMinesClient(client)
    if smc.check_guild_bonus_active():
        return True
    return smc.activate_guild_bonus()


if __name__ == "__main__":
    test_survival_mines()
