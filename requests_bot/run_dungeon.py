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
from requests_bot.config import (
    BASE_URL, SKIP_DUNGEONS, DUNGEON_ACTION_LIMITS, SCRIPT_DIR,
    get_skill_cooldowns, get_dungeon_difficulty, get_skill_hp_threshold,
    load_deaths, get_extra_dungeons
)
from requests_bot import config as config_module  # Для доступа к ONLY_DUNGEONS
from requests_bot.logger import log_info, log_debug, log_error


class DungeonRunner:
    """Полное прохождение данжена"""

    def __init__(self, client: VMMOClient):
        self.client = client
        self.base_url = BASE_URL
        self.combat_url = None
        self.page_id = None
        self.current_dungeon_id = None  # Текущий данжен для лимитов
        self.current_difficulty = "brutal"  # Текущая сложность
        self.collected_loot = set()  # ID собранного лута
        self.loot_take_url = None  # Сохраняем URL для сбора лута из начальной боевой страницы
        self.report_back_url = None  # URL для activity reporter (lnkReportBack)
        self.last_report_back_time = 0  # Время последнего report back
        self.metronome_url = None  # URL для metronome heartbeat
        self.last_metronome_time = 0  # Время последнего metronome
        self.metronome_count = 0  # Счётчик пульсов metronome (dls параметр)
        self.refresher_url = None  # URL для refresher (сбор лута)
        self.attack_count = 0  # Счётчик атак для периодического сбора лута

    def _save_loot_url_from_combat_page(self):
        """Сохраняет lootTakeUrl из страницы боя"""
        html = self.client.current_page
        if not html:
            return

        # Сохраняем lootTakeUrl
        loot_url_match = re.search(r"lootTakeUrl\s*=\s*['\"]([^'\"]+)['\"]", html)
        loot_url = loot_url_match.group(1) if loot_url_match else None
        if loot_url:
            self.loot_take_url = loot_url
            log_debug(f"[LOOT] Saved loot URL")
        else:
            log_error(f"[LOOT] WARNING: lootTakeUrl NOT FOUND!")

        # КРИТИЧНО: Отправляем "page rendered ping" - это активирует отправку лута!
        # Браузер отправляет этот запрос после рендеринга страницы
        # Формат: ptxPageRenderedPingUrl = 'URL?pageId-IEndpointBehaviorListener.5-&params'
        page_rendered_match = re.search(r"ptxPageRenderedPingUrl\s*=\s*'([^']+)'", html)
        if page_rendered_match:
            page_rendered_url = page_rendered_match.group(1)
            try:
                resp = self.client.session.get(page_rendered_url, timeout=5)
                log_debug(f"[LOOT] Page rendered ping: {resp.status_code}")
            except Exception as e:
                log_error(f"[LOOT] Page rendered ping failed: {e}")

        # Сохраняем URL для activity reporter (lnkReportBack)
        # Браузер периодически отправляет этот запрос чтобы сообщить серверу об активности
        # Формат: IBehaviorListener.0-combatPanel-container-lnkReportBack
        report_back_match = re.search(r'"u":"([^"]*lnkReportBack[^"]*)"', html)
        if report_back_match:
            self.report_back_url = report_back_match.group(1)

        # Сохраняем URL для metronome heartbeat
        # КРИТИЧНО: Браузер отправляет metronome каждые ~1-2 секунды
        # Формат: IEndpointBehaviorListener.1-combatPanel-container с ctx=metronome
        # Ищем pageId из URL для формирования metronome URL
        page_id_match = re.search(r"ptxPageId\s*=\s*(\d+)", html)
        if page_id_match:
            page_id = page_id_match.group(1)
            # Формируем базовый URL для metronome
            # Пример: /dungeon/combat/dSanctuary?1362-IEndpointBehaviorListener.1-combatPanel-container&1=normal
            combat_base = self.combat_url.split("?")[0] if self.combat_url else ""
            difficulty_match = re.search(r"1=(normal|hard|impossible)", self.combat_url or "")
            difficulty_param = f"1={difficulty_match.group(1)}" if difficulty_match else "1=normal"
            self.metronome_url = f"{combat_base}?{page_id}-IEndpointBehaviorListener.1-combatPanel-container&{difficulty_param}"
            self.metronome_count = 0  # Сбрасываем счётчик
            # Сохраняем page_id для refresher
            self.page_id = page_id
            # Формируем refresher URL для сбора лута
            # Формат: dungeon/combat/XXX?{pageId}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher&1=normal
            self.refresher_url = f"{combat_base}?{page_id}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher&{difficulty_param}"
            self.attack_count = 0  # Сбрасываем счётчик атак

    def _collect_loot(self, ajax_response=None):
        """Собирает лут из AJAX-ответа или текущей страницы

        Args:
            ajax_response: requests.Response от AJAX-запроса (приоритет)
                          Если None - используем self.client.current_page
        """
        # AJAX-ответ содержит лут, current_page - нет (он не обновляется после AJAX)
        if ajax_response is not None:
            try:
                html = ajax_response.text
            except:
                html = None
        else:
            html = self.client.current_page

        if not html:
            return 0

        # Используем сохранённый loot_url (из начальной страницы боя)
        # lootTakeUrl приходит только при первой загрузке, не в AJAX-ответах
        loot_url = self.loot_take_url
        if not loot_url:
            # Fallback: пробуем найти в текущей странице (вдруг это полная загрузка)
            # Формат: Ptx.Shadows.Combat.lootTakeUrl = 'URL'
            loot_url_match = re.search(r"lootTakeUrl\s*=\s*['\"]([^'\"]+)['\"]", html)
            if loot_url_match:
                loot_url = loot_url_match.group(1)
                self.loot_take_url = loot_url  # Сохраняем для будущих вызовов

        # Ищем ID лута двумя способами
        loot_ids = set()
        # HTML: <div id="loot_box_77322"
        loot_ids.update(re.findall(r'id="loot_box_(\d+)"', html))
        # JS: dropLoot({id: '77322'
        loot_ids.update(re.findall(r"dropLoot\s*\(\s*\{[^}]*id:\s*'(\d+)'", html))

        # DEBUG: логируем что нашли
        if loot_ids:
            new_loot = loot_ids - self.collected_loot
            if new_loot:
                log_info(f"[LOOT] Найдено {len(new_loot)} новых: {new_loot}")

        # Если есть лут но нет URL - логируем проблему
        if loot_ids and not loot_url:
            log_error(f"[LOOT] НАЙДЕН ЛУТ ({len(loot_ids)} шт) НО НЕТ loot_url! IDs: {loot_ids}")
            return 0

        if not loot_url:
            return 0

        collected = 0
        for loot_id in loot_ids:
            if loot_id not in self.collected_loot:
                collect_url = loot_url + loot_id
                self.client.get(collect_url)
                self.collected_loot.add(loot_id)
                collected += 1
                log_info(f"[LOOT] Собран: {loot_id}")

        return collected

    def _collect_loot_from_ajax(self, ajax_text):
        """
        Собирает лут из AJAX-ответа атаки.

        Лут приходит в теге <evaluate> как:
        Ptx.Shadows.Combat.dropLoot({
            id: '3643008',
            type: 1,
            img: '/images/items/icons/...',
            ...
        });
        """
        if not ajax_text:
            return 0

        # Ищем dropLoot вызовы в AJAX ответе
        # Паттерн: dropLoot({id: '12345', ...}) - [\s\S]*? для многострочного матча
        loot_matches = re.findall(r"dropLoot\s*\(\s*\{[\s\S]*?id:\s*'(\d+)'", ajax_text)

        # Дебаг: проверяем есть ли dropLoot в ответе вообще
        if "dropLoot" in ajax_text:
            log_info(f"[LOOT] AJAX содержит dropLoot! Найдено ID: {loot_matches}")
            if not loot_matches:
                # Сохраняем для дебага
                debug_path = os.path.join(SCRIPT_DIR, "debug_ajax_with_loot.xml")
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(ajax_text)
                log_error(f"[LOOT] dropLoot найден но regex не сработал! Saved to {debug_path}")

        if not loot_matches:
            return 0

        loot_url = self.loot_take_url
        if not loot_url:
            log_error(f"[LOOT] AJAX содержит лут ({len(loot_matches)} шт) но нет loot_url!")
            return 0

        collected = 0
        for loot_id in loot_matches:
            if loot_id not in self.collected_loot:
                collect_url = loot_url + loot_id
                try:
                    self.client.session.get(collect_url)  # Быстрый GET без сохранения страницы
                    self.collected_loot.add(loot_id)
                    collected += 1
                    log_info(f"[LOOT] Собран из AJAX: {loot_id}")
                except Exception as e:
                    log_error(f"[LOOT] Ошибка сбора {loot_id}: {e}")

        return collected

    def _collect_loot_via_refresher(self):
        """Собирает лут через refresher endpoint (основной метод сбора)

        Лут в VMMO приходит через refresher, а не через WebSocket/AJAX атаки.
        Браузер вызывает refresher каждые 500ms, мы вызываем каждые 3 атаки.

        Returns:
            int: Количество собранного лута
        """
        if not self.refresher_url:
            return 0

        try:
            # Вызываем refresher
            resp = self.client.session.get(self.refresher_url, timeout=10)
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
                        self.client.session.get(take_url, timeout=5)
                        self.collected_loot.add(loot_id)
                        collected += 1
                        log_info(f"[LOOT] Собран: {loot_id}")
                    except Exception as e:
                        log_error(f"[LOOT ERROR] {e}")

            return collected

        except Exception as e:
            log_error(f"[REFRESHER ERROR] {e}")
            return 0

    def _set_difficulty(self, target="brutal"):
        """
        Устанавливает нужную сложность.

        Args:
            target: 'brutal', 'hero', или 'normal'

        Сложности идут по кругу: Норма -> Брутал -> Герой -> Норма...
        Левая стрелка: Норма -> Брутал -> Герой
        Правая стрелка: Норма <- Брутал <- Герой
        """
        # Маппинг русских названий
        target_map = {
            "brutal": "брутал",
            "hero": "герой",
            "normal": "норма",
        }
        target_ru = target_map.get(target, "брутал")

        max_attempts = 10  # Защита от бесконечного цикла

        for attempt in range(max_attempts):
            soup = self.client.soup()
            if not soup:
                break

            # Получаем текущую сложность
            level_text = soup.select_one(".switch-level-text")
            current_level = level_text.get_text(strip=True).lower() if level_text else ""

            # Если уже нужная сложность - останавливаемся
            if target_ru in current_level:
                print(f"[*] Сложность: {current_level.title()}")
                self.current_difficulty = target
                return

            # Ищем кнопку переключения (левая стрелка для повышения)
            switch_left = soup.select_one("a.switch-level-left")
            if not switch_left:
                # Нет кнопки - данжен не поддерживает переключение (только Норма)
                print(f"[*] Сложность: {current_level.title()} (без переключения)")
                self.current_difficulty = "normal"
                return

            href = switch_left.get("href")
            if not href:
                break

            print(f"[*] Переключаю: {current_level.title()} -> ...")
            self.client.get(href)

        # Показываем итоговую сложность
        soup = self.client.soup()
        if soup:
            level_text = soup.select_one(".switch-level-text")
            if level_text:
                final_level = level_text.get_text(strip=True)
                print(f"[*] Сложность: {final_level}")
                # Определяем текущую сложность
                if "брутал" in final_level.lower():
                    self.current_difficulty = "brutal"
                elif "герой" in final_level.lower():
                    self.current_difficulty = "hero"
                else:
                    self.current_difficulty = "normal"

    def get_all_available_dungeons(self, section_id=None):
        """Получает список всех доступных данженов из всех вкладок в dungeon_tabs"""
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

        # Получаем список вкладок из конфига (по умолчанию tab2)
        from requests_bot.config import get_dungeon_tabs
        tabs_to_load = get_dungeon_tabs() if section_id is None else [section_id]

        all_dungeons = []

        # Загружаем все вкладки
        for tab in tabs_to_load:
            section_url = f"{api_section_url}&section_id={tab}"
            dungeons_resp = self.client.session.get(section_url, headers=headers)
            try:
                data = dungeons_resp.json()
                tab_dungeons = data.get("section", {}).get("dungeons", [])
                all_dungeons.extend(tab_dungeons)
            except Exception as e:
                print(f"[WARN] Failed to load tab {tab}: {e}")

        available = []

        try:

            # Загружаем актуальный список скипнутых данжей из deaths.json
            deaths = load_deaths()
            skipped_ids = set(SKIP_DUNGEONS)  # Из конфига
            for dungeon_id, data in deaths.items():
                if data.get("skipped") or data.get("current_difficulty") == "skip":
                    skipped_ids.add(dungeon_id)

            for d in all_dungeons:
                cooldown = d.get("cooldown", 0)
                name = d.get("name", "?").replace("<br>", " ")
                dng_id = d.get("id")

                if cooldown:
                    pass  # На КД - не логируем
                elif dng_id in skipped_ids:
                    pass  # Скипнут - не логируем
                elif config_module.ONLY_DUNGEONS and dng_id not in config_module.ONLY_DUNGEONS:
                    pass  # Не в списке - не логируем
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

        if not html:
            return False

        # Проверяем URL на смерть
        if "/dead" in url or "/death" in url:
            return True

        # Проверяем модальное окно смерти (как в Playwright)
        if "battlefield-modal" in html and "_fail" in html:
            return True

        # Проверяем класс _death-hero (мобильная версия)
        if "_death-hero" in html:
            return True

        # Проверяем текст
        html_lower = html.lower()
        death_texts = [
            "вы погибли", "вы мертвы", "персонаж мёртв",
            "ты пала в сражении", "ты пал в сражении",
            "you died", "you are dead"
        ]
        if any(text in html_lower for text in death_texts):
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

    def click_continue_if_needed(self):
        """
        Проверяет наличие кнопки "Продолжить" на странице завершения данжена.
        Некоторые данжены (напр. Владения Барона) показывают эту кнопку после победы.
        Без нажатия на неё персонаж остаётся в банде.
        """
        html = self.client.current_page
        if not html:
            return False

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Ищем кнопку "Продолжить" (не "Продолжить бой"!)
        for btn in soup.select("a.go-btn"):
            btn_text = btn.get_text(strip=True)
            if btn_text == "Продолжить":
                href = btn.get("href", "")
                if href:
                    print("[*] Найдена кнопка 'Продолжить', нажимаю...")
                    try:
                        self.client.get(href)
                        time.sleep(0.5)
                        print("[OK] Нажата кнопка 'Продолжить'")
                        return True
                    except Exception as e:
                        print(f"[ERR] Ошибка нажатия 'Продолжить': {e}")
                        return False

        return False

    def ensure_out_of_dungeon(self):
        """
        Гарантирует выход из данжена.
        Вызывается после завершения данжена для надёжности.
        """
        # Проверяем кнопку "Продолжить" на странице завершения
        self.click_continue_if_needed()

        # Переходим в город для гарантии
        try:
            self.client.get("/city")
            time.sleep(0.3)
        except Exception:
            pass

    def enter_dungeon(self, dungeon_id, api_link_url):
        """Входит в данжен и начинает бой"""
        print(f"\n[*] Entering dungeon: {dungeon_id}")
        self.current_dungeon_id = dungeon_id  # Сохраняем для лимитов
        self.collected_loot.clear()  # Очищаем лут от предыдущего данжена
        self.loot_take_url = None  # Сбрасываем URL лута

        # Проверяем и ремонтируем снаряжение перед входом
        try:
            if self.client.repair_equipment():
                print("[*] Снаряжение отремонтировано перед данженом")
        except Exception as e:
            print(f"[*] Ошибка проверки ремонта: {e}")

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

        # 3. Устанавливаем сложность (по умолчанию Брутал, но снижается после смертей)
        target_difficulty = get_dungeon_difficulty(dungeon_id)
        self._set_difficulty(target_difficulty)

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
        # "stuck" - баг игры, кнопка не работает - пропускаем данж
        # "died" - подземелье закрыто (смерть без воскрешения)
        if result == "stuck":
            return "stuck"
        if result == "died":
            return "died"
        return result == True or result == "completed"

    def _start_combat(self, retry=0):
        """Начинает бой из lobby/standby/step страницы"""
        html = self.client.current_page
        soup = self.client.soup()
        current_url = self.client.current_url or ""

        # Проверяем "Подземелье закрыто" (смерть без воскрешения)
        if "DungeonClosedPage" in current_url or "Подземелье закрыто" in (html or ""):
            print("[*] Подземелье закрыто (смерть без воскрешения)")
            # Пробуем покинуть банду
            leave_url = self._find_leave_party_url()
            if leave_url:
                print("[*] Покидаем банду после смерти...")
                self.client.get(leave_url)
                time.sleep(1)
            return "died"

        # Проверяем сначала - может данжен уже завершён
        url_lower = current_url.lower()
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
                        self._save_loot_url_from_combat_page()
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
            self._save_loot_url_from_combat_page()
            return "/combat" in resp.url

        # Вариант 3: Прямая ссылка на /combat/
        combat_link = re.search(r'href="([^"]*dungeon/combat/[^"]+)"', html)
        if combat_link:
            print(f"[*] Found direct combat link")
            resp = self.client.get(combat_link.group(1))
            self.combat_url = resp.url
            self._save_loot_url_from_combat_page()
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
                    self._save_loot_url_from_combat_page()
                    return "/combat" in resp.url

                # Ищем Loading content
                load_match = re.search(r"Loading content for .*?'([^']+)'", resp.text)
                if load_match:
                    combat_url = load_match.group(1)
                    print(f"[*] Loading combat: {combat_url}")
                    resp = self.client.get(combat_url)
                    self.combat_url = resp.url
                    self._save_loot_url_from_combat_page()
                    return "/combat" in resp.url

        # Retry: страница могла не загрузиться полностью
        if retry < 3:
            print(f"[*] Retrying start combat ({retry + 1}/3)...")
            time.sleep(1)
            self.client.get(self.client.current_url)  # Обновляем страницу
            return self._start_combat(retry=retry + 1)

        # Баг игры: кнопка "Начать бой!" без AJAX обработчика (Пороги Шэдоу Гарда)
        # Пробуем покинуть банду и вернуться к списку данжей
        current_url = self.client.current_url or ""
        print(f"[DEBUG] Current URL after retries: {current_url}")

        if "/dungeon/lobby/" in current_url:
            leave_url = self._find_leave_party_url()
            print(f"[DEBUG] Leave party URL: {leave_url}")
            if leave_url:
                print("[*] Застряли в lobby (баг игры). Покидаем банду...")
                resp = self.client.get(leave_url)
                time.sleep(1)
                # Возвращаем "stuck" чтобы бот знал что нужно пропустить этот данж
                return "stuck"
            else:
                print("[*] Застряли в lobby, но кнопка 'Покинуть банду' не найдена")
                # Пробуем просто перейти в город
                self.client.get(f"{self.base_url}/city")
                return "stuck"

        print("[ERR] Could not start combat")
        return False

    def _find_leave_party_url(self):
        """Ищет URL для кнопки 'Покинуть банду' в лобби"""
        html = self.client.current_page
        if not html:
            return None

        # Ищем ссылку с ppAction=leaveParty
        match = re.search(r'href="([^"]*ppAction=leaveParty[^"]*)"', html)
        if match:
            url = match.group(1).replace("&amp;", "&")
            if not url.startswith("http"):
                url = self.base_url + url
            return url
        return None

    def _make_ajax_request(self, url):
        """AJAX запрос для боя"""
        # Защита от None/javascript URLs
        if not url or url.startswith("javascript"):
            return None

        base_path = self.combat_url.split("?")[0].replace(self.base_url, "") if self.combat_url else ""

        # Добавляем timestamp и tmt как браузер
        import random
        timestamp = int(time.time() * 1000)
        tmt = random.randint(10, 50)  # Браузер шлёт примерно такие значения

        # Добавляем параметры к URL
        separator = "&" if "?" in url else "?"
        url_with_params = f"{url}{separator}_={timestamp}&tmt={tmt}"

        headers = {
            "Wicket-Ajax": "true",
            "Wicket-Ajax-BaseURL": base_path.lstrip("/"),
            "Wicket-FocusedElementId": "ptx_combat_rich2_attack_link",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml, text/xml, */*; q=0.01",
            "Referer": self.combat_url or self.client.current_url,
        }
        return self.client.session.get(url_with_params, headers=headers)

    def _send_activity_report(self):
        """
        Отправляет activity report серверу (lnkReportBack).
        Браузер отправляет этот запрос периодически чтобы сообщить серверу об активности.
        Без этого сервер может считать клиента неактивным и не отправлять лут.
        """
        if not self.report_back_url:
            return

        now = time.time()
        # Отправляем не чаще чем раз в 3 секунды
        if now - self.last_report_back_time < 3:
            return

        try:
            base_path = self.combat_url.split("?")[0].replace(self.base_url, "") if self.combat_url else ""
            timestamp = int(now * 1000)

            headers = {
                "Wicket-Ajax": "true",
                "Wicket-Ajax-BaseURL": base_path.lstrip("/"),
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/xml, text/xml, */*; q=0.01",
                "Referer": self.combat_url or self.client.current_url,
            }

            url = f"{self.report_back_url}&_={timestamp}"
            self.client.session.get(url, headers=headers, timeout=5)
            self.last_report_back_time = now
            log_debug("[LOOT] Activity report sent")
        except Exception as e:
            log_debug(f"[LOOT] Activity report failed: {e}")

    def _send_metronome(self):
        """
        Отправляет metronome heartbeat серверу.
        КРИТИЧНО: Браузер отправляет это каждые 1-2 секунды!
        Без этого сервер считает клиента неактивным и НЕ отправляет лут через WebSocket.

        Формат запроса:
        ?pageId-IEndpointBehaviorListener.1-combatPanel-container&1=normal&tmt=-1006&ctx=metronome&dls=3&tmgs=&stteHdn=false
        """
        if not self.metronome_url:
            return

        now = time.time()
        # Отправляем каждые 1.5 секунды (браузер шлёт каждые 1-2 сек)
        if now - self.last_metronome_time < 1.5:
            return

        try:
            import random
            self.metronome_count += 1
            # tmt - какой-то timing, браузер шлёт отрицательные значения
            tmt = random.randint(-2000, -500)

            # Формируем URL с параметрами metronome
            url = f"{self.metronome_url}&tmt={tmt}&ctx=metronome&dls={self.metronome_count}&tmgs=&stteHdn=false"

            headers = {
                "Accept": "application/json,text/html,application/xhtml+xml,application/xml",
                "Referer": f"{self.base_url}/scripts/combat_callback.js",
            }

            resp = self.client.session.get(url, headers=headers, timeout=5)
            self.last_metronome_time = now

            # Проверяем ответ
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get("status") == "OK":
                        log_debug(f"[LOOT] Metronome OK (dls={self.metronome_count})")
                    else:
                        log_debug(f"[LOOT] Metronome response: {data}")
                except:
                    log_debug(f"[LOOT] Metronome sent (non-JSON response)")
        except Exception as e:
            log_debug(f"[LOOT] Metronome failed: {e}")

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
        GCD = 2.0  # Глобальный КД
        ATTACK_CD = 0.6  # Задержка между атаками
        consecutive_no_units = 0  # Счётчик попыток без юнитов

        print(f"\n{'='*50}")
        print(f"COMBAT STARTED - Stage {stage}")
        print(f"{'='*50}")

        # Сбрасываем watchdog при входе в бой
        reset_watchdog()

        return self._combat_loop(
            max_actions, actions, stage, last_gcd_time,
            GCD, ATTACK_CD, consecutive_no_units
        )

    def _combat_loop(self, max_actions, actions, stage, last_gcd_time,
                     GCD, ATTACK_CD, consecutive_no_units):
        """Внутренний цикл боя"""
        while actions < max_actions:
            # КРИТИЧНО: Отправляем metronome heartbeat - без этого сервер не шлёт лут!
            self._send_metronome()

            # Отправляем activity report - сервер должен знать что клиент активен
            self._send_activity_report()

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
                    # Гарантируем выход из банды/данжена
                    self.ensure_out_of_dungeon()
                    return "completed", actions
                elif result == "died":
                    print(f"\n[X] DIED after {actions} actions!")
                    return "died", actions
                else:
                    print(f"\n[?] Unknown state after {actions} actions")
                    return "unknown", actions

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
            skill_used = False
            if (now - last_gcd_time) >= GCD:
                ready_skills = parser.get_ready_skills()
                # Получаем HP врага и пороги скиллов
                enemy_hp = parser.get_enemy_hp()
                hp_thresholds = get_skill_hp_threshold()

                for skill in ready_skills:
                    pos = skill["pos"]
                    # КД скилла проверяется динамически в parser.get_ready_skills() из HTML
                    # Дополнительная проверка статичных КД из конфига больше НЕ нужна

                    # Проверяем порог HP для этого скилла
                    if pos in hp_thresholds:
                        min_hp = hp_thresholds[pos]
                        if enemy_hp < min_hp:
                            continue  # HP врага ниже порога, пропускаем скилл

                    resp = self._make_ajax_request(skill["url"])
                    if resp and resp.status_code == 200:
                        print(f"[SKILL] Used skill {pos} (enemy HP: {enemy_hp})")
                        actions += 1
                        last_gcd_time = time.time()
                        reset_watchdog()  # Успешное действие
                        consecutive_no_units = 0
                        # Обновляем страницу для следующего действия
                        self.client.get(self.combat_url)
                        # Увеличиваем счётчик атак и собираем лут через refresher каждые 3 атаки
                        self.attack_count += 1
                        if self.attack_count % 3 == 0:
                            self._collect_loot_via_refresher()
                        time.sleep(GCD)
                        skill_used = True
                        break  # После одного скилла выходим, т.к. GCD

            # После скилла пропускаем атаку - возвращаемся к началу цикла
            if skill_used:
                continue

            # Атака
            action_url = parser.get_attack_url()

            if action_url:
                resp = self._make_ajax_request(action_url)
                if resp and resp.status_code == 200:
                    actions += 1
                    reset_watchdog()  # Успешное действие
                    consecutive_no_units = 0
                    if actions % 5 == 0:
                        print(f"[ATTACK] #{actions}")
                    # Обновляем страницу для следующего действия
                    self.client.get(self.combat_url)
                    # Увеличиваем счётчик атак и собираем лут через refresher каждые 3 атаки
                    self.attack_count += 1
                    if self.attack_count % 3 == 0:
                        self._collect_loot_via_refresher()
                    time.sleep(ATTACK_CD)
                else:
                    print(f"[ERR] Attack failed")
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
        # Финальный сбор лута через refresher (когда все враги убиты)
        collected = self._collect_loot_via_refresher()
        if collected > 0:
            log_info(f"[LOOT] Собрано в конце боя: {collected} предметов")

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
                            self._save_loot_url_from_combat_page()
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
                        self._save_loot_url_from_combat_page()
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
                    # Пробуем запустить бой (один раз, без рекурсии)
                    result = self._start_combat(retry=2)  # retry=2 чтобы не было глубокой рекурсии
                    if result == "completed":
                        return "completed"
                    if result:
                        return "next_stage"
                    # Не смогли - выходим из цикла
                    break

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
                    self._save_loot_url_from_combat_page()
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
        dungeons, api_link_url = runner.get_all_available_dungeons()

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
