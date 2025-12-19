# ============================================
# VMMO Hell Games (requests version)
# ============================================
# Адские Игры - бой пока данжены на КД
# ============================================

import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from requests_bot.config import BASE_URL, HELL_GAMES_URL

# Скиллы которые пропускаем в Hell Games (например Талисман Доблести)
HELL_GAMES_SKIP_SKILLS = [5]  # Пропускаем 5-й скилл

# Кулдауны скиллов (измерено + буфер)
SKILL_CDS = {
    1: 15.5,
    2: 24.5,
    3: 39.5,
    4: 54.5,
    5: 42.5,
}


class HellGamesClient:
    """Клиент для Адских Игр"""

    def __init__(self, client):
        self.client = client
        self.skill_cooldowns = {}  # {pos: last_use_time}
        self.last_gcd_time = 0
        self.GCD = 2.0
        self.loot_collected = 0

    def enter_hell_games(self):
        """Переходит в Адские Игры"""
        print("[HELL] Перехожу в Адские Игры...")
        resp = self.client.get(HELL_GAMES_URL)

        if "login" in resp.url.lower():
            print("[HELL] Требуется авторизация!")
            return False

        if "/basin/combat" not in resp.url:
            print(f"[HELL] Неожиданный URL: {resp.url}")
            return False

        print("[HELL] Вошли в Адские Игры!")
        return True

    def _check_death(self):
        """Проверяет умер ли персонаж"""
        html = self.client.current_page
        if not html:
            return False

        # Модальное окно смерти
        if "battlefield-modal" in html and "_fail" in html:
            return True

        # Класс _death-hero
        if "_death-hero" in html:
            return True

        # Текст смерти
        html_lower = html.lower()
        death_texts = ["вы погибли", "ты пала в сражении", "ты пал в сражении"]
        if any(text in html_lower for text in death_texts):
            return True

        return False

    def _parse_ajax_urls(self, html):
        """Извлекает Wicket AJAX URLs"""
        urls = {}
        pattern = r'Wicket\.Ajax\.ajax\(\{[^}]*"c":"([^"]+)"[^}]*"u":"([^"]+)"'
        matches = re.findall(pattern, html)
        for element_id, url in matches:
            urls[element_id] = url
        return urls

    def _make_ajax_request(self, url):
        """AJAX запрос"""
        # Защита от javascript: URLs
        if not url or url.startswith("javascript"):
            print(f"[HELL] DEBUG: Skipping invalid URL: {url}")
            return None

        # Делаем URL абсолютным если нужно
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

    def get_sources_info(self):
        """Информация об источниках"""
        soup = self.client.soup()
        if not soup:
            return []

        sources = []
        for i, link in enumerate(soup.select("a.source-link")):
            classes = link.get("class", [])
            if isinstance(classes, str):
                classes = classes.split()

            sources.append({
                "idx": i,
                "is_light": "_side-light" in classes,  # Вражеский
                "is_dark": "_side-dark" in classes,    # Наш
                "is_current": "_current" in classes,
                "is_locked": "_lock" in classes,
            })
        return sources

    def get_source_urls(self):
        """URLs переключения источников"""
        urls = self._parse_ajax_urls(self.client.current_page)
        sources = {}
        for element_id, url in urls.items():
            if "sources-sources" in url:
                match = re.search(r'sources-(\d+)-link', url)
                if match:
                    idx = int(match.group(1))
                    sources[idx] = url
        return sources

    def find_enemy_source(self):
        """Находит вражеский источник (light) для атаки"""
        sources_info = self.get_sources_info()
        source_urls = self.get_source_urls()

        for src in sources_info:
            idx = src["idx"]
            if src["is_light"] and not src["is_current"] and not src["is_locked"]:
                if idx in source_urls:
                    return idx, source_urls[idx]
        return None, None

    def all_sources_ours(self):
        """Проверяет все ли источники наши (dark)"""
        for src in self.get_sources_info():
            if src["is_light"]:
                return False
        return True

    def has_keeper_enemy(self):
        """Проверяет наличие хранителя на позиции 22"""
        soup = self.client.soup()
        if not soup:
            return False
        keeper = soup.select_one("div.unit._unit-pos-22 div.unit-show._keeper")
        return keeper is not None

    def get_keeper_url(self):
        """URL для клика на хранителя (выбор цели)"""
        soup = self.client.soup()
        if not soup:
            return None

        # Ищем ссылку на юнит в позиции 22 (хранитель)
        keeper_unit = soup.select_one("div.unit._unit-pos-22")
        if keeper_unit:
            unit_link = keeper_unit.select_one("a.unit-link")
            if unit_link:
                # Проверяем href (если не javascript:;)
                href = unit_link.get("href", "")
                if href and not href.startswith("javascript"):
                    return urljoin(BASE_URL, href)

                # Проверяем onclick для Wicket AJAX
                onclick = unit_link.get("onclick", "")
                match = re.search(r"u:'([^']+)'", onclick)
                if match:
                    return urljoin(self.client.current_url, match.group(1))

        # Fallback: ищем в AJAX URLs по ID элемента
        urls = self._parse_ajax_urls(self.client.current_page)
        for element_id, url in urls.items():
            if "unit-pos-22" in element_id or "entities-1" in url:
                return url
        return None

    def use_skill_if_ready(self):
        """Использует готовый скилл (с учётом КД и исключений)"""
        now = time.time()

        # Проверяем GCD
        if (now - self.last_gcd_time) < self.GCD:
            return False

        skill_urls = self.get_skill_urls()

        for pos in range(1, 6):
            # Пропускаем исключённые скиллы
            if pos in HELL_GAMES_SKIP_SKILLS:
                continue

            if pos not in skill_urls:
                continue

            # Проверяем индивидуальный КД
            skill_cd = SKILL_CDS.get(pos, 15.0)
            last_use = self.skill_cooldowns.get(pos, 0)
            if (now - last_use) < skill_cd:
                continue

            # Скилл готов - используем
            resp = self._make_ajax_request(skill_urls[pos])
            if resp and resp.status_code == 200:
                print(f"[HELL] Использован скилл {pos}")
                self.skill_cooldowns[pos] = now
                self.last_gcd_time = now
                # Обновляем страницу
                self.client.get(self.client.current_url)
                return True

        return False

    def attack(self):
        """Выполняет атаку"""
        attack_url = self.get_attack_url()
        if not attack_url:
            return False

        resp = self._make_ajax_request(attack_url)
        if resp and resp.status_code == 200:
            # Обновляем страницу
            self.client.get(self.client.current_url)
            return True
        return False

    def switch_to_source(self, source_url):
        """Переключается на источник"""
        resp = self._make_ajax_request(source_url)
        if resp and resp.status_code == 200:
            time.sleep(2)
            self.client.get(self.client.current_url)
            return True
        return False

    def select_keeper(self):
        """Выбирает хранителя как цель атаки"""
        keeper_url = self.get_keeper_url()
        if keeper_url:
            resp = self._make_ajax_request(keeper_url)
            if resp and resp.status_code == 200:
                print("[HELL] Выбрали хранителя как цель")
                self.client.get(self.client.current_url)
                return True
        return False

    def fight(self, duration_seconds):
        """
        Основной цикл боя в Адских Играх.

        Логика:
        1. Ищем вражеский источник (light) -> переходим
        2. Выбираем хранителя (pos-22) как цель -> бьём со скиллами
        3. Когда хранитель убит -> ищем следующий light
        4. Все наши (dark) -> ждём, атакуем без скиллов
        """
        print(f"[HELL] Начинаем бой на {duration_seconds // 60}м {duration_seconds % 60}с")

        if not self.enter_hell_games():
            return False

        end_time = time.time() + duration_seconds
        last_log_minute = -1
        keeper_selected = False  # Флаг: выбран ли хранитель как цель
        attacks = 0

        while time.time() < end_time:
            try:
                # Обновляем страницу для актуального состояния
                self.client.get(self.client.current_url)

                # Проверяем смерть
                if self._check_death():
                    print("[HELL] Персонаж погиб! Выходим...")
                    return False

                # Лог времени
                remaining = int(end_time - time.time())
                current_minute = remaining // 60
                if current_minute != last_log_minute and remaining > 0:
                    print(f"[HELL] Осталось {current_minute}м {remaining % 60}с")
                    last_log_minute = current_minute
                    # Debug: показываем состояние раз в минуту
                    sources = self.get_sources_info()
                    light_count = sum(1 for s in sources if s["is_light"])
                    dark_count = sum(1 for s in sources if s["is_dark"])
                    print(f"[HELL] DEBUG: keeper={self.has_keeper_enemy()}, sources={len(sources)} (light={light_count}, dark={dark_count}), attack_url={self.get_attack_url() is not None}")

                # Проверяем хранителя
                if self.has_keeper_enemy():
                    # Хранитель есть - выбираем его и бьём
                    if not keeper_selected:
                        if self.select_keeper():
                            keeper_selected = True
                        time.sleep(0.5)

                    # Используем скиллы и атакуем
                    self.use_skill_if_ready()
                    if self.attack():
                        attacks += 1
                        if attacks % 10 == 0:
                            print(f"[HELL] Атак: {attacks}")
                    time.sleep(1.5)

                else:
                    # Хранителя нет - убит или мы в пустом источнике
                    keeper_selected = False

                    # Ищем вражеский источник
                    idx, source_url = self.find_enemy_source()
                    if source_url:
                        print(f"[HELL] Переходим в вражеский источник {idx}...")
                        self.switch_to_source(source_url)
                        time.sleep(2)

                    elif self.all_sources_ours():
                        # Все наши - просто ждём, атакуем без скиллов
                        if self.attack():
                            attacks += 1
                        time.sleep(3)

                    else:
                        # Есть враги, но заблокированы - ждём
                        print(f"[HELL] Ждём (враги заблокированы или нет источников)")
                        time.sleep(2)

            except Exception as e:
                print(f"[HELL] Ошибка: {e}")
                time.sleep(2)

        print(f"[HELL] Время вышло! Всего атак: {attacks}")
        return True


def fight_in_hell_games(client, duration_seconds):
    """Удобная функция для вызова из main"""
    hell = HellGamesClient(client)
    return hell.fight(duration_seconds)


def test_hell_games():
    """Тест Адских Игр"""
    from requests_bot.client import VMMOClient

    print("=" * 50)
    print("VMMO Hell Games Test")
    print("=" * 50)

    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            return

    hell = HellGamesClient(client)

    # 1. Входим
    if not hell.enter_hell_games():
        print("[ERR] Не удалось войти в Hell Games")
        return

    # 2. Информация
    print("\n[INFO] Состояние:")
    print(f"  Attack URL: {hell.get_attack_url() is not None}")
    print(f"  Skills: {list(hell.get_skill_urls().keys())}")

    sources = hell.get_sources_info()
    print(f"  Sources: {len(sources)}")
    for s in sources:
        status = []
        if s["is_light"]: status.append("ENEMY")
        if s["is_dark"]: status.append("OURS")
        if s["is_current"]: status.append("CURRENT")
        if s["is_locked"]: status.append("LOCKED")
        print(f"    [{s['idx']}] {' '.join(status)}")

    print(f"  Has keeper: {hell.has_keeper_enemy()}")
    print(f"  All ours: {hell.all_sources_ours()}")

    # 3. Короткий бой (30 секунд)
    print("\n[*] Тестовый бой 30 секунд...")
    hell.fight(30)
    print("[OK] Тест завершён")


if __name__ == "__main__":
    test_hell_games()
