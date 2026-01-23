# ============================================
# VMMO Hell Games (requests version)
# ============================================
# Адские Игры - бой пока данжены на КД
# ============================================

import re
import time
import traceback
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from requests_bot.config import (
    BASE_URL, HELL_GAMES_URL, CITY_URL,
    is_craft_ready_soon, is_iron_craft_enabled
)
from requests_bot.craft import CyclicCraftClient


class HellGamesClient:
    """Клиент для Адских Игр"""

    def __init__(self, client, is_light_side=False, profile: str = "unknown"):
        """
        Args:
            client: VMMOClient
            is_light_side: True если персонаж светлый (враги = dark),
                          False если тёмный (враги = light)
            profile: имя профиля (для кэша цен аукциона)
        """
        self.client = client
        self.is_light_side = is_light_side
        self.profile = profile
        self.last_gcd_time = 0
        self.GCD = 2.0
        self.loot_collected = 0
        self.collected_loot_ids = set()  # ID собранного лута
        self.refresher_url = None  # URL для refresher (сбор лута)
        self.loot_take_url = None  # URL для сбора лута
        self.attack_count = 0  # Счётчик атак для периодического сбора лута

    def _collect_loot(self):
        """Собирает лут из текущего ответа"""
        html = self.client.current_page
        if not html:
            return 0

        # Ищем lootTakeUrl
        loot_url_match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", html)
        if not loot_url_match:
            return 0
        loot_url = loot_url_match.group(1)

        # Ищем ID лута двумя способами
        loot_ids = set()
        loot_ids.update(re.findall(r'id="loot_box_(\d+)"', html))
        loot_ids.update(re.findall(r"dropLoot\s*\(\s*\{[^}]*id:\s*'(\d+)'", html))

        collected = 0
        for loot_id in loot_ids:
            if loot_id not in self.collected_loot_ids:
                collect_url = loot_url + loot_id
                self.client.get(collect_url)
                self.collected_loot_ids.add(loot_id)
                collected += 1
                self.loot_collected += 1
                print(f"[LOOT] Собран: {loot_id}")

        return collected

    def _setup_refresher_url(self):
        """Формирует URL для refresher из текущей страницы боя"""
        html = self.client.current_page
        if not html:
            return

        # Ищем pageId
        page_id_match = re.search(r"ptxPageId\s*=\s*(\d+)", html)
        if not page_id_match:
            return

        page_id = page_id_match.group(1)

        # Формируем refresher URL для basin/combat
        # Формат: ?{pageId}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher
        # Используем относительный URL (только query string), чтобы urljoin правильно склеил с текущим URL
        self.refresher_url = f"?{page_id}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher"

        # Сохраняем lootTakeUrl
        loot_url_match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", html)
        if loot_url_match:
            self.loot_take_url = loot_url_match.group(1)

        self.attack_count = 0

    def _collect_loot_via_refresher(self):
        """Собирает лут через refresher endpoint (основной метод сбора)"""
        if not self.refresher_url:
            return 0

        try:
            # Преобразуем относительный URL в абсолютный
            absolute_url = urljoin(self.client.current_url, self.refresher_url)
            resp = self.client.session.get(absolute_url, timeout=10)
            if resp.status_code != 200:
                return 0

            response_text = resp.text

            # Ищем lootTakeUrl в ответе
            loot_url_match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", response_text)
            if loot_url_match:
                self.loot_take_url = loot_url_match.group(1)

            # Ищем dropLoot
            if "dropLoot" not in response_text:
                return 0

            # Парсим ID лута
            loot_ids = re.findall(r"id:\s*'(\d+)'", response_text)
            if not loot_ids or not self.loot_take_url:
                return 0

            collected = 0
            for loot_id in loot_ids:
                if loot_id not in self.collected_loot_ids:
                    take_url = self.loot_take_url + loot_id
                    try:
                        self.client.session.get(take_url, timeout=5)
                        self.collected_loot_ids.add(loot_id)
                        collected += 1
                        self.loot_collected += 1
                        print(f"[LOOT] Собран: {loot_id}")
                    except Exception as e:
                        print(f"[LOOT ERROR] {e}")

            return collected

        except Exception as e:
            print(f"[REFRESHER ERROR] {e}")
            return 0

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
        # Настраиваем refresher URL для сбора лута
        self._setup_refresher_url()
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

    def _heal_and_repair(self):
        """
        Восстанавливает здоровье и ремонтирует снаряжение после смерти.
        Ищет кнопку ppAction=hr (Heal + Repair) и нажимает её.
        """
        soup = self.client.soup()
        if not soup:
            return False

        # Ищем кнопку Heal+Repair (ppAction=hr)
        hr_link = soup.select_one('a.go-btn[href*="ppAction=hr"]')
        if hr_link:
            href = hr_link.get("href")
            if href:
                print("[HELL] Восстанавливаем здоровье и ремонтируем снаряжение...")
                self.client.get(href)
                time.sleep(1)
                return True

        # Fallback: ищем любую ссылку с ppAction=hr
        for link in soup.select("a[href*='ppAction=hr']"):
            href = link.get("href")
            if href:
                print("[HELL] Восстанавливаем здоровье и ремонтируем снаряжение...")
                self.client.get(href)
                time.sleep(1)
                return True

        print("[HELL] Кнопка восстановления не найдена")
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

        try:
            resp = self.client.session.get(url, headers=headers, timeout=10)
            return resp
        except Exception as e:
            print(f"[HELL] Ошибка AJAX запроса: {e}")
            return None

    def get_attack_url(self):
        """Получает URL атаки для Hell Games"""
        html = self.client.current_page
        if not html:
            return None

        # Hell Games использует специальный URL формат
        # Паттерн: basin/combat?{pageId}-1.IBehaviorListener.0-combatPanel-container-battlefield-controls-controlsInner-attackBlock-attackBlockInner-attackLink

        # Ищем pageId
        page_id_match = re.search(r"ptxPageId\s*=\s*(\d+)", html)
        if not page_id_match:
            print(f"[HELL] Ошибка: ptxPageId не найден!")
            return None

        page_id = page_id_match.group(1)

        # Формируем URL атаки (относительно ТЕКУЩЕЙ страницы, используем только query string)
        # Текущий URL: https://vmmo.vten.ru/basin/combat
        # Нужен: ?{pageId}-1.IBehaviorListener.0-...
        attack_url = f"?{page_id}-1.IBehaviorListener.0-combatPanel-container-battlefield-controls-controlsInner-attackBlock-attackBlockInner-attackLink"

        return attack_url

    def get_skill_urls(self):
        """Получает URLs скиллов для Hell Games"""
        html = self.client.current_page
        if not html:
            return {}

        # Ищем pageId
        page_id_match = re.search(r"ptxPageId\s*=\s*(\d+)", html)
        if not page_id_match:
            return {}

        page_id = page_id_match.group(1)

        # Формируем URLs для скиллов
        # Реальный паттерн из curl: ?{pageId}-2.IBehaviorListener.0-combatPanel-container-battlefield-controls-controlsInner-skills-{N}-skillBlock-skillBlockInner-skillLink
        # где N = 0..7 (позиции скиллов, 0-indexed)
        # ВАЖНО: индекс -2, а не -1 (как в атаке)!

        skills = {}
        for skill_idx in range(8):  # 0-7 (максимум 8 скиллов)
            skill_pos = skill_idx + 1  # 1-8
            skill_url = f"?{page_id}-2.IBehaviorListener.0-combatPanel-container-battlefield-controls-controlsInner-skills-{skill_idx}-skillBlock-skillBlockInner-skillLink"
            skills[skill_pos] = skill_url

        return skills

    def get_skills_status(self):
        """
        Получает статус всех скиллов: готов ли скилл или на КД.
        Парсит текущее состояние из HTML (класс _time-lock и time-counter).

        Returns:
            dict: {pos: {"ready": bool, "remaining_cd": int}}
        """
        soup = self.client.soup()
        if not soup:
            return {}

        skills_status = {}

        for pos in range(1, 9):  # Проверяем все 8 скиллов (1-8)
            skill_div = soup.select_one(f".wrap-skill-link._skill-pos-{pos}")
            if not skill_div:
                continue

            # Проверяем класс _time-lock (скилл на КД)
            classes = skill_div.get("class", [])
            if isinstance(classes, str):
                classes = classes.split()

            is_on_cd = "_time-lock" in classes

            # Парсим оставшееся время из time-counter
            remaining_cd = 0
            if is_on_cd:
                time_counter = skill_div.select_one(".time-counter")
                if time_counter and time_counter.text.strip():
                    try:
                        # Парсим формат "MM:SS" или "SS"
                        time_text = time_counter.text.strip()
                        parts = time_text.split(":")
                        if len(parts) == 2:  # MM:SS
                            remaining_cd = int(parts[0]) * 60 + int(parts[1])
                        elif len(parts) == 1:  # SS
                            remaining_cd = int(parts[0])
                    except (ValueError, IndexError):
                        # Если не удалось распарсить, считаем что на КД
                        remaining_cd = 999

            skills_status[pos] = {
                "ready": not is_on_cd,
                "remaining_cd": remaining_cd
            }

        return skills_status

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
                "is_light": "_side-light" in classes,
                "is_dark": "_side-dark" in classes,
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
        """
        Находит вражеский источник для атаки.
        Светлые ищут dark, тёмные ищут light.
        """
        sources_info = self.get_sources_info()
        source_urls = self.get_source_urls()

        for src in sources_info:
            idx = src["idx"]
            # Светлые атакуют dark, тёмные атакуют light
            is_enemy = src["is_dark"] if self.is_light_side else src["is_light"]
            if is_enemy and not src["is_current"] and not src["is_locked"]:
                if idx in source_urls:
                    return idx, source_urls[idx]
        return None, None

    def all_sources_ours(self):
        """Проверяет все ли источники наши"""
        for src in self.get_sources_info():
            # Светлые: враги = dark, тёмные: враги = light
            is_enemy = src["is_dark"] if self.is_light_side else src["is_light"]
            if is_enemy:
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
        """Использует готовый скилл (динамически проверяя готовность из HTML)"""
        now = time.time()

        # Проверяем GCD
        if (now - self.last_gcd_time) < self.GCD:
            return False

        # Получаем актуальный статус всех скиллов из HTML
        skills_status = self.get_skills_status()
        if not skills_status:
            return False

        skill_urls = self.get_skill_urls()

        for pos in range(1, 9):  # Проверяем все 8 скиллов (1-8)
            if pos not in skill_urls or pos not in skills_status:
                continue

            # Проверяем готовность скилла из HTML (учитывает дебаффы врагов)
            if not skills_status[pos]["ready"]:
                continue

            # Скилл готов - используем
            timestamp = int(time.time() * 1000)
            full_url = f"{skill_urls[pos]}&_={timestamp}&tmt=19"

            resp = self._make_ajax_request(full_url)
            if resp and resp.status_code == 200:
                self.last_gcd_time = now
                # Собираем лут через refresher каждые 3 атаки
                self.attack_count += 1
                if self.attack_count % 3 == 0:
                    self._collect_loot_via_refresher()
                time.sleep(0.5)  # Задержка после скилла
                # Обновляем страницу
                self.client.get(self.client.current_url)
                return True

        return False

    def attack(self):
        """Выполняет атаку в Hell Games"""
        action_url = self.get_attack_url()

        if not action_url:
            return False

        # Добавляем timestamp параметры как в браузере
        timestamp = int(time.time() * 1000)
        full_url = f"{action_url}&_={timestamp}&tmt=19"

        try:
            resp = self._make_ajax_request(full_url)
            if resp and resp.status_code == 200:
                # Собираем лут через refresher каждые 3 атаки
                self.attack_count += 1
                if self.attack_count % 3 == 0:
                    self._collect_loot_via_refresher()
                time.sleep(1.0)  # Задержка после атаки
                # Обновляем страницу
                self.client.get(self.client.current_url)
                return True
        except Exception as e:
            print(f"[HELL] Ошибка атаки: {e}")

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

    def go_to_city(self):
        """Выходит в город после Hell Games"""
        print("[HELL] Выхожу в город...")
        resp = self.client.get(CITY_URL)
        if resp and "/city" in resp.url:
            print("[HELL] В городе!")
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
        print(f"[HELL] ===== НАЧАЛО БОЯ: {duration_seconds // 60}м {duration_seconds % 60}с =====")

        # Проверяем и ремонтируем снаряжение перед боем
        try:
            self.client.repair_equipment()
        except Exception:
            pass
        if not self.enter_hell_games():
            print("[HELL] ===== ОШИБКА ВХОДА =====")
            return False

        print("[HELL] ===== ВХОД УСПЕШЕН, НАЧИНАЕМ ЦИКЛ БОЯ =====")

        end_time = time.time() + duration_seconds
        last_log_minute = -1
        keeper_selected = False  # Флаг: выбран ли хранитель как цель
        attacks = 0

        iteration = 0
        while time.time() < end_time:
            try:
                iteration += 1
                # Обновляем страницу для актуального состояния
                self.client.get(self.client.current_url)

                # Проверяем смерть
                if self._check_death():
                    print("[HELL] Персонаж погиб! Восстанавливаемся...")
                    if self._heal_and_repair():
                        print("[HELL] Восстановлены! Продолжаем бой...")
                        keeper_selected = False
                        time.sleep(2)
                        continue
                    else:
                        print("[HELL] Не удалось восстановиться, выходим...")
                        return False

                # Лог времени (раз в минуту)
                remaining = int(end_time - time.time())
                current_minute = remaining // 60
                if current_minute != last_log_minute and remaining > 0:
                    print(f"[HELL] Осталось {current_minute}м {remaining % 60}с")
                    last_log_minute = current_minute

                # Проверяем крафт - выходим ЗАРАНЕЕ (60 сек до готовности)
                craft_enabled = is_iron_craft_enabled()
                craft_ready = is_craft_ready_soon(threshold_seconds=60) if craft_enabled else False

                if craft_enabled and craft_ready:
                    print("[HELL] Крафт скоро завершится! Выходим в город...")
                    # Выходим в город
                    self.client.get(CITY_URL)
                    time.sleep(2)

                    # Проверяем и забираем/перезапускаем крафт
                    craft = CyclicCraftClient(self.client, profile=self.profile)

                    # Первый вызов: забирает готовый крафт
                    craft.do_cyclic_craft_step()

                    # Второй вызов (через 5 сек): запускает новый крафт
                    time.sleep(5)
                    craft.do_cyclic_craft_step()

                    print("[HELL] Крафт обработан (забран + новый запущен), возвращаемся в Hell Games...")
                    # Возвращаемся обратно
                    if self.enter_hell_games():
                        keeper_selected = False  # Сбрасываем состояние
                        time.sleep(2)
                        continue  # Начинаем новую итерацию
                    else:
                        print("[HELL] Не удалось вернуться, выходим...")
                        return False

                # Проверяем хранителя
                has_keeper = self.has_keeper_enemy()

                if has_keeper:
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
                        time.sleep(2)

            except Exception as e:
                print(f"[HELL] !!!!! ОШИБКА В ЦИКЛЕ БОЯ: {e} !!!!!")
                print(f"[HELL] Traceback:\n{traceback.format_exc()}")
                time.sleep(2)

        print(f"[HELL] ===== ВРЕМЯ ВЫШЛО! Итераций: {iteration}, Атак: {attacks} =====")

        # Выходим в город чтобы можно было крафтить и т.д.
        self.go_to_city()

        return True


def fight_in_hell_games(client, duration_seconds, is_light_side=False, profile: str = "unknown"):
    """
    Удобная функция для вызова из main.

    Args:
        client: VMMOClient
        duration_seconds: длительность боя
        is_light_side: True если персонаж светлый (Happypoq и др.)
        profile: имя профиля (для кэша цен аукциона)
    """
    hell = HellGamesClient(client, is_light_side=is_light_side, profile=profile)
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
