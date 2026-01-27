# ============================================
# VMMO Requests Bot - Combat Module
# ============================================
# Боевая логика на чистом requests
# ============================================

import re
import time
from bs4 import BeautifulSoup
from requests_bot.config import LOOT_COLLECT_INTERVAL


class CombatParser:
    """Парсер боевой страницы"""

    def __init__(self, html, base_url):
        self.html = html
        self.base_url = base_url
        self.soup = BeautifulSoup(html, "html.parser")
        self._ajax_urls = {}
        self._parse_ajax_urls()

    def _parse_ajax_urls(self):
        """Извлекает все Wicket AJAX URLs из скриптов"""
        # Паттерн 1: Wicket.Ajax.ajax({"c":"element_id","u":"url"...})
        pattern1 = r'Wicket\.Ajax\.ajax\(\{[^}]*"c":"([^"]+)"[^}]*"u":"([^"]+)"'
        matches = re.findall(pattern1, self.html)
        for element_id, url in matches:
            self._ajax_urls[element_id] = url

        # Паттерн 2: "c":"element_id","u":"url" (в массивах обработчиков)
        pattern2 = r'"c":"([^"]+)","u":"([^"]+)"'
        matches2 = re.findall(pattern2, self.html)
        for element_id, url in matches2:
            if element_id not in self._ajax_urls:
                self._ajax_urls[element_id] = url

    def get_attack_url(self):
        """Возвращает URL для кнопки атаки"""
        return self._ajax_urls.get("ptx_combat_rich2_attack_link")

    def get_skill_urls(self):
        """Возвращает URLs для скиллов"""
        skills = {}
        # Скиллы имеют паттерн: skills-N-skillBlock
        for element_id, url in self._ajax_urls.items():
            if "skillBlock" in url and "skillLink" in url:
                # Извлекаем номер скилла из URL
                match = re.search(r'skills-(\d+)-skillBlock', url)
                if match:
                    skill_pos = int(match.group(1)) + 1  # 0-indexed -> 1-indexed
                    skills[skill_pos] = url
        return skills

    def get_unit_urls(self):
        """Возвращает URLs для кликов по юнитам (выбор цели)"""
        units = {}
        for element_id, url in self._ajax_urls.items():
            if "actOnLink" in url:
                # Извлекаем позицию
                match = re.search(r'entities-(\d+)-entityPanel', url)
                if match:
                    units[element_id] = url
        return units

    def get_source_urls(self):
        """Возвращает URLs для переключения источников (Hell Games)"""
        sources = {}
        for element_id, url in self._ajax_urls.items():
            if "sources-sources" in url:
                match = re.search(r'sources-(\d+)-link', url)
                if match:
                    source_idx = int(match.group(1))
                    sources[source_idx] = {"id": element_id, "url": url}
        return sources

    def get_sources_info(self):
        """
        Возвращает информацию об источниках в Адских Играх.
        Классы: _side-light (враг), _side-dark (наш), _current (текущий), _lock (заблокирован)
        """
        sources = []
        source_links = self.soup.select("a.source-link")

        for i, link in enumerate(source_links):
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

    def find_enemy_source(self):
        """Находит вражеский источник (light) который не текущий и не заблокирован"""
        sources_info = self.get_sources_info()
        source_urls = self.get_source_urls()

        for src in sources_info:
            idx = src["idx"]
            if src["is_light"] and not src["is_current"] and not src["is_locked"]:
                if idx in source_urls:
                    return idx, source_urls[idx]["url"]
        return None, None

    def has_units(self):
        """Проверяет наличие юнитов (врагов) на поле"""
        # Позиции врагов: 21-25
        for pos in range(21, 26):
            unit = self.soup.select_one(f".unit._unit-pos-{pos}")
            if unit:
                return True
        return False

    def get_units_info(self):
        """Возвращает информацию о юнитах"""
        units = []
        for pos in range(21, 26):
            unit = self.soup.select_one(f".unit._unit-pos-{pos}")
            if unit:
                name_el = unit.select_one(".unit-name")
                hp_el = unit.select_one(".unit-hp-bar")
                units.append({
                    "pos": pos,
                    "name": name_el.get_text(strip=True) if name_el else "Unknown",
                    "has_hp": hp_el is not None
                })
        return units

    def get_enemy_hp(self):
        """Возвращает текущий HP врага (из шапки справа)

        Returns:
            int: HP врага в абсолютных значениях, или 0 если не найден
        """
        # HP врага находится в .battlefield-head-right .battlefield-head-hp-text
        enemy_head = self.soup.select_one(".battlefield-head-right")
        if not enemy_head:
            return 0

        hp_text_el = enemy_head.select_one(".battlefield-head-hp-text")
        if not hp_text_el:
            return 0

        hp_text = hp_text_el.get_text(strip=True)
        # Формат: "197.8K / 264.3K" или "640 / 640"
        # Берём первое число (текущий HP)
        match = re.match(r'([\d.,]+)(K)?', hp_text)
        if not match:
            return 0

        hp_value = float(match.group(1).replace(',', '.'))
        if match.group(2) == 'K':
            hp_value *= 1000

        return int(hp_value)

    def is_battle_active(self):
        """Проверяет активен ли бой"""
        return self.get_attack_url() is not None

    def get_loot_take_url(self):
        """Возвращает базовый URL для сбора лута

        Формат: Ptx.Shadows.Combat.lootTakeUrl = 'URL'
        """
        match = re.search(r"lootTakeUrl\s*=\s*['\"]([^'\"]+)['\"]", self.html)
        return match.group(1) if match else None

    def find_loot_ids(self):
        """Находит все ID лута в HTML/AJAX ответе

        Ищет двумя способами:
        1. HTML div: <div id="loot_box_77322" class="combat-loot">
        2. JS вызов: dropLoot({id: '77322', ...})

        Returns:
            set: Множество ID лута (строки)
        """
        loot_ids = set()

        # Способ 1: HTML лут-боксы
        html_loot = re.findall(r'id="loot_box_(\d+)"', self.html)
        loot_ids.update(html_loot)

        # Способ 2: JS dropLoot вызовы
        js_loot = re.findall(r"dropLoot\s*\(\s*\{[^}]*id:\s*'(\d+)'", self.html)
        loot_ids.update(js_loot)

        return loot_ids

    def check_skill_cooldown(self, skill_pos):
        """Проверяет КД скилла (True = на КД, False = готов)"""
        # Ищем таймер скилла
        wrapper = self.soup.select_one(f".wrap-skill-link._skill-pos-{skill_pos}")
        if not wrapper:
            return True  # Нет скилла

        timer = wrapper.select_one(".time-counter")
        if timer:
            timer_text = timer.get_text(strip=True)
            if timer_text and timer_text != "00:00":
                return True  # На КД
        return False

    def get_ready_skills(self):
        """Возвращает список готовых скиллов"""
        skill_urls = self.get_skill_urls()
        ready = []
        for pos, url in skill_urls.items():
            if not self.check_skill_cooldown(pos):
                ready.append({"pos": pos, "url": url})
        return ready


class CombatClient:
    """Клиент для боя через requests"""

    def __init__(self, vmmo_client):
        self.client = vmmo_client
        self.parser = None
        self.page_id = None
        self.collected_loot = set()  # Собранные ID лута (чтобы не собирать дважды)
        self.loot_take_url = None  # Сохраняем URL для сбора лута из начальной страницы
        self.dungeon_path = None  # Путь данжена для refresher (например "dungeon/combat/dSanctuary")
        self.difficulty_param = None  # Параметр сложности (например "1=normal")
        self.attack_count = 0  # Счётчик атак для периодического сбора лута

    def load_combat_page(self, url="/basin/combat"):
        """Загружает страницу боя"""
        resp = self.client.get(url)
        self.parser = CombatParser(self.client.current_page, resp.url)

        # Сохраняем loot URL из начальной страницы (он не приходит в AJAX)
        self.loot_take_url = self.parser.get_loot_take_url()

        # Извлекаем page ID из URL
        match = re.search(r'\?(\d+)', resp.url)
        if match:
            self.page_id = match.group(1)

        # Извлекаем путь данжена и параметр сложности для refresher
        # URL формат: https://vmmo.vten.ru/dungeon/combat/dSanctuary?6&1=normal
        current_url = resp.url
        if "/dungeon/combat/" in current_url:
            # Извлекаем путь: dungeon/combat/dSanctuary
            path_match = re.search(r'(dungeon/combat/[^?]+)', current_url)
            if path_match:
                self.dungeon_path = path_match.group(1)

            # Извлекаем параметр сложности: 1=normal, 1=hard, 1=impossible
            diff_match = re.search(r'1=(normal|hard|impossible)', current_url)
            if diff_match:
                self.difficulty_param = f"1={diff_match.group(1)}"

        # Сбрасываем счётчик атак
        self.attack_count = 0

        return self.parser

    def _make_ajax_request(self, url):
        """Выполняет AJAX запрос"""
        # Определяем base URL из текущего URL
        base_url = self.client.current_url
        if "?" in base_url:
            base_path = base_url.split("?")[0].replace("https://vmmo.vten.ru/", "")
            base_url_header = f"{base_path}?{self.page_id}" if self.page_id else base_path
        else:
            base_url_header = f"basin/combat?{self.page_id}" if self.page_id else ""

        headers = {
            "Wicket-Ajax": "true",
            "Wicket-Ajax-BaseURL": base_url_header,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml, text/xml, */*; q=0.01",
            "Referer": self.client.current_url,
        }
        resp = self.client.session.get(url, headers=headers)

        # Обновляем current_page для последующего парсинга
        if resp.status_code == 200:
            self.client.current_page = resp.text

        return resp

    def collect_loot(self):
        """Собирает лут из текущего ответа

        Returns:
            int: Количество собранного лута
        """
        if not self.parser:
            return 0

        loot_ids = self.parser.find_loot_ids()

        # Используем сохранённый loot_url (из начальной страницы)
        # AJAX ответы не содержат lootTakeUrl
        loot_url = self.loot_take_url
        if not loot_url:
            # Попробуем получить из текущего parser (на случай если это не AJAX)
            loot_url = self.parser.get_loot_take_url()

        if not loot_ids or not loot_url:
            return 0

        collected = 0
        for loot_id in loot_ids:
            if loot_id not in self.collected_loot:
                collect_url = loot_url + loot_id
                self.client.get(collect_url)
                self.collected_loot.add(loot_id)
                collected += 1
                print(f"[LOOT] Собран: {loot_id}")

        return collected

    def collect_loot_via_refresher(self):
        """Собирает лут через refresher endpoint (основной метод сбора)

        Лут в VMMO приходит через refresher, а не через WebSocket/AJAX атаки.
        Браузер вызывает refresher каждые 500ms, мы вызываем каждые N атак.

        Returns:
            int: Количество собранного лута
        """
        if not self.page_id or not self.dungeon_path:
            return 0

        # Формируем URL refresher
        # Формат: dungeon/combat/dSanctuary?{pageId}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher&1=normal
        refresher_url = f"https://vmmo.vten.ru/{self.dungeon_path}?{self.page_id}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher"
        if self.difficulty_param:
            refresher_url += f"&{self.difficulty_param}"

        try:
            resp = self._make_ajax_request(refresher_url)
            if resp.status_code != 200:
                return 0

            response_text = resp.text

            # Ищем lootTakeUrl в ответе refresher (он там есть!)
            loot_url_match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", response_text)
            if loot_url_match:
                self.loot_take_url = loot_url_match.group(1)

            # Ищем все dropLoot в ответе
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
                        self.client.get(take_url)
                        self.collected_loot.add(loot_id)
                        collected += 1
                        print(f"[LOOT] Собран: {loot_id}")
                    except Exception as e:
                        print(f"[LOOT ERROR] {e}")

            return collected

        except Exception as e:
            print(f"[REFRESHER ERROR] {e}")
            return 0

    def attack(self):
        """Выполняет атаку"""
        if not self.parser:
            return False, "No parser loaded"

        attack_url = self.parser.get_attack_url()
        if not attack_url:
            return False, "No attack URL found"

        resp = self._make_ajax_request(attack_url)
        if resp.status_code == 200:
            # Обновляем parser с новым ответом для поиска лута
            self.parser = CombatParser(self.client.current_page, self.client.current_url)

            # Увеличиваем счётчик атак
            self.attack_count += 1

            # Собираем лут из AJAX ответа (старый метод - может найти что-то)
            self.collect_loot()

            # Каждые 3 атаки вызываем refresher для сбора лута (основной метод)
            if self.attack_count % LOOT_COLLECT_INTERVAL == 0:
                self.collect_loot_via_refresher()

            return True, "Attack successful"
        return False, f"Attack failed: {resp.status_code}"

    def use_skill(self, skill_pos):
        """Использует скилл"""
        if not self.parser:
            return False, "No parser loaded"

        skill_urls = self.parser.get_skill_urls()
        if skill_pos not in skill_urls:
            return False, f"Skill {skill_pos} not found"

        # Проверяем КД
        if self.parser.check_skill_cooldown(skill_pos):
            return False, f"Skill {skill_pos} on cooldown"

        resp = self._make_ajax_request(skill_urls[skill_pos])
        if resp.status_code == 200:
            # Обновляем parser
            self.parser = CombatParser(self.client.current_page, self.client.current_url)

            # Увеличиваем счётчик атак (скилл = атака)
            self.attack_count += 1

            # Собираем лут из AJAX ответа
            self.collect_loot()

            # Каждые 3 атаки вызываем refresher
            if self.attack_count % LOOT_COLLECT_INTERVAL == 0:
                self.collect_loot_via_refresher()

            return True, f"Skill {skill_pos} used"
        return False, f"Skill failed: {resp.status_code}"

    def use_first_ready_skill(self):
        """Использует первый готовый скилл"""
        if not self.parser:
            return False, "No parser loaded"

        ready = self.parser.get_ready_skills()
        if not ready:
            return False, "No skills ready"

        skill = ready[0]
        return self.use_skill(skill["pos"])

    def switch_source(self, source_idx):
        """Переключает источник в Адских Играх"""
        if not self.parser:
            return False, "No parser loaded"

        sources = self.parser.get_source_urls()
        if source_idx not in sources:
            return False, f"Source {source_idx} not found"

        resp = self._make_ajax_request(sources[source_idx]["url"])
        if resp.status_code == 200:
            self.load_combat_page()
            return True, f"Switched to source {source_idx}"
        return False, f"Switch failed: {resp.status_code}"

    def fight_loop(self, max_attacks=50, use_skills=True, delay=1.5):
        """Боевой цикл"""
        attacks = 0

        while attacks < max_attacks:
            if not self.parser or not self.parser.is_battle_active():
                # Финальный сбор лута перед выходом
                self.collect_loot_via_refresher()
                return "no_battle", attacks

            # Используем скилл если доступен
            if use_skills:
                ready = self.parser.get_ready_skills()
                if ready:
                    success, msg = self.use_skill(ready[0]["pos"])
                    if success:
                        print(f"[SKILL] {msg}")
                        time.sleep(delay)
                        attacks += 1
                        continue

            # Атакуем
            success, msg = self.attack()
            if success:
                print(f"[ATTACK] #{attacks + 1}")
                attacks += 1
                time.sleep(delay)
            else:
                print(f"[ERR] {msg}")
                break

        # Финальный сбор лута
        self.collect_loot_via_refresher()
        return "max_attacks", attacks


def test_combat():
    """Тест боевой системы"""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from requests_bot.client import VMMOClient

    print("=" * 50)
    print("VMMO Combat System Test")
    print("=" * 50)

    # Авторизуемся
    client = VMMOClient()
    client.load_cookies()
    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            return

    # Создаём боевой клиент
    combat = CombatClient(client)

    print("\n[*] Loading Hell Games...")
    parser = combat.load_combat_page("/basin/combat")

    if parser.is_battle_active():
        print("[OK] Battle is active!")
        print(f"  Attack URL: {parser.get_attack_url()[:60]}...")
        print(f"  Skills: {list(parser.get_skill_urls().keys())}")
        print(f"  Ready skills: {[s['pos'] for s in parser.get_ready_skills()]}")
        print(f"  Sources: {list(parser.get_source_urls().keys())}")
        print(f"  Units: {parser.get_units_info()}")

        # Пробуем одну атаку
        print("\n[*] Trying single attack...")
        success, msg = combat.attack()
        print(f"  Result: {msg}")

        if success:
            print(f"  New units: {combat.parser.get_units_info()}")
    else:
        print("[INFO] No active battle")
        print("  Make sure you're in a dungeon or Hell Games first")


if __name__ == "__main__":
    test_combat()
