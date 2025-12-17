# ============================================
# VMMO Requests Bot - Combat Module
# ============================================
# Боевая логика на чистом requests
# ============================================

import re
import time
from bs4 import BeautifulSoup


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
        # Паттерн: Wicket.Ajax.ajax({"c":"element_id","u":"url"...})
        pattern = r'Wicket\.Ajax\.ajax\(\{[^}]*"c":"([^"]+)"[^}]*"u":"([^"]+)"'
        matches = re.findall(pattern, self.html)
        for element_id, url in matches:
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

    def is_battle_active(self):
        """Проверяет активен ли бой"""
        return self.get_attack_url() is not None

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

    def load_combat_page(self, url="/basin/combat"):
        """Загружает страницу боя"""
        resp = self.client.get(url)
        self.parser = CombatParser(self.client.current_page, resp.url)

        # Извлекаем page ID из URL
        match = re.search(r'\?(\d+)', resp.url)
        if match:
            self.page_id = match.group(1)

        return self.parser

    def _make_ajax_request(self, url):
        """Выполняет AJAX запрос"""
        headers = {
            "Wicket-Ajax": "true",
            "Wicket-Ajax-BaseURL": f"basin/combat?{self.page_id}" if self.page_id else "",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml, text/xml, */*; q=0.01",
            "Referer": self.client.current_url,
        }
        resp = self.client.session.get(url, headers=headers)
        return resp

    def attack(self):
        """Выполняет атаку"""
        if not self.parser:
            return False, "No parser loaded"

        attack_url = self.parser.get_attack_url()
        if not attack_url:
            return False, "No attack URL found"

        resp = self._make_ajax_request(attack_url)
        if resp.status_code == 200:
            # Перезагружаем страницу для получения обновлённого состояния
            self.load_combat_page()
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
            self.load_combat_page()
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
