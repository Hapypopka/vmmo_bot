# ============================================
# VMMO Bot - Valentine Event Dungeons
# ============================================
# Ивент День Святого Валентина 2026
# Данжены: Пещеры Сурта, Зал Сердец, Загадочный Лес
# ============================================

import time
import re
from urllib.parse import urljoin

from requests_bot.logger import log_info, log_debug, log_warning, log_error
from requests_bot.config import get_dungeon_difficulty, record_death

BASE_URL = "https://vmmo.vten.ru"

# Маппинг сложности на URL параметр
DIFFICULTY_URL_MAP = {
    "brutal": "impossible",
    "hero": "hard",
    "normal": "normal",
}

# Ивент-данжены (сложность берётся из deaths.json, дефолт brutal)
VALENTINE_DUNGEONS = {
    "SurtCaves": {
        "id": "SurtCaves",
        "name": "Пещеры Сурта",
    },
    "HallOfHearts": {
        "id": "HallOfHearts",
        "name": "Зал Сердец",
    },
    "MysteriousForest": {
        "id": "MysteriousForest",
        "name": "Загадочный Лес",
    },
    "RestMonastery": {
        "id": "RestMonastery",
        "name": "Монастырь Покоя",
    },
}

# Кэш КД данженов (в памяти)
_cooldown_cache = {}


def fetch_cooldowns_from_api(client) -> dict:
    """
    Получает КД данженов с сервера через JSON API.

    Returns:
        dict: {dungeon_id: cooldown_ms} или пустой dict при ошибке
    """
    # 1. Идём на страницу событий чтобы получить listener URL
    log_info("[VALENTINE] Запрашиваю КД с сервера...")
    client.get(f"{BASE_URL}/dungeons?section=tab1")
    time.sleep(0.5)

    html = client.current_page
    current_url = client.current_url
    log_debug(f"[VALENTINE] URL после перехода: {current_url}")

    # 2. Ищем apiSectionUrl с IEndpointBehaviorListener.1-blockDungeonsNew
    # Паттерн: apiSectionUrl: 'https://...IEndpointBehaviorListener.1-blockDungeonsNew...'
    api_pattern = r"apiSectionUrl:\s*['\"]([^'\"]+IEndpointBehaviorListener\.\d+-blockDungeonsNew[^'\"]*)['\"]"
    match = re.search(api_pattern, html)

    if not match:
        # Fallback - ищем любой URL с .1-blockDungeonsNew
        api_pattern2 = r"(https?://[^'\"]+IEndpointBehaviorListener\.1-blockDungeonsNew[^'\"]*)"
        match = re.search(api_pattern2, html)

    if not match:
        log_warning(f"[VALENTINE] API URL не найден! URL: {current_url}, HTML len: {len(html)}")
        return {}

    api_url = match.group(1)
    # Добавляем section_id если нет
    if 'section_id=' not in api_url:
        api_url += '&section_id=tab1'

    log_debug(f"[VALENTINE] API URL: {api_url}")

    # 3. Запрашиваем JSON напрямую через session
    try:
        headers = {
            'ptxAPI': 'true',
            'Accept': 'text/json, application/json',
        }
        response = client.session.get(api_url, headers=headers)

        # Парсим JSON
        import json
        data = json.loads(response.text)

        if data.get('status') != 'OK':
            log_warning(f"[VALENTINE] API статус: {data.get('status')}")
            return {}

        # 4. Извлекаем КД для каждого данжена
        cooldowns = {}
        dungeons = data.get('section', {}).get('dungeons', [])

        for dng in dungeons:
            dng_id = dng.get('id', '').replace('dng:', '')  # убираем префикс dng:
            cd = dng.get('cooldown')
            if cd:
                cooldowns[dng_id] = cd  # в миллисекундах
                log_debug(f"[VALENTINE] {dng_id}: КД {cd // 1000 // 60}м с сервера")

        return cooldowns

    except Exception as e:
        log_warning(f"[VALENTINE] Ошибка API: {e}")
        return {}


def update_cooldowns_from_server(client):
    """
    Обновляет кэш КД из данных сервера.
    Вызывать перед запуском данженов.
    """
    cooldowns = fetch_cooldowns_from_api(client)

    log_info(f"[VALENTINE] API вернул КД для {len(cooldowns)} данженов: {list(cooldowns.keys())}")

    # Сначала очищаем КД для данженов, которых НЕТ в ответе API (значит доступны!)
    for dungeon_id in VALENTINE_DUNGEONS:
        if dungeon_id not in cooldowns:
            # Данжен доступен - убираем из кэша КД
            if dungeon_id in _cooldown_cache:
                del _cooldown_cache[dungeon_id]
                name = VALENTINE_DUNGEONS[dungeon_id]["name"]
                log_info(f"[VALENTINE] {name}: КД истёк, ДОСТУПЕН!")
            else:
                name = VALENTINE_DUNGEONS[dungeon_id]["name"]
                log_debug(f"[VALENTINE] {name}: не было в кэше, доступен")

    # Устанавливаем КД для данженов с активным КД
    for dungeon_id, cd_ms in cooldowns.items():
        if dungeon_id in VALENTINE_DUNGEONS:
            cd_seconds = cd_ms // 1000
            set_cooldown(dungeon_id, cd_seconds)
            name = VALENTINE_DUNGEONS[dungeon_id]["name"]
            log_info(f"[VALENTINE] {name}: КД {cd_seconds // 3600}ч {(cd_seconds % 3600) // 60}м")


def get_landing_url(dungeon_id: str, difficulty: str = "brutal") -> str:
    """Возвращает URL посадочной страницы данжена"""
    # Маппим внутреннюю сложность на URL параметр
    url_diff = DIFFICULTY_URL_MAP.get(difficulty, difficulty)
    return f"{BASE_URL}/dungeon/landing/{dungeon_id}/{url_diff}"


def get_lobby_url(dungeon_id: str, difficulty: str = "brutal") -> str:
    """Возвращает URL лобби данжена (устаревший, используй get_landing_url)"""
    url_diff = DIFFICULTY_URL_MAP.get(difficulty, difficulty)
    return f"{BASE_URL}/dungeon/lobby/{dungeon_id}?1={url_diff}"


def check_cooldown(dungeon_id: str) -> tuple[bool, int]:
    """
    Проверяет КД данжена из кэша.

    Returns:
        tuple: (is_available, seconds_remaining)
    """
    if dungeon_id not in _cooldown_cache:
        return True, 0

    cooldown_until = _cooldown_cache[dungeon_id]
    now = time.time()

    if now >= cooldown_until:
        del _cooldown_cache[dungeon_id]
        return True, 0

    remaining = int(cooldown_until - now)
    return False, remaining


def set_cooldown(dungeon_id: str, seconds: int):
    """Устанавливает КД для данжена"""
    _cooldown_cache[dungeon_id] = time.time() + seconds
    log_debug(f"[VALENTINE] КД для {dungeon_id}: {seconds // 60}м")


def parse_cooldown_from_page(html: str, dungeon_id: str) -> int | None:
    """
    Парсит КД данжена со страницы.

    Returns:
        int: секунды КД или None если не на КД
    """
    # Ищем паттерн времени типа "5ч 47м" или "47м" рядом с названием данжена
    patterns = [
        r'(\d+)\s*ч\s*(\d+)\s*м',  # 5ч 47м
        r'(\d+)\s*м',  # 47м
        r'(\d+)\s*с',  # 30с
    ]

    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                hours, minutes = int(groups[0]), int(groups[1])
                return hours * 3600 + minutes * 60
            elif len(groups) == 1:
                value = int(groups[0])
                if 'м' in pattern:
                    return value * 60
                else:
                    return value

    return None


def try_enter_dungeon(client, dungeon_id: str) -> tuple[str, int]:
    """
    Пытается войти в ивент-данжен.

    Флоу:
    1. Landing page: /dungeon/landing/{id}/{difficulty}
    2. Клик "Войти" -> Lobby: /dungeon/lobby/{id}?...&1={difficulty}
    3. Извлекаем ptxPageId и переходим напрямую в combat

    Args:
        client: VMMOClient
        dungeon_id: ID данжена (SurtCaves, HallOfHearts, MysteriousForest)

    Returns:
        tuple: (result, cd_seconds)
        result: "entered", "on_cooldown", "error"
    """
    if dungeon_id not in VALENTINE_DUNGEONS:
        log_error(f"[VALENTINE] Неизвестный данжен: {dungeon_id}")
        return "error", 0

    dungeon = VALENTINE_DUNGEONS[dungeon_id]
    name = dungeon["name"]

    # Получаем сложность из deaths.json (дефолт brutal)
    difficulty = get_dungeon_difficulty(dungeon_id)

    # Если данж скипнут - пропускаем
    if difficulty == "skip":
        log_debug(f"[VALENTINE] {name} в скипе (слишком много смертей)")
        return "skipped", 0

    # Проверяем кэш КД (короткий - 30 мин после редиректа)
    is_available, remaining = check_cooldown(dungeon_id)
    if not is_available:
        log_info(f"[VALENTINE] {name} на КД (КЭШ): ещё {remaining // 60}м")
        return "on_cooldown", remaining

    log_info(f"[VALENTINE] {name} доступен по кэшу, пробуем войти...")

    # Шаг 1: Идём на landing страницу
    landing_url = get_landing_url(dungeon_id, difficulty)
    log_debug(f"[VALENTINE] Landing: {name}")

    client.get(landing_url)
    time.sleep(0.3)

    current_url = client.current_url
    html = client.current_page

    # Проверяем редирект/ошибки
    if "/error/" in current_url or "accessDenied" in current_url:
        log_debug(f"[VALENTINE] {name}: доступ запрещён")
        return "error", 0

    # Редирект на город/данжены = на КД
    if "/city" in current_url or (
        "/dungeons" in current_url
        and "landing" not in current_url
        and "lobby" not in current_url
        and "combat" not in current_url
    ):
        set_cooldown(dungeon_id, 30 * 60)  # 30 мин - проверим снова позже
        log_debug(f"[VALENTINE] {name} на КД (редирект)")
        return "on_cooldown", 30 * 60

    # Уже в бою?
    if "/dungeon/combat" in current_url:
        log_info(f"[VALENTINE] Уже в бою: {name}")
        return "entered", 0

    # Проверяем КД на странице ("Ты сможешь войти через")
    if "сможешь войти через" in html.lower():
        log_debug(f"[VALENTINE] {name}: на КД (текст на странице)")
        set_cooldown(dungeon_id, 30 * 60)  # 30 мин - проверим снова позже
        return "on_cooldown", 30 * 60

    # Шаг 2: На landing - ищем href кнопки "Войти"
    if "/dungeon/landing" in current_url:
        log_debug(f"[VALENTINE] На landing, ищу href 'Войти'...")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        enter_url = None
        for link in soup.select('a'):
            text = link.get_text(strip=True)
            href = link.get('href', '')
            if 'Войти' in text and href and not href.startswith('javascript'):
                enter_url = href if href.startswith('http') else urljoin(BASE_URL, href)
                break

        if not enter_url:
            # Пробуем найти по ILinkListener паттерну
            ilink_match = re.search(
                r'href="([^"]*ILinkListener[^"]*createPartyOrEnterLink[^"]*)"',
                html
            )
            if ilink_match:
                enter_url = ilink_match.group(1).replace('&amp;', '&')
                if not enter_url.startswith('http'):
                    enter_url = urljoin(BASE_URL, enter_url)

        if enter_url:
            log_debug(f"[VALENTINE] Клик 'Войти'")
            client.get(enter_url)
            time.sleep(0.3)
            current_url = client.current_url
            html = client.current_page
        else:
            log_warning(f"[VALENTINE] {name}: кнопка 'Войти' не найдена")
            return "error", 0

    # Проверяем - в бою?
    if "/dungeon/combat" in current_url:
        log_info(f"[VALENTINE] Вошли в бой: {name}")
        return "entered", 0

    # Шаг 3: В лобби/standby - ищем linkStartCombat
    if "/dungeon/lobby" in current_url or "/dungeon/standby" in current_url:
        log_debug(f"[VALENTINE] В лобби/standby, ищу linkStartCombat...")

        # Ищем IBehaviorListener URL для старта боя
        # Паттерн: IBehaviorListener.0-lobby-dungeon-blockStart-linkStartCombat
        start_match = re.search(
            r'["\'](https?://[^"\']*linkStartCombat[^"\']*)["\']',
            html
        )

        if not start_match:
            # Пробуем найти относительный URL
            rel_match = re.search(
                r'["\'](/[^"\']*linkStartCombat[^"\']*)["\']',
                html
            )
            if rel_match:
                start_url = BASE_URL + rel_match.group(1).replace('&amp;', '&')
            else:
                # Пробуем Wicket AJAX паттерн
                wicket_match = re.search(r'"u":"([^"]*linkStartCombat[^"]*)"', html)
                if wicket_match:
                    start_url = wicket_match.group(1)
                    if not start_url.startswith('http'):
                        start_url = BASE_URL + start_url
                else:
                    log_warning(f"[VALENTINE] {name}: linkStartCombat не найден")
                    return "error", 0
        else:
            start_url = start_match.group(1).replace('&amp;', '&')

        log_debug(f"[VALENTINE] Start combat URL найден")
        client.get(start_url)
        time.sleep(0.3)
        current_url = client.current_url
        html = client.current_page

    # Финальная проверка - мы в бою?
    if "/dungeon/combat" in current_url:
        log_info(f"[VALENTINE] В бою: {name}")
        return "entered", 0

    # Проверяем индикаторы боя в HTML
    combat_indicators = ['ptx_combat', 'combat-skills', 'skillBlock', 'АТАКА']
    if any(ind in html for ind in combat_indicators):
        log_info(f"[VALENTINE] В бою (по HTML): {name}")
        return "entered", 0

    log_warning(f"[VALENTINE] {name}: не удалось войти (URL: {current_url[:80]})")
    return "error", 0


def set_cooldown_after_completion(client, dungeon_id: str):
    """
    Парсит и устанавливает КД после завершения данжена.
    Вызывать после победы.
    """
    # Идём на страницу событий чтобы увидеть КД
    client.get(f"{BASE_URL}/dungeons?section=tab1")
    time.sleep(0.5)

    html = client.current_page

    # Ищем КД для конкретного данжена
    # Паттерн: title="dng:SurtCaves" ... затем время КД
    dungeon_pattern = rf'title="dng:{dungeon_id}"[^>]*>.*?(\d+)\s*ч\s*(\d+)\s*м'
    match = re.search(dungeon_pattern, html, re.DOTALL)

    if match:
        hours, minutes = int(match.group(1)), int(match.group(2))
        cd_seconds = hours * 3600 + minutes * 60
        set_cooldown(dungeon_id, cd_seconds)
        log_debug(f"[VALENTINE] КД после победы {dungeon_id}: {hours}ч {minutes}м")
    else:
        # Дефолтный КД 4 часа (реальный КД на сервере ~4ч)
        set_cooldown(dungeon_id, 4 * 3600)
        log_debug(f"[VALENTINE] КД после победы {dungeon_id}: 4ч (дефолт)")


def run_valentine_dungeons(client, dungeon_runner) -> dict:
    """
    Проходит все доступные ивент-данжены.

    Args:
        client: VMMOClient
        dungeon_runner: DungeonRunner для боя

    Returns:
        dict: {"completed": int, "on_cooldown": int, "errors": int, "skipped": int}
    """
    stats = {"completed": 0, "on_cooldown": 0, "errors": 0, "skipped": 0}

    # Сначала получаем актуальные КД с сервера
    log_info("[VALENTINE] Проверяю КД данженов с сервера...")
    update_cooldowns_from_server(client)

    for dungeon_id, dungeon_config in VALENTINE_DUNGEONS.items():
        name = dungeon_config["name"]

        # Получаем текущую сложность для лога
        difficulty = get_dungeon_difficulty(dungeon_id)
        diff_name = {"brutal": "брутал", "hero": "героик", "normal": "нормал", "skip": "скип"}.get(difficulty, difficulty)

        log_debug(f"[VALENTINE] Проверяю: {name} ({diff_name})...")
        result, cd = try_enter_dungeon(client, dungeon_id)

        if result == "skipped":
            log_debug(f"[VALENTINE] {name} скипнут (много смертей)")
            stats["skipped"] += 1
            continue

        if result == "on_cooldown":
            log_debug(f"[VALENTINE] {name} на КД ({cd // 60}м)")
            stats["on_cooldown"] += 1
            continue

        if result == "error":
            log_debug(f"[VALENTINE] {name}: ошибка входа")
            stats["errors"] += 1
            continue

        if result == "entered":
            # Запускаем бой
            log_info(f"[VALENTINE] Бой в {name} ({diff_name})...")
            dungeon_runner.current_dungeon_id = dungeon_id
            dungeon_runner.combat_url = client.current_url

            fight_result, actions = dungeon_runner.fight_until_done()

            if fight_result == "completed":
                log_info(f"[VALENTINE] {name} пройден! ({actions} действий)")
                stats["completed"] += 1
                # Устанавливаем КД
                set_cooldown_after_completion(client, dungeon_id)
            elif fight_result == "died":
                # Записываем смерть и понижаем сложность
                new_diff, should_skip = record_death(dungeon_id, name, difficulty)
                if should_skip:
                    log_warning(f"[VALENTINE] Смерть в {name} на {diff_name} → СКИП")
                else:
                    new_diff_name = {"brutal": "брутал", "hero": "героик", "normal": "нормал"}.get(new_diff, new_diff)
                    log_warning(f"[VALENTINE] Смерть в {name} на {diff_name} → {new_diff_name}")
                stats["errors"] += 1
                dungeon_runner.resurrect()
            else:
                log_warning(f"[VALENTINE] {name}: результат '{fight_result}'")
                stats["errors"] += 1

    return stats
