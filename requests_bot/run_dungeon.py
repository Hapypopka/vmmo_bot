# ============================================
# VMMO Dungeon Runner - Full dungeon clear
# ============================================

import os
import sys
import re
import json
import time
from urllib.parse import urljoin

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient
from requests_bot.combat import CombatParser
from requests_bot.watchdog import reset_watchdog, is_watchdog_triggered, check_watchdog
from requests_bot.config import BASE_URL, SKIP_DUNGEONS, DUNGEON_ACTION_LIMITS, SCRIPT_DIR, get_skill_cooldowns


class DungeonRunner:
    """Полное прохождение данжена"""

    def __init__(self, client: VMMOClient):
        self.client = client
        self.base_url = BASE_URL
        self.combat_url = None
        self.page_id = None
        self.current_dungeon_id = None  # Текущий данжен для лимитов
        self.loot_collected = 0

    def collect_loot(self):
        """
        Собирает лут во время боя.
        Лут собирается через lootTakeUrl + pdti=item_id
        """
        html = self.client.current_page
        if not html:
            return 0

        # Находим lootTakeUrl
        loot_url_match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", html)
        if not loot_url_match:
            return 0

        loot_base_url = loot_url_match.group(1)

        # Находим все лут-боксы с id
        soup = self.client.soup()
        if not soup:
            return 0

        collected = 0
        loot_boxes = soup.select("div.combat-loot[id^='loot_box_']")

        for loot_box in loot_boxes:
            loot_id = loot_box.get("id", "")
            # Извлекаем числовой ID из "loot_box_182124"
            if loot_id.startswith("loot_box_"):
                item_id = loot_id.replace("loot_box_", "")
                take_url = loot_base_url + item_id
                self.client.get(take_url)
                collected += 1

        if collected > 0:
            print(f"[LOOT] Подобрали: {collected} шт.")
            self.loot_collected += collected

        return collected

    def _set_brutal_difficulty(self):
        """
        Устанавливает сложность Брутал.
        Кликает на левую стрелку пока не достигнет Брутал.
        Сложности идут по кругу: Норма -> Брутал -> Герой -> Норма...
        """
        max_attempts = 10  # Защита от бесконечного цикла

        for attempt in range(max_attempts):
            soup = self.client.soup()
            if not soup:
                break

            # Получаем текущую сложность
            level_text = soup.select_one(".switch-level-text")
            current_level = level_text.get_text(strip=True).lower() if level_text else ""

            # Если уже Брутал - останавливаемся
            if "брутал" in current_level:
                print(f"[*] Сложность: Брутал")
                return

            # Ищем кнопку переключения (левая стрелка)
            switch_left = soup.select_one("a.switch-level-left")
            if not switch_left:
                # Нет кнопки - данжен не поддерживает переключение (только Норма)
                print(f"[*] Сложность: {current_level.title()} (без переключения)")
                return

            href = switch_left.get("href")
            if not href:
                break

            print(f"[*] Переключаю: {current_level.title()} -> ...")
            self.client.get(href)

        # Показываем итоговую сложность если не нашли Брутал
        soup = self.client.soup()
        if soup:
            level_text = soup.select_one(".switch-level-text")
            if level_text:
                final_level = level_text.get_text(strip=True)
                print(f"[*] Сложность: {final_level}")

    def get_all_available_dungeons(self, section_id="tab2"):
        """Получает список всех доступных данженов"""
        print("\n[*] Loading dungeons page...")
        resp = self.client.get("/dungeons?52")

        # Извлекаем API URLs
        api_section_match = re.search(r"apiSectionUrl:\s*'([^']+)'", self.client.current_page)
        api_link_match = re.search(r"apiLinkUrl:\s*'([^']+)'", self.client.current_page)

        if not api_section_match or not api_link_match:
            print("[ERR] API URLs not found")
            return [], None

        api_section_url = api_section_match.group(1)
        api_link_url = api_link_match.group(1)

        # Запрашиваем данжены
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": resp.url,
        }

        section_url = f"{api_section_url}&section_id={section_id}"
        dungeons_resp = self.client.session.get(section_url, headers=headers)

        available = []
        try:
            data = dungeons_resp.json()
            dungeons = data.get("section", {}).get("dungeons", [])

            print(f"[*] Found {len(dungeons)} dungeons")

            for d in dungeons:
                cooldown = d.get("cooldown", 0)
                name = d.get("name", "?").replace("<br>", " ")
                dng_id = d.get("id")

                if cooldown:
                    mins = cooldown // 1000 // 60
                    secs = cooldown // 1000 % 60
                    print(f"  - {name}: CD {mins}m {secs}s")
                elif dng_id in SKIP_DUNGEONS:
                    print(f"  - {name}: SKIP (blacklisted)")
                else:
                    print(f"  - {name}: READY")
                    available.append({"id": dng_id, "name": name})

            return available, api_link_url

        except Exception as e:
            print(f"[ERR] Failed to parse dungeons: {e}")
            return [], None

    def check_death(self):
        """Проверяет умер ли персонаж"""
        html = self.client.current_page
        url = self.client.current_url

        # Проверяем URL на смерть
        if "/dead" in url or "/death" in url:
            return True

        # Проверяем текст
        death_texts = ["вы погибли", "вы мертвы", "персонаж мёртв", "you died", "you are dead"]
        if any(text in html.lower() for text in death_texts):
            return True

        return False

    def resurrect(self):
        """Воскрешает персонажа"""
        print("[*] Attempting resurrection...")

        # Переходим на страницу смерти/воскрешения
        resp = self.client.get("/city")

        # Ищем кнопку воскрешения
        resurrect_patterns = [
            r'href=["\']([^"\']*(?:resurrect|revive|воскрес)[^"\']*)["\']',
            r'href=["\']([^"\']*IBehaviorListener[^"\']*)["\'].*?(?:воскрес|resurrect)',
        ]

        for pattern in resurrect_patterns:
            match = re.search(pattern, self.client.current_page, re.IGNORECASE)
            if match:
                res_url = match.group(1).replace("&amp;", "&")
                print(f"[*] Found resurrect button")
                resp = self.client.get(res_url)
                time.sleep(1)

                # Проверяем успех
                if not self.check_death():
                    print("[OK] Resurrected!")
                    return True

        # Пробуем просто зайти в город
        resp = self.client.get("/city")
        if not self.check_death():
            print("[OK] Back in city")
            return True

        print("[ERR] Could not resurrect")
        return False

    def enter_dungeon(self, dungeon_id, api_link_url):
        """Входит в данжен и начинает бой"""
        print(f"\n[*] Entering dungeon: {dungeon_id}")
        self.current_dungeon_id = dungeon_id  # Сохраняем для лимитов

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }

        # 1. Получаем redirect URL
        enter_url = f"{api_link_url}&link_id={dungeon_id}"
        resp = self.client.session.get(enter_url, headers=headers)

        try:
            data = resp.json()
            if data.get("status") != "redirect":
                print(f"[ERR] Unexpected response: {data}")
                return False

            landing_url = data["url"]
            # Добавляем /normal если нет - нужно для корректной работы
            if not landing_url.endswith("/normal"):
                landing_url += "/normal"

            print(f"[*] Landing: {landing_url}")

        except Exception as e:
            print(f"[ERR] Failed to get redirect: {e}")
            return False

        # 2. Загружаем landing page
        resp = self.client.get(landing_url)
        print(f"[*] Landing page loaded: {resp.url}")

        # 3. Устанавливаем сложность Брутал
        self._set_brutal_difficulty()

        # 4. Ищем кнопку входа (несколько вариантов)
        html = self.client.current_page
        enter_btn_url = None

        # Вариант 1: Прямая ссылка на standby (новый формат)
        # Ищем: href="https://vmmo.vten.ru/dungeon/standby/dSanctuary"
        standby_match = re.search(
            r'href="([^"]*dungeon/standby/[^"?]+)"',
            html
        )
        if standby_match:
            enter_btn_url = standby_match.group(1)
            print(f"[*] Found standby link: {enter_btn_url}")

        # Вариант 2: ILinkListener (старый формат)
        if not enter_btn_url:
            ilink_match = re.search(
                r'href=["\']([^"\']*ILinkListener[^"\']*enterLinksPanel[^"\']*)["\']',
                html
            )
            if ilink_match:
                enter_btn_url = ilink_match.group(1)
                print(f"[*] Found ILinkListener enter: {enter_btn_url}")

        # Вариант 3: go-btn с Войти текстом
        if not enter_btn_url:
            soup = self.client.soup()
            if soup:
                for btn in soup.select("a.go-btn"):
                    btn_text = btn.get_text(strip=True)
                    href = btn.get("href", "")
                    if "Войти" in btn_text and href and href != "#":
                        enter_btn_url = href
                        print(f"[*] Found 'Войти' button: {enter_btn_url}")
                        break

        if not enter_btn_url:
            print("[ERR] Enter button not found")
            # Debug: save HTML
            debug_path = os.path.join(SCRIPT_DIR, "debug_no_enter.html")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Saved to {debug_path}")
            return False

        print(f"[*] Clicking enter button...")

        # 5. Кликаем enter
        resp = self.client.get(enter_btn_url)
        print(f"[*] Lobby/Standby: {resp.url}")

        # 5. Ищем кнопку "Начать бой"
        result = self._start_combat()
        # "completed" здесь маловероятно при входе, но если уже завершено - это тоже успех
        return result == True or result == "completed"

    def _start_combat(self, retry=0):
        """Начинает бой из lobby/standby/step страницы"""
        html = self.client.current_page
        soup = self.client.soup()

        # Проверяем сначала - может данжен уже завершён
        url_lower = self.client.current_url.lower()
        if "dungeoncompleted" in url_lower:
            print("[*] Dungeon already completed (URL)")
            return "completed"

        html_lower = html.lower() if html else ""
        if any(text in html_lower for text in ["подземелье пройдено", "подземелье зачищено"]):
            print("[*] Dungeon already completed (text)")
            return "completed"

        # Вариант 1: Кнопка "Продолжить бой" или "Начать бой" (после этапа / на standby)
        if soup:
            for btn in soup.select("a.go-btn"):
                btn_text = btn.get_text(strip=True)
                href = btn.get("href", "")
                # Ищем обе кнопки
                if ("Продолжить бой" in btn_text or "Начать бой" in btn_text) and href and href != "#" and not href.startswith("javascript"):
                    print(f"[*] Found '{btn_text}' button")
                    resp = self.client.get(href)
                    if "/combat" in resp.url:
                        self.combat_url = resp.url
                        return True
                    # Проверяем - может это был последний этап и данжен завершён
                    resp_url_lower = resp.url.lower()
                    if "dungeoncompleted" in resp_url_lower:
                        print("[*] Dungeon completed after clicking button")
                        return "completed"
                    # Проверяем текст страницы на завершение
                    new_html = self.client.current_page.lower() if self.client.current_page else ""
                    if any(text in new_html for text in ["подземелье пройдено", "подземелье зачищено"]):
                        print("[*] Dungeon completed (text on new page)")
                        return "completed"
                    # Может быть редирект на standby - ждём и пробуем снова
                    time.sleep(0.5)
                    return self._start_combat(retry=retry)

        # Вариант 2: ppAction=combat
        start_btn = re.search(
            r'href=["\']([^"\']*ppAction=combat[^"\']*)["\']',
            html
        )
        if start_btn:
            start_url = start_btn.group(1).replace("&amp;", "&")
            print(f"[*] Starting combat (ppAction)...")
            resp = self.client.get(start_url)
            self.combat_url = resp.url
            return "/combat" in resp.url

        # Вариант 3: Прямая ссылка на /combat/
        combat_link = re.search(r'href="([^"]*dungeon/combat/[^"]+)"', html)
        if combat_link:
            print(f"[*] Found direct combat link")
            resp = self.client.get(combat_link.group(1))
            self.combat_url = resp.url
            return "/combat" in resp.url

        # Вариант 4: Wicket AJAX linkStartCombat
        wicket_start = re.search(
            r'"u":"([^"]*linkStartCombat[^"]*)"',
            html
        )
        if wicket_start:
            start_url = wicket_start.group(1)
            print(f"[*] Starting combat (Wicket AJAX)...")

            # Извлекаем base URL для Wicket
            base_path = self.client.current_url.split("?")[0].replace(self.base_url, "")

            headers = {
                "Wicket-Ajax": "true",
                "Wicket-Ajax-BaseURL": base_path,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "*/*",
            }

            resp = self.client.session.get(start_url, headers=headers)

            # Парсим AJAX response
            if "xml" in resp.headers.get("Content-Type", ""):
                # Ищем redirect
                redirect_match = re.search(r'<redirect>([^<]+)</redirect>', resp.text)
                if redirect_match:
                    combat_url = redirect_match.group(1)
                    print(f"[*] Redirecting to combat: {combat_url}")
                    resp = self.client.get(combat_url)
                    self.combat_url = resp.url
                    return "/combat" in resp.url

                # Ищем Loading content
                load_match = re.search(r"Loading content for .*?'([^']+)'", resp.text)
                if load_match:
                    combat_url = load_match.group(1)
                    print(f"[*] Loading combat: {combat_url}")
                    resp = self.client.get(combat_url)
                    self.combat_url = resp.url
                    return "/combat" in resp.url

        # Retry: страница могла не загрузиться полностью
        if retry < 3:
            print(f"[*] Retrying start combat ({retry + 1}/3)...")
            time.sleep(1)
            self.client.get(self.client.current_url)  # Обновляем страницу
            return self._start_combat(retry=retry + 1)

        print("[ERR] Could not start combat")
        return False

    def _make_ajax_request(self, url):
        """AJAX запрос для боя"""
        # Защита от None/javascript URLs
        if not url or url.startswith("javascript"):
            return None

        base_path = self.combat_url.split("?")[0].replace(self.base_url, "") if self.combat_url else ""

        headers = {
            "Wicket-Ajax": "true",
            "Wicket-Ajax-BaseURL": base_path.lstrip("/"),
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml, text/xml, */*; q=0.01",
            "Referer": self.combat_url or self.client.current_url,
        }
        return self.client.session.get(url, headers=headers)

    def check_and_use_stalker_seal(self):
        """
        Проверяет и использует Печать Сталкера в ивентовом бою.
        Печать появляется как device-pos-1 когда нет врагов.
        АГРЕССИВНАЯ проверка: если печать заморожена - ждём и проверяем многократно.
        Возвращает True если печать была активирована.
        """
        html = self.client.current_page
        soup = self.client.soup()
        if not soup:
            return False

        # Проверяем есть ли подсказка про Печать Сталкера
        if "применить Печать Сталкера" not in html:
            return False

        print("[EVENT] Обнаружена подсказка про Печать Сталкера!")

        # АГРЕССИВНАЯ проверка - пробуем до 10 раз с интервалом 0.5 сек
        for attempt in range(10):
            # Обновляем страницу для актуального состояния
            if attempt > 0:
                time.sleep(0.5)
                self.client.get(self.combat_url)
                html = self.client.current_page
                soup = self.client.soup()
                if not soup:
                    continue

            # Ищем кнопку Печати Сталкера (device-pos-1)
            seal_wrapper = soup.select_one(".wrap-device-link._device-pos-1")
            if not seal_wrapper:
                print(f"[EVENT] Попытка {attempt+1}/10: Кнопка Печати не найдена")
                continue

            # Проверяем, не заморожена ли (класс _freeze)
            wrapper_class = " ".join(seal_wrapper.get("class", []))
            if "_freeze" in wrapper_class:
                print(f"[EVENT] Попытка {attempt+1}/10: Печать заморожена...")
                continue

            # Печать разморожена! Ищем AJAX URL для активации
            # Паттерн: devices-0-deviceBlock-deviceLink
            device_pattern = r'"u":"([^"]*devices-0-deviceBlock[^"]*deviceLink[^"]*)"'
            device_match = re.search(device_pattern, html)

            if device_match:
                device_url = device_match.group(1)
                print("[EVENT] Печать разморожена! Активируем!")
                resp = self._make_ajax_request(device_url)
                if resp and resp.status_code == 200:
                    print("[EVENT] Печать Сталкера АКТИВИРОВАНА!")
                    time.sleep(2)
                    self.client.get(self.combat_url)
                    return True
            else:
                print(f"[EVENT] Попытка {attempt+1}/10: URL активации не найден")

        print("[EVENT] Не удалось активировать Печать за 10 попыток")
        return False

    def check_shadow_guard_tutorial(self):
        """
        Проверяет, находимся ли мы в туториале Shadow Guard (Пороги Шэдоу Гарда).
        Если видим "Голос Джека" — нужно покинуть банду, т.к. там слишком много врагов.
        Возвращает True если нажали "Покинуть банду".
        """
        html = self.client.current_page
        soup = self.client.soup()
        if not soup:
            return False

        # Проверяем наличие battlefield-lore с текстом Джека
        lore = soup.select_one("div.battlefield-lore-inner, div.lore-inner")
        if not lore:
            return False

        lore_text = lore.get_text(strip=True).lower()

        # Если это туториал Shadow Guard (Голос Джека)
        if "голос джека" not in lore_text and "джек" not in lore_text:
            return False

        print("[SHADOW] Обнаружен туториал Shadow Guard (Голос Джека) — выходим!")

        # Ищем кнопку "Покинуть банду"
        for btn in soup.select("a.go-btn"):
            btn_text = btn.get_text(strip=True)
            if "Покинуть банду" in btn_text:
                href = btn.get("href")
                if href and not href.startswith("javascript"):
                    leave_url = urljoin(self.client.current_url, href)
                    self.client.get(leave_url)
                    print("[SHADOW] Покинули Shadow Guard туториал")
                    time.sleep(2)
                    return True

        print("[SHADOW] Кнопка 'Покинуть банду' не найдена")
        return False

    def fight_until_done(self, max_actions=None):
        """Бьёмся до конца данжена"""
        # Определяем лимит действий для этого данжена
        if max_actions is None:
            max_actions = DUNGEON_ACTION_LIMITS.get(
                self.current_dungeon_id,
                DUNGEON_ACTION_LIMITS["default"]
            )
            print(f"[*] Action limit for this dungeon: {max_actions}")

        actions = 0
        stage = 1
        last_gcd_time = 0  # Глобальный КД
        skill_cooldowns = {}  # Индивидуальные КД скиллов {pos: last_use_time}
        GCD = 2.0  # Глобальный КД
        ATTACK_CD = 1.5  # Задержка между атаками
        consecutive_no_units = 0  # Счётчик попыток без юнитов

        # Индивидуальные КД скиллов (из профиля или дефолтные)
        profile_cds = get_skill_cooldowns()
        if profile_cds:
            SKILL_CDS = profile_cds
            print(f"[*] Using profile skill CDs: {SKILL_CDS}")
        else:
            # Дефолтные КД (измерено skill_cd_observer.py + 0.5s буфер)
            SKILL_CDS = {
                1: 15.5,
                2: 24.5,
                3: 39.5,
                4: 54.5,
                5: 42.5,
            }

        print(f"\n{'='*50}")
        print(f"COMBAT STARTED - Stage {stage}")
        print(f"{'='*50}")

        # Сбрасываем watchdog при входе в бой
        reset_watchdog()

        while actions < max_actions:
            # Проверяем watchdog
            if is_watchdog_triggered():
                print("[WATCHDOG] Застряли в бою! Выходим...")
                watchdog_result = check_watchdog(self.client)
                return "watchdog", actions

            # Парсим текущую страницу
            parser = CombatParser(self.client.current_page, self.client.current_url)

            # Проверяем смерть
            if self.check_death():
                print(f"\n[X] DIED after {actions} actions!")
                return "died", actions

            # Проверяем есть ли бой
            if not parser.is_battle_active():
                # Проверяем - может это следующий этап или конец?
                result = self._check_dungeon_state()
                if result == "next_stage":
                    stage += 1
                    print(f"\n{'='*50}")
                    print(f"STAGE {stage}")
                    print(f"{'='*50}")
                    continue
                elif result == "completed":
                    print(f"\n[OK] DUNGEON COMPLETED! Actions: {actions}")
                    return "completed", actions
                elif result == "died":
                    print(f"\n[X] DIED after {actions} actions!")
                    return "died", actions
                else:
                    print(f"\n[?] Unknown state after {actions} actions")
                    return "unknown", actions

            # Собираем лут с пола
            self.collect_loot()

            # Проверяем Shadow Guard туториал (Голос Джека) — выходим если обнаружен
            if self.check_shadow_guard_tutorial():
                return "shadow_guard_exit", actions

            # Проверяем Печать Сталкера (в ивенте)
            if self.check_and_use_stalker_seal():
                continue  # После активации печати продолжаем бой

            # Показываем врагов
            units = parser.get_units_info()
            if units and actions % 10 == 0:  # Каждые 10 действий
                enemies = ", ".join([u["name"] for u in units])
                print(f"[*] Enemies: {enemies}")

            # Пробуем скиллы если GCD прошёл
            now = time.time()
            if (now - last_gcd_time) >= GCD:
                ready_skills = parser.get_ready_skills()
                for skill in ready_skills:
                    pos = skill["pos"]
                    # Проверяем индивидуальный КД скилла
                    skill_cd = SKILL_CDS.get(pos, 15.0)  # Дефолт 15 сек
                    last_use = skill_cooldowns.get(pos, 0)
                    if (now - last_use) < skill_cd:
                        continue  # Этот скилл ещё на КД

                    resp = self._make_ajax_request(skill["url"])
                    if resp and resp.status_code == 200:
                        print(f"[SKILL] Used skill {pos}")
                        actions += 1
                        skill_cooldowns[pos] = time.time()
                        last_gcd_time = time.time()
                        reset_watchdog()  # Успешное действие
                        consecutive_no_units = 0
                        # Обновляем страницу
                        self.client.get(self.combat_url)
                        time.sleep(GCD)
                        break  # После одного скилла выходим, т.к. GCD

            # Атака
            attack_url = parser.get_attack_url()
            if attack_url:
                resp = self._make_ajax_request(attack_url)
                if resp and resp.status_code == 200:
                    actions += 1
                    reset_watchdog()  # Успешное действие
                    consecutive_no_units = 0
                    if actions % 5 == 0:
                        print(f"[ATTACK] #{actions}")
                    # Обновляем страницу
                    self.client.get(self.combat_url)
                    time.sleep(ATTACK_CD)
                else:
                    print(f"[ERR] Attack failed: {resp.status_code}")
                    consecutive_no_units += 1
                    if consecutive_no_units >= 40:
                        print("[WATCHDOG] 40 попыток без прогресса!")
                        return "stuck", actions
                    time.sleep(1)
            else:
                consecutive_no_units += 1
                if consecutive_no_units >= 40:
                    print("[WATCHDOG] 40 попыток без URL атаки!")
                    return "stuck", actions
                time.sleep(1)

        return "max_actions", actions

    def _check_dungeon_state(self):
        """Проверяет состояние после боя"""
        html = self.client.current_page
        url = self.client.current_url
        soup = self.client.soup()

        # Проверяем смерть
        if self.check_death():
            return "died"

        # Проверяем URL на завершение данжена
        url_lower = url.lower()
        if "dungeoncompleted" in url_lower:
            print("[*] Dungeon completed (URL)")
            return "completed"

        if "dungeon/landing" in url_lower or "/dungeons" in url_lower:
            return "completed"

        # Проверяем текст заголовков на статус
        if soup:
            for h2 in soup.select("h2, h2 span"):
                text = h2.get_text(strip=True).lower()
                if "пройден" in text or "зачищен" in text:
                    if "этап" in text:
                        print(f"[*] Stage complete: {text}")
                        # Этап пройден - ищем кнопку продолжения
                        break
                    elif "подземелье" in text:
                        print(f"[*] Dungeon complete: {text}")
                        return "completed"

        # Проверяем URL - на странице между этапами (step)
        if "/dungeon/step/" in url:
            # Это интерстеп страница - ищем кнопку "Продолжить бой"
            if soup:
                for btn in soup.select("a.go-btn"):
                    btn_text = btn.get_text(strip=True)
                    href = btn.get("href", "")
                    if "Продолжить бой" in btn_text and href and not href.startswith("javascript"):
                        print(f"[*] Interstep: clicking 'Продолжить бой'")
                        resp = self.client.get(href)
                        if "/combat" in resp.url:
                            self.combat_url = resp.url
                            return "next_stage"
                        # Может потребоваться запустить бой
                        result = self._start_combat()
                        if result == "completed":
                            return "completed"
                        if result:
                            return "next_stage"

        # Проверяем URL - всё ещё в бою
        if "/combat" in url:
            # Всё ещё на странице боя - возможно загрузка
            time.sleep(1)
            self.client.get(self.combat_url)
            return "continue"

        # Ищем кнопку "Продолжить бой" по тексту (главный способ)
        if soup:
            for btn in soup.select("a.go-btn"):
                btn_text = btn.get_text(strip=True)
                href = btn.get("href", "")
                if "Продолжить бой" in btn_text and href and href != "#" and not href.startswith("javascript"):
                    print(f"[*] Found 'Продолжить бой' -> clicking")
                    resp = self.client.get(href)
                    if "/combat" in resp.url:
                        self.combat_url = resp.url
                        return "next_stage"
                    # Проверяем - может данжен завершён после клика
                    resp_url_lower = resp.url.lower()
                    if "dungeoncompleted" in resp_url_lower:
                        print("[*] Dungeon completed after clicking 'Продолжить бой'")
                        return "completed"
                    new_html = self.client.current_page.lower() if self.client.current_page else ""
                    if any(text in new_html for text in ["подземелье пройдено", "подземелье зачищено"]):
                        print("[*] Dungeon completed (text)")
                        return "completed"
                    # Рекурсивно проверяем новую страницу
                    result = self._start_combat()
                    if result == "completed":
                        return "completed"
                    if result:
                        return "next_stage"

        # Ищем кнопку "Продолжить" или "Следующий этап" по href
        next_btn = re.search(
            r'href=["\']([^"\']*(?:ppAction=combat|nextStep|/step/)[^"\']*)["\']',
            html,
            re.IGNORECASE
        )
        if next_btn:
            next_url = next_btn.group(1).replace("&amp;", "&")
            if not next_url.startswith("javascript"):
                print(f"[*] Found next stage button (href)")
                resp = self.client.get(next_url)

                # Если это уже combat - отлично
                if "/combat" in resp.url:
                    self.combat_url = resp.url
                    return "next_stage"

                # Иначе нужно снова запустить бой (standby/step page)
                result = self._start_combat()
                if result == "completed":
                    return "completed"
                if result:
                    return "next_stage"

        # Ищем Wicket AJAX для следующего этапа
        wicket_next = re.search(r'"u":"([^"]*(?:linkStartCombat|nextStep)[^"]*)"', html)
        if wicket_next:
            print(f"[*] Found Wicket next stage")
            result = self._start_combat()
            if result == "completed":
                return "completed"
            if result:
                return "next_stage"

        # Ищем текст о завершении
        html_lower = html.lower()
        if any(text in html_lower for text in ["подземелье пройдено", "подземелье зачищено", "dungeon complete"]):
            return "completed"

        # Ищем кнопку выхода или "В город"
        if soup:
            for btn in soup.select("a.go-btn"):
                btn_text = btn.get_text(strip=True)
                if btn_text in ["В город", "Выйти", "Покинуть"]:
                    return "completed"

        # Проверяем landing page - значит данжен завершён
        if "/landing" in url:
            return "completed"

        # Сохраняем для дебага
        debug_path = os.path.join(SCRIPT_DIR, "debug_unknown_state.html")
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[DEBUG] Saved unknown state to {debug_path}")
        print(f"[DEBUG] Current URL: {url}")

        return "unknown"


def main():
    print("=" * 50)
    print("VMMO Dungeon Runner - All Dungeons")
    print("=" * 50)

    # Авторизуемся
    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            return

    runner = DungeonRunner(client)

    # Статистика
    stats = {"completed": 0, "died": 0, "failed": 0, "total_actions": 0}

    while True:
        # Получаем список доступных данженов
        dungeons, api_link_url = runner.get_all_available_dungeons("tab2")

        if not dungeons:
            print("\n" + "=" * 50)
            print("ALL DUNGEONS ON COOLDOWN!")
            print(f"Stats: {stats['completed']} completed, {stats['died']} deaths, {stats['failed']} failed")
            print(f"Total actions: {stats['total_actions']}")
            print("=" * 50)
            break

        # Берём первый доступный
        dungeon = dungeons[0]
        print(f"\n{'#'*50}")
        print(f"# Starting: {dungeon['name']}")
        print(f"# Remaining: {len(dungeons)} dungeons")
        print(f"{'#'*50}")

        # Входим в данжен
        if not runner.enter_dungeon(dungeon["id"], api_link_url):
            print(f"[ERR] Failed to enter {dungeon['name']}")
            stats["failed"] += 1
            time.sleep(2)
            continue

        # Бьёмся до конца
        result, actions = runner.fight_until_done(max_actions=300)
        stats["total_actions"] += actions

        if result == "completed":
            stats["completed"] += 1
            print(f"[OK] {dungeon['name']} completed in {actions} actions")

        elif result == "died":
            stats["died"] += 1
            print(f"[X] Died in {dungeon['name']} after {actions} actions")

            # Воскрешаемся и продолжаем
            if runner.resurrect():
                print("[*] Continuing to next dungeon...")
            else:
                print("[ERR] Could not resurrect, stopping")
                break

        else:
            stats["failed"] += 1
            print(f"[?] Unknown result in {dungeon['name']}: {result}")
            # Возвращаемся в город чтобы восстановить состояние
            client.get("/city")

        # Небольшая пауза между данженами
        time.sleep(2)

    print("\n" + "=" * 50)
    print("FINAL STATS:")
    print(f"  Completed: {stats['completed']}")
    print(f"  Deaths: {stats['died']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Total actions: {stats['total_actions']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
