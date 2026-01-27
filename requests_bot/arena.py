"""
Модуль для PvP арены.

Flow:
1. GET /pvp/select - страница выбора арены
2. Проверяем сколько боёв осталось (парсим "за X боев")
3. GET /pvp/select?ppAction=pvpGo&arena=arena1r2&bet=0 - встаём в очередь
4. Поллим страницу пока не появится кнопка "На арену" (arenaLink + PVP_Enter)
5. GET arenaLink - переходим на арену
6. GET /pvp/ready - предбой (ждём 10 сек или пока не редирект на combat)
7. Бой через combat.py
8. GET /pvp/result - результаты
9. Если боёв > MIN_FIGHTS: GET ppAction=pvpAgain
"""

import re
import time
from typing import Optional, Tuple

try:
    from requests_bot.logger import log_info, log_debug, log_warning, log_error
    from requests_bot.config import LOOT_COLLECT_INTERVAL
except ImportError:
    def log_info(msg): print(f"[INFO] {msg}")
    def log_debug(msg): print(f"[DEBUG] {msg}")
    def log_warning(msg): print(f"[WARN] {msg}")
    def log_error(msg): print(f"[ERROR] {msg}")
    LOOT_COLLECT_INTERVAL = 3


# Минимум боёв оставляем (не тратим все)
MIN_FIGHTS_LEFT = 5

# Типы арен
ARENA_TYPES = {
    "duel": "arena1r2",      # Дуэльная 1x1
    "duel2": "arena2r2",     # Дуэльная 2x2 (?)
    "circular": "arena3",    # Круговая (?)
}

# Таймауты
QUEUE_TIMEOUT = 60          # Макс ожидание в очереди (сек)
QUEUE_POLL_INTERVAL = 3     # Интервал проверки очереди
READY_WAIT = 12             # Ожидание на странице предбоя
CD_WAIT = 30                # Ожидание если кнопки заблокированы (КД после боя)
CD_MAX_RETRIES = 5          # Макс попыток дождаться КД


class ArenaClient:
    """Клиент для PvP арены."""

    def __init__(self, client):
        """
        Args:
            client: VMMOClient с активной сессией
        """
        self.client = client
        self.session = client.session
        self.base_url = "https://vmmo.vten.ru"

        # Для сбора лута через refresher
        self.refresher_url = None
        self.loot_take_url = None
        self.collected_loot = set()
        self.attack_count = 0

    def _setup_refresher_url(self, html: str, combat_url: str):
        """Настраивает refresher URL для сбора лута"""
        # Ищем page_id
        page_id_match = re.search(r'ptxPageId\s*=\s*(\d+)', html)
        if not page_id_match:
            log_debug("[ARENA] page_id не найден для refresher")
            return

        page_id = page_id_match.group(1)

        # Формируем refresher URL
        # Формат: /pvp/combat?{pageId}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher
        base_path = combat_url.split("?")[0]
        self.refresher_url = f"{base_path}?{page_id}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher"

        # Ищем loot_take_url
        loot_match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", html)
        if loot_match:
            self.loot_take_url = loot_match.group(1)

        log_debug(f"[ARENA] Refresher настроен: page_id={page_id}")
        self.collected_loot.clear()
        self.attack_count = 0

    def _collect_loot_via_refresher(self):
        """Собирает лут через refresher endpoint"""
        if not self.refresher_url:
            return 0

        try:
            resp = self.session.get(self.refresher_url, timeout=10)
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
                        self.session.get(take_url, timeout=5)
                        self.collected_loot.add(loot_id)
                        collected += 1
                        log_info(f"[ARENA LOOT] Собран: {loot_id}")
                    except Exception as e:
                        log_error(f"[ARENA LOOT ERROR] {e}")

            return collected

        except Exception as e:
            log_debug(f"[ARENA REFRESHER ERROR] {e}")
            return 0

    def get_fights_remaining(self, html: Optional[str] = None) -> int:
        """
        Получает количество оставшихся боёв за очки.

        Args:
            html: HTML страницы (если None - загрузит /pvp/select)

        Returns:
            int: Количество боёв (0 если не удалось распарсить)
        """
        if html is None:
            resp = self.session.get(f"{self.base_url}/pvp/select")
            if resp.status_code != 200:
                log_error(f"[ARENA] Не удалось загрузить /pvp/select: {resp.status_code}")
                return 0
            html = resp.text
            log_debug(f"[ARENA] URL: {resp.url}")

        # Парсим "за X боев" или "за X боя" или "за X бой"
        # Сегодня можно получить <img...> за 44 боя.
        # Сегодня можно получить <img...> за 41 бой.
        match = re.search(r'за\s+(\d+)\s+бо[йеёяв]', html)
        if match:
            return int(match.group(1))

        # Пробуем альтернативный паттерн
        match = re.search(r'(\d+)\s+бо[йеёяв]', html)
        if match:
            return int(match.group(1))

        # Сохраним HTML для дебага
        with open("arena_debug.html", "w", encoding="utf-8") as f:
            f.write(html)
        log_warning("[ARENA] Не удалось найти количество боёв, сохранил arena_debug.html")
        return 0

    def get_queue_button(self, html: str, arena_type: str = "arena1r2") -> Optional[str]:
        """
        Ищет кнопку входа в очередь арены.

        Args:
            html: HTML страницы /pvp/select
            arena_type: Тип арены (arena1r2, arena2r2, arena3)

        Returns:
            str: URL кнопки или None
        """
        # href="...?ppAction=pvpGo&amp;ppKey=...&amp;arena=arena1r2&amp;bet=0"
        # Учитываем HTML encoding (&amp;)
        pattern = rf'href=["\']([^"\']*ppAction=pvpGo[^"\']*arena={arena_type}[^"\']*)["\']'
        match = re.search(pattern, html)
        if match:
            url = match.group(1)
            if not url.startswith("http"):
                url = self.base_url + url
            return url.replace("&amp;", "&")

        # Сохраним для дебага если не нашли
        with open("arena_queue_debug.html", "w", encoding="utf-8") as f:
            f.write(html)
        log_debug(f"[ARENA] Кнопка {arena_type} не найдена, сохранил arena_queue_debug.html")

        # Диагностика: проверяем есть ли кнопки вообще
        if f'arena={arena_type}' not in html:
            log_warning(f"[ARENA] Тип арены {arena_type} не найден на странице")
        elif '<span class="go-btn">' in html and '<a class="go-btn"' not in html:
            log_warning("[ARENA] Кнопки арены disabled (span вместо a) - возможно занят крафтом или боем")

        return None

    def get_arena_enter_button(self, html: str) -> Optional[str]:
        """
        Ищет кнопку "На арену" (появляется когда найден соперник).

        Args:
            html: HTML страницы

        Returns:
            str: URL кнопки или None
        """
        # href="...arenaLink...ppAction=PVP_Enter"
        pattern = r'href=["\']([^"\']*arenaLink[^"\']*ppAction=PVP_Enter[^"\']*)["\']'
        match = re.search(pattern, html)
        if match:
            url = match.group(1)
            if not url.startswith("http"):
                url = self.base_url + url
            return url.replace("&amp;", "&")
        return None

    def get_cancel_button(self, html: str) -> Optional[str]:
        """
        Ищет кнопку отмены очереди.

        Args:
            html: HTML страницы

        Returns:
            str: URL кнопки или None
        """
        # cancelLink или PVP_Leave
        pattern = r'href=["\']([^"\']*(?:cancelLink|PVP_Leave)[^"\']*)["\']'
        match = re.search(pattern, html)
        if match:
            url = match.group(1)
            if not url.startswith("http"):
                url = self.base_url + url
            return url.replace("&amp;", "&")
        return None

    def get_again_button(self, html: str) -> Optional[str]:
        """
        Ищет кнопку "Ещё раз" на странице результатов.

        Args:
            html: HTML страницы /pvp/result

        Returns:
            str: URL кнопки или None
        """
        # ppAction=pvpAgain
        pattern = r'href=["\']([^"\']*ppAction=pvpAgain[^"\']*)["\']'
        match = re.search(pattern, html)
        if match:
            url = match.group(1)
            if not url.startswith("http"):
                url = self.base_url + url
            return url.replace("&amp;", "&")
        return None

    def is_in_queue(self, html: str) -> bool:
        """Проверяет, находимся ли мы в очереди или на странице ожидания."""
        # На странице /pvp/ready есть pvp-versus (ожидание соперника)
        # Также проверяем старые маркеры
        return ("pvp-versus" in html or
                "Время ожидания" in html or
                "cancelLink" in html or
                "/pvp/ready" in html)

    def is_in_combat(self, html: str) -> bool:
        """Проверяет, находимся ли мы в бою."""
        return "/pvp/combat/" in html or "ptxIsCombatPage = true" in html

    def is_on_result_page(self, html: str) -> bool:
        """Проверяет, находимся ли мы на странице результатов."""
        return "/pvp/result" in html or "Итоги боя" in html

    def is_buttons_disabled(self, html: str) -> bool:
        """Проверяет заблокированы ли кнопки арены (КД после боя)."""
        # Когда КД активен, кнопки арены это <span>, а не <a href="...arena=...">
        # Проверяем наличие активной ссылки на арену
        import re
        has_arena_link = bool(re.search(r'<a[^>]+href="[^"]*arena=arena\d', html))
        return not has_arena_link

    def check_and_leave_party(self, html: str) -> Tuple[bool, str]:
        """
        Проверяет есть ли попап "Сначала покинь текущую банду" и выходит из неё.

        Args:
            html: HTML страницы

        Returns:
            tuple: (was_in_party, new_html)
        """
        # Проверяем попап "Сначала покинь текущую банду"
        if "Сначала покинь текущую банду" in html or "LeavePartyPanel" in html:
            log_warning("[ARENA] Обнаружен попап 'Покинуть банду'")

            # Ищем кнопку "Покинуть банду" (нижняя, с ppAction=leaveParty)
            match = re.search(r'href="([^"]*ppAction=leaveParty[^"]*)"', html)
            if match:
                leave_url = match.group(1)
                if not leave_url.startswith("http"):
                    leave_url = self.base_url + leave_url
                leave_url = leave_url.replace("&amp;", "&")

                log_info("[ARENA] Выхожу из банды...")
                resp = self.session.get(leave_url)
                if resp.status_code == 200:
                    log_info("[ARENA] Успешно вышел из банды")
                    return True, resp.text
                else:
                    log_error(f"[ARENA] Ошибка выхода из банды: {resp.status_code}")
            else:
                log_warning("[ARENA] Не найдена кнопка 'Покинуть банду'")

        return False, html

    def join_queue(self, arena_type: str = "arena1r2") -> Tuple[bool, str]:
        """
        Встаёт в очередь на арену.

        Args:
            arena_type: Тип арены

        Returns:
            tuple: (success, html/error)
            Специальные ошибки:
            - "CD" - кнопки заблокированы, нужно подождать
            - "Мало боёв: X" - лимит достигнут
        """
        log_info(f"[ARENA] Загружаю страницу арены...")
        resp = self.session.get(f"{self.base_url}/pvp/select")
        if resp.status_code != 200:
            return False, f"Ошибка загрузки: {resp.status_code}"

        html = resp.text

        # Проверяем не застряли ли в банде (из предыдущего данжена)
        was_in_party, html = self.check_and_leave_party(html)
        if was_in_party:
            # После выхода из банды перезагружаем страницу
            resp = self.session.get(f"{self.base_url}/pvp/select")
            if resp.status_code == 200:
                html = resp.text

        # Проверяем - может мы уже в очереди?
        if self.is_in_queue(html):
            log_info("[ARENA] Уже в очереди, ожидаю соперника...")
            return True, html

        # Проверяем количество боёв
        fights = self.get_fights_remaining(html)
        log_info(f"[ARENA] Осталось боёв за очки: {fights}")

        if fights <= MIN_FIGHTS_LEFT:
            return False, f"Мало боёв: {fights} <= {MIN_FIGHTS_LEFT}"

        # Проверяем заблокированы ли кнопки (КД после боя)
        if self.is_buttons_disabled(html):
            log_warning("[ARENA] Кнопки заблокированы (КД после боя)")
            return False, "CD"

        # Ищем кнопку очереди
        queue_url = self.get_queue_button(html, arena_type)
        if not queue_url:
            return False, f"Не найдена кнопка очереди для {arena_type}"

        log_info(f"[ARENA] Встаю в очередь: {arena_type}")
        resp = self.session.get(queue_url)
        if resp.status_code != 200:
            return False, f"Ошибка входа в очередь: {resp.status_code}"

        # После нажатия кнопки проверяем /pvp/ready - туда попадаем при ожидании
        time.sleep(0.5)
        resp = self.session.get(f"{self.base_url}/pvp/ready")
        log_debug(f"[ARENA] После входа в очередь: URL={resp.url}")

        # Сохраняем для дебага
        with open("arena_after_queue.html", "w", encoding="utf-8") as f:
            f.write(resp.text)

        return True, resp.text

    def wait_for_opponent(self, initial_html: str) -> Tuple[bool, str]:
        """
        Ждёт пока найдётся соперник.

        Args:
            initial_html: HTML после входа в очередь

        Returns:
            tuple: (success, arena_enter_url/error)
        """
        html = initial_html
        start_time = time.time()
        first_check = True  # Первая проверка - не считаем отсутствие очереди ошибкой

        while time.time() - start_time < QUEUE_TIMEOUT:
            # Проверяем кнопку "На арену"
            enter_url = self.get_arena_enter_button(html)
            if enter_url:
                log_info("[ARENA] Соперник найден!")
                return True, enter_url

            # Может уже в бою?
            if self.is_in_combat(html):
                log_info("[ARENA] Уже в бою!")
                return True, html

            # Ещё в очереди?
            if not self.is_in_queue(html):
                if first_check:
                    # Первая проверка - страница могла не успеть обновиться
                    log_debug("[ARENA] Первая проверка - не в очереди, жду обновления...")
                else:
                    # После первой итерации - если не в очереди, значит вышли
                    return False, "Вышли из очереди"

            first_check = False
            elapsed = int(time.time() - start_time)
            log_debug(f"[ARENA] Ожидание соперника... {elapsed}s")

            time.sleep(QUEUE_POLL_INTERVAL)

            # Обновляем страницу /pvp/ready - там ждём соперника
            resp = self.session.get(f"{self.base_url}/pvp/ready")
            if resp.status_code != 200:
                return False, f"Ошибка обновления: {resp.status_code}"
            html = resp.text

            # Если редирект на /pvp/select - значит не в очереди
            if "/pvp/select" in str(resp.url) and "/pvp/ready" not in str(resp.url):
                log_debug(f"[ARENA] Редирект на select, видимо не в очереди")

        return False, "Таймаут ожидания соперника"

    def enter_arena(self, enter_url: str) -> Tuple[bool, str]:
        """
        Входит на арену (предбой).

        Args:
            enter_url: URL кнопки "На арену"

        Returns:
            tuple: (success, combat_url/error)
        """
        log_info("[ARENA] Вхожу на арену...")
        resp = self.session.get(enter_url)
        if resp.status_code != 200:
            return False, f"Ошибка входа: {resp.status_code}"

        html = resp.text

        # Проверяем что на странице /pvp/ready
        if "/pvp/ready" not in resp.url and "pvp-versus" not in html:
            log_warning(f"[ARENA] Неожиданная страница: {resp.url}")

        # Ждём начала боя
        log_info(f"[ARENA] Предбой, ждём {READY_WAIT}с...")
        time.sleep(READY_WAIT)

        # Проверяем начался ли бой
        resp = self.session.get(f"{self.base_url}/pvp/select")
        html = resp.text

        if self.is_in_combat(html):
            # Ищем URL боя
            combat_match = re.search(r'https://vmmo\.vten\.ru/pvp/combat/[^"\']+', html)
            if combat_match:
                return True, combat_match.group(0)
            return True, html  # Вернём HTML, бой начался

        return False, "Бой не начался"

    def do_combat(self) -> Tuple[bool, str]:
        """
        Проводит бой на арене.

        Returns:
            tuple: (success, result_html)
        """
        from requests_bot.combat import CombatParser

        max_attacks = 100
        attacks = 0
        combat_url = f"{self.base_url}/pvp/combat"

        log_info("[ARENA] Начинаю бой...")

        # Загружаем страницу боя один раз в начале
        resp = self.session.get(combat_url)
        if resp.status_code != 200:
            log_error(f"[ARENA] Не удалось загрузить бой: {resp.status_code}")
            return False, "Не удалось загрузить бой"

        html = resp.text
        current_url = str(resp.url)

        # Извлекаем page_id для AJAX
        page_id_match = re.search(r'ptxPageId\s*=\s*(\d+)', html)
        page_id = page_id_match.group(1) if page_id_match else ""

        # Настраиваем refresher для сбора лута
        self._setup_refresher_url(html, current_url)

        while attacks < max_attacks:
            # Проверяем - может бой уже закончился и мы на результатах
            if "/pvp/result" in current_url or "Итоги боя" in html:
                log_info("[ARENA] Бой завершён, переходим к результатам")
                return True, html

            # Проверяем смерть противника (лог "растерла в порошок" с черепом)
            # skull_gray.png появляется ТОЛЬКО когда кто-то убит
            if 'skull_gray.png' in html:
                log_info("[ARENA] Противник мёртв (skull в логе), ждём результаты")
                # Поллим страницу результатов пока не появится
                for wait in range(10):  # Макс 10 попыток по 2 сек = 20 сек
                    time.sleep(2)
                    resp = self.session.get(f"{self.base_url}/pvp/result")
                    if "Итоги боя" in resp.text or "arena_points.png" in resp.text:
                        log_info(f"[ARENA] Результаты получены после {(wait+1)*2}с")
                        return True, resp.text
                    log_debug(f"[ARENA] Ожидание результатов... {(wait+1)*2}с")
                # Всё равно вернём что получили
                return True, resp.text

            # Проверяем есть ли активный бой
            parser = CombatParser(html, current_url)
            attack_url = parser.get_attack_url()

            if not attack_url:
                log_info("[ARENA] Нет attack URL, бой завершён")
                # Проверяем результаты
                time.sleep(1)
                resp = self.session.get(f"{self.base_url}/pvp/result")
                return True, resp.text

            # Пробуем использовать скилл
            skill_used = False
            skill_urls = parser.get_skill_urls()
            for pos in sorted(skill_urls.keys()):
                if not parser.check_skill_cooldown(pos):
                    # Скилл готов - используем
                    skill_url = skill_urls[pos]
                    self._do_ajax_action(skill_url, current_url, page_id)
                    log_debug(f"[ARENA] Скилл {pos} использован")
                    skill_used = True
                    attacks += 1
                    break

            if not skill_used:
                # Атакуем
                self._do_ajax_action(attack_url, current_url, page_id)
                attacks += 1

            # Сбор лута каждые 3 атаки
            self.attack_count += 1
            if self.attack_count % LOOT_COLLECT_INTERVAL == 0:
                self._collect_loot_via_refresher()

            # Логируем прогресс каждые 10 действий
            if attacks % 10 == 0:
                log_debug(f"[ARENA] Действий: {attacks}")

            # После действия перезагружаем страницу чтобы получить актуальное состояние
            time.sleep(0.3)
            resp = self.session.get(combat_url)
            if resp.status_code == 200:
                html = resp.text
                current_url = str(resp.url)

        log_info(f"[ARENA] Выполнено {attacks} действий")

        # Финальный сбор лута
        self._collect_loot_via_refresher()

        # Получаем результат
        time.sleep(3)
        resp = self.session.get(f"{self.base_url}/pvp/result")
        return True, resp.text

    def _do_ajax_action(self, url: str, referer: str, page_id: str):
        """Выполняет AJAX действие (атака/скилл)."""
        base_path = referer.split("?")[0].replace("https://vmmo.vten.ru/", "")
        base_url_header = f"{base_path}?{page_id}" if page_id else base_path

        headers = {
            "Wicket-Ajax": "true",
            "Wicket-Ajax-BaseURL": base_url_header,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml, text/xml, */*; q=0.01",
            "Referer": referer,
        }
        self.session.get(url, headers=headers)

    def parse_result(self, html: str) -> dict:
        """
        Парсит результаты боя.

        Args:
            html: HTML страницы /pvp/result

        Returns:
            dict: {won: bool, rating_change: float, points: int}
        """
        result = {
            "won": False,
            "rating_change": 0.0,
            "points": 0,
        }

        # Сохраняем для дебага
        with open("arena_result_debug.html", "w", encoding="utf-8") as f:
            f.write(html)

        # Победа - ищем "Победитель" или положительный рейтинг
        if "Победитель" in html:
            result["won"] = True

        # Изменение рейтинга: ищем span.info с +X.X или span.major с -X.X
        # Формат: <img ... src="...arena_sword.png" ...> <span class="info">+1.1</span>
        # Может быть как /> так и > в конце img
        # ВАЖНО: ищем только значения с + или - (изменение), а не абсолютный рейтинг
        rating_matches = re.findall(r'arena_sword\.png[^>]*>\s*<span[^>]*>([+-][\d.]+)</span>', html)
        for match in rating_matches:
            try:
                rating = float(match)
                result["rating_change"] = rating
                if rating > 0:
                    result["won"] = True
                break  # Берём первый match с +/- (наш результат)
            except ValueError:
                pass

        # Очки: +3 после arena_points.png
        # Формат: <img ... src="...arena_points.png" ...> <span class="info">+3</span>
        points_match = re.search(r'arena_points\.png[^>]*>\s*<span[^>]*>\+(\d+)</span>', html)
        if points_match:
            result["points"] = int(points_match.group(1))

        log_debug(f"[ARENA] Результат: won={result['won']}, rating={result['rating_change']}, points={result['points']}")

        return result

    def run_arena_session(self, max_fights: int = 50, arena_type: str = "arena1r2") -> dict:
        """
        Запускает сессию арены - бьёмся пока есть бои.

        Args:
            max_fights: Максимум боёв за сессию
            arena_type: Тип арены

        Returns:
            dict: Статистика {fights: int, wins: int, points: int, rating_change: float}
        """
        stats = {
            "fights": 0,
            "wins": 0,
            "points": 0,
            "rating_change": 0.0,
        }

        log_info(f"[ARENA] Начинаю сессию арены, макс {max_fights} боёв")

        cd_retries = 0  # Счётчик ретраев при КД

        while stats["fights"] < max_fights:
            # Проверяем сколько боёв осталось
            fights_left = self.get_fights_remaining()
            log_info(f"[ARENA] Боёв осталось: {fights_left}")

            # Если не смогли распарсить (0) - продолжаем, не выходим
            if fights_left > 0 and fights_left <= MIN_FIGHTS_LEFT:
                log_info(f"[ARENA] Достигнут лимит ({MIN_FIGHTS_LEFT}), останавливаюсь")
                break

            # Встаём в очередь
            success, result = self.join_queue(arena_type)
            if not success:
                # Если это КД - ждём и пробуем снова
                if result == "CD":
                    cd_retries += 1
                    if cd_retries > CD_MAX_RETRIES:
                        log_error(f"[ARENA] Превышен лимит ожидания КД ({CD_MAX_RETRIES} попыток)")
                        break
                    log_info(f"[ARENA] Ожидаю КД {CD_WAIT}с (попытка {cd_retries}/{CD_MAX_RETRIES})...")
                    time.sleep(CD_WAIT)
                    continue
                else:
                    log_error(f"[ARENA] Не удалось встать в очередь: {result}")
                    break

            # Успешно встали в очередь - сбрасываем счётчик КД
            cd_retries = 0

            # Ждём соперника
            success, result = self.wait_for_opponent(result)
            if not success:
                log_error(f"[ARENA] Не дождались соперника: {result}")
                break

            # Входим на арену
            if isinstance(result, str) and result.startswith("http"):
                success, result = self.enter_arena(result)
                if not success:
                    log_error(f"[ARENA] Не удалось войти: {result}")
                    break

            # Бой!
            success, result_html = self.do_combat()

            # Парсим результат
            fight_result = self.parse_result(result_html)
            stats["fights"] += 1
            stats["points"] += fight_result["points"]
            stats["rating_change"] += fight_result["rating_change"]
            if fight_result["won"]:
                stats["wins"] += 1

            log_info(f"[ARENA] Бой #{stats['fights']}: "
                    f"{'Победа' if fight_result['won'] else 'Поражение'}, "
                    f"+{fight_result['points']} очков, "
                    f"рейтинг {fight_result['rating_change']:+.1f}")

            # Проверяем кнопку "Ещё раз"
            again_url = self.get_again_button(result_html)
            if again_url:
                log_debug("[ARENA] Нажимаю 'Ещё раз'...")
                resp = self.session.get(again_url)
                time.sleep(1)
            else:
                log_debug("[ARENA] Кнопка 'Ещё раз' не найдена, идём через главную")
                time.sleep(2)

        log_info(f"[ARENA] Сессия завершена: {stats['fights']} боёв, "
                f"{stats['wins']} побед, {stats['points']} очков, "
                f"рейтинг {stats['rating_change']:+.1f}")

        return stats


def main():
    """Тест модуля арены."""
    import argparse

    parser = argparse.ArgumentParser(description="PvP Arena bot")
    parser.add_argument("--profile", type=str, default="char1", help="Профиль персонажа")
    parser.add_argument("--fights", type=int, default=5, help="Максимум боёв")
    parser.add_argument("--check-only", action="store_true", help="Только проверить количество боёв")
    args = parser.parse_args()

    # Устанавливаем профиль
    from requests_bot.config import set_profile
    set_profile(args.profile)
    print(f"[ARENA] Профиль: {args.profile}")

    from requests_bot.client import VMMOClient

    client = VMMOClient()
    # Сначала пробуем cookies
    client.load_cookies()

    # Проверяем авторизацию - делаем запрос и смотрим содержимое
    resp = client.session.get("https://vmmo.vten.ru/pvp/select")
    if "entrance" in resp.url or "ptxUserId = '0'" in resp.text or "ptxUserLogin = ''" in resp.text:
        print("Cookies невалидны, логинюсь...")
        if not client.login():
            print("Ошибка авторизации!")
            return
        print("Логин успешен!")

    arena = ArenaClient(client)

    # Проверяем количество боёв
    fights = arena.get_fights_remaining()
    print(f"Боёв осталось: {fights}")

    if args.check_only:
        return

    if fights > MIN_FIGHTS_LEFT:
        # Запускаем сессию
        stats = arena.run_arena_session(max_fights=args.fights)
        print(f"Статистика: {stats}")
    else:
        print(f"Мало боёв ({fights} <= {MIN_FIGHTS_LEFT}), пропускаю")


if __name__ == "__main__":
    main()
