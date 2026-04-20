# ============================================
# VMMO Bot - April Event Dungeons
# ============================================
# Ивент Апрель 2026 — Комета Ностромо
# Данжи: mirrormaze, Apr2023-ReturnCometNostromo
# Дефолтная сложность: normal (нормал)
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

# Ивент-данжен
VALENTINE_DUNGEONS = {
    "Apr2023-ReturnCometNostromo": {
        "id": "Apr2023-ReturnCometNostromo",
        "name": "Комета Ностромо",
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
    log_info("[EVENT] Запрашиваю КД с сервера...")
    client.get(f"{BASE_URL}/dungeons?section=tab1")
    time.sleep(0.5)

    html = client.current_page
    current_url = client.current_url
    log_debug(f"[EVENT] URL после перехода: {current_url}")

    # Ищем apiSectionUrl с IEndpointBehaviorListener.1-blockDungeonsNew
    api_pattern = r"apiSectionUrl:\s*['\"]([^'\"]+IEndpointBehaviorListener\.\d+-blockDungeonsNew[^'\"]*)['\"]"
    match = re.search(api_pattern, html)

    if not match:
        api_pattern2 = r"(https?://[^'\"]+IEndpointBehaviorListener\.1-blockDungeonsNew[^'\"]*)"
        match = re.search(api_pattern2, html)

    if not match:
        log_warning(f"[EVENT] API URL не найден! URL: {current_url}, HTML len: {len(html)}")
        return {}

    api_url = match.group(1)
    if 'section_id=' not in api_url:
        api_url += '&section_id=tab1'

    log_debug(f"[EVENT] API URL: {api_url}")

    try:
        headers = {
            'ptxAPI': 'true',
            'Accept': 'text/json, application/json',
        }
        response = client.session.get(api_url, headers=headers)

        import json
        data = json.loads(response.text)

        if data.get('status') != 'OK':
            log_warning(f"[EVENT] API статус: {data.get('status')}")
            return {}

        cooldowns = {}
        dungeons = data.get('section', {}).get('dungeons', [])

        for dng in dungeons:
            dng_id = dng.get('id', '').replace('dng:', '')
            cd = dng.get('cooldown')
            if cd:
                cooldowns[dng_id] = cd
                log_debug(f"[EVENT] {dng_id}: КД {cd // 1000 // 60}м с сервера")

        return cooldowns

    except Exception as e:
        log_warning(f"[EVENT] Ошибка API: {e}")
        return {}


def update_cooldowns_from_server(client):
    """Обновляет кэш КД из данных сервера."""
    cooldowns = fetch_cooldowns_from_api(client)

    log_info(f"[EVENT] API вернул КД для {len(cooldowns)} данженов: {list(cooldowns.keys())}")

    for dungeon_id in VALENTINE_DUNGEONS:
        if dungeon_id not in cooldowns:
            if dungeon_id in _cooldown_cache:
                del _cooldown_cache[dungeon_id]
                name = VALENTINE_DUNGEONS[dungeon_id]["name"]
                log_info(f"[EVENT] {name}: КД истёк, ДОСТУПЕН!")
            else:
                name = VALENTINE_DUNGEONS[dungeon_id]["name"]
                log_debug(f"[EVENT] {name}: не было в кэше, доступен")

    for dungeon_id, cd_ms in cooldowns.items():
        if dungeon_id in VALENTINE_DUNGEONS:
            cd_seconds = cd_ms // 1000
            set_cooldown(dungeon_id, cd_seconds)
            name = VALENTINE_DUNGEONS[dungeon_id]["name"]
            log_info(f"[EVENT] {name}: КД {cd_seconds // 3600}ч {(cd_seconds % 3600) // 60}м")


def get_landing_url(dungeon_id: str, difficulty: str = "normal") -> str:
    """Возвращает URL посадочной страницы данжена"""
    url_diff = DIFFICULTY_URL_MAP.get(difficulty, difficulty)
    return f"{BASE_URL}/dungeon/landing/{dungeon_id}/{url_diff}"


def get_lobby_url(dungeon_id: str, difficulty: str = "normal") -> str:
    """Возвращает URL лобби данжена"""
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
    log_debug(f"[EVENT] КД для {dungeon_id}: {seconds // 60}м")


def try_enter_dungeon(client, dungeon_id: str) -> tuple[str, int]:
    """
    Пытается войти в ивент-данжен.

    Returns:
        tuple: (result, cd_seconds)
        result: "entered", "on_cooldown", "error", "skipped"
    """
    if dungeon_id not in VALENTINE_DUNGEONS:
        log_error(f"[EVENT] Неизвестный данжен: {dungeon_id}")
        return "error", 0

    dungeon = VALENTINE_DUNGEONS[dungeon_id]
    name = dungeon["name"]

    # Получаем сложность из deaths.json (дефолт normal для этого ивента)
    difficulty = get_dungeon_difficulty(dungeon_id)
    # Ивент только на нормале — понижаем любую сложность
    if difficulty in ("brutal", "hero"):
        difficulty = "normal"

    if difficulty == "skip":
        log_debug(f"[EVENT] {name} в скипе (слишком много смертей)")
        return "skipped", 0

    is_available, remaining = check_cooldown(dungeon_id)
    if not is_available:
        log_info(f"[EVENT] {name} на КД (КЭШ): ещё {remaining // 60}м")
        return "on_cooldown", remaining

    log_info(f"[EVENT] {name} доступен по кэшу, пробуем войти...")

    # Шаг 1: Landing page
    landing_url = get_landing_url(dungeon_id, difficulty)
    log_debug(f"[EVENT] Landing: {name}")

    client.get(landing_url)
    time.sleep(0.3)

    current_url = client.current_url
    html = client.current_page

    if "/error/" in current_url or "accessDenied" in current_url:
        log_debug(f"[EVENT] {name}: доступ запрещён")
        return "error", 0

    # Редирект на город/данжены = на КД
    if "/city" in current_url or (
        "/dungeons" in current_url
        and "landing" not in current_url
        and "lobby" not in current_url
        and "combat" not in current_url
    ):
        set_cooldown(dungeon_id, 30 * 60)
        log_debug(f"[EVENT] {name} на КД (редирект)")
        return "on_cooldown", 30 * 60

    if "/dungeon/combat" in current_url:
        log_info(f"[EVENT] Уже в бою: {name}")
        return "entered", 0

    if "сможешь войти через" in html.lower():
        log_debug(f"[EVENT] {name}: на КД (текст на странице)")
        set_cooldown(dungeon_id, 30 * 60)
        return "on_cooldown", 30 * 60

    # Шаг 2: На landing - ищем кнопку "Войти"
    if "/dungeon/landing" in current_url:
        log_debug(f"[EVENT] На landing, ищу href 'Войти'...")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')

        enter_url = None
        for link in soup.select('a'):
            text = link.get_text(strip=True)
            href = link.get('href', '')
            if 'Войти' in text and href and not href.startswith('javascript'):
                enter_url = href if href.startswith('http') else urljoin(BASE_URL, href)
                break

        if not enter_url:
            ilink_match = re.search(
                r'href="([^"]*ILinkListener[^"]*createPartyOrEnterLink[^"]*)"',
                html
            )
            if ilink_match:
                enter_url = ilink_match.group(1).replace('&amp;', '&')
                if not enter_url.startswith('http'):
                    enter_url = urljoin(BASE_URL, enter_url)

        if enter_url:
            log_debug(f"[EVENT] Клик 'Войти'")
            client.get(enter_url)
            time.sleep(0.3)
            current_url = client.current_url
            html = client.current_page
        else:
            log_warning(f"[EVENT] {name}: кнопка 'Войти' не найдена")
            return "error", 0

    if "/dungeon/combat" in current_url:
        log_info(f"[EVENT] Вошли в бой: {name}")
        return "entered", 0

    # Шаг 3: В лобби/standby - ищем linkStartCombat
    if "/dungeon/lobby" in current_url or "/dungeon/standby" in current_url:
        log_debug(f"[EVENT] В лобби/standby, ищу linkStartCombat...")

        start_match = re.search(
            r'["\'](https?://[^"\']*linkStartCombat[^"\']*)["\']',
            html
        )

        if not start_match:
            rel_match = re.search(
                r'["\'](/[^"\']*linkStartCombat[^"\']*)["\']',
                html
            )
            if rel_match:
                start_url = BASE_URL + rel_match.group(1).replace('&amp;', '&')
            else:
                wicket_match = re.search(r'"u":"([^"]*linkStartCombat[^"]*)"', html)
                if wicket_match:
                    start_url = wicket_match.group(1)
                    if not start_url.startswith('http'):
                        start_url = BASE_URL + start_url
                else:
                    log_warning(f"[EVENT] {name}: linkStartCombat не найден")
                    return "error", 0
        else:
            start_url = start_match.group(1).replace('&amp;', '&')

        log_debug(f"[EVENT] Start combat URL найден")
        client.get(start_url)
        time.sleep(0.3)
        current_url = client.current_url
        html = client.current_page

    if "/dungeon/combat" in current_url:
        log_info(f"[EVENT] В бою: {name}")
        return "entered", 0

    combat_indicators = ['ptx_combat', 'combat-skills', 'skillBlock', 'АТАКА']
    if any(ind in html for ind in combat_indicators):
        log_info(f"[EVENT] В бою (по HTML): {name}")
        return "entered", 0

    log_warning(f"[EVENT] {name}: не удалось войти (URL: {current_url[:80]})")
    return "error", 0


def set_cooldown_after_completion(client, dungeon_id: str):
    """Парсит и устанавливает КД после завершения данжена."""
    client.get(f"{BASE_URL}/dungeons?section=tab1")
    time.sleep(0.5)

    html = client.current_page

    dungeon_pattern = rf'title="dng:{dungeon_id}"[^>]*>.*?(\d+)\s*ч\s*(\d+)\s*м'
    match = re.search(dungeon_pattern, html, re.DOTALL)

    if match:
        hours, minutes = int(match.group(1)), int(match.group(2))
        cd_seconds = hours * 3600 + minutes * 60
        set_cooldown(dungeon_id, cd_seconds)
        log_debug(f"[EVENT] КД после победы {dungeon_id}: {hours}ч {minutes}м")
    else:
        set_cooldown(dungeon_id, 4 * 3600)
        log_debug(f"[EVENT] КД после победы {dungeon_id}: 4ч (дефолт)")


def run_valentine_dungeons(client, dungeon_runner) -> dict:
    """
    Проходит ивент-данж Комета Ностромо.

    Args:
        client: VMMOClient
        dungeon_runner: DungeonRunner для боя

    Returns:
        dict: {"completed": int, "on_cooldown": int, "errors": int, "skipped": int}
    """
    stats = {"completed": 0, "on_cooldown": 0, "errors": 0, "skipped": 0}

    log_info("[EVENT] Проверяю КД данженов с сервера...")
    update_cooldowns_from_server(client)

    for dungeon_id, dungeon_config in VALENTINE_DUNGEONS.items():
        name = dungeon_config["name"]

        difficulty = get_dungeon_difficulty(dungeon_id)
        # Ивент только на нормале
        if difficulty in ("brutal", "hero"):
            difficulty = "normal"
        diff_name = {"brutal": "брутал", "hero": "героик", "normal": "нормал", "skip": "скип"}.get(difficulty, difficulty)

        log_debug(f"[EVENT] Проверяю: {name} ({diff_name})...")
        result, cd = try_enter_dungeon(client, dungeon_id)

        if result == "skipped":
            log_debug(f"[EVENT] {name} скипнут (много смертей)")
            stats["skipped"] += 1
            continue

        if result == "on_cooldown":
            log_debug(f"[EVENT] {name} на КД ({cd // 60}м)")
            stats["on_cooldown"] += 1
            continue

        if result == "error":
            log_debug(f"[EVENT] {name}: ошибка входа")
            stats["errors"] += 1
            continue

        if result == "entered":
            log_info(f"[EVENT] Бой в {name} ({diff_name})...")
            dungeon_runner.current_dungeon_id = dungeon_id
            dungeon_runner.combat_url = client.current_url

            fight_result, actions = dungeon_runner.fight_until_done()

            if fight_result == "completed":
                log_info(f"[EVENT] {name} пройден! ({actions} действий)")
                stats["completed"] += 1
                set_cooldown_after_completion(client, dungeon_id)
            elif fight_result == "died":
                new_diff, should_skip = record_death(dungeon_id, name, difficulty)
                if should_skip:
                    log_warning(f"[EVENT] Смерть в {name} на {diff_name} → СКИП")
                else:
                    new_diff_name = {"brutal": "брутал", "hero": "героик", "normal": "нормал"}.get(new_diff, new_diff)
                    log_warning(f"[EVENT] Смерть в {name} на {diff_name} → {new_diff_name}")
                stats["errors"] += 1
                dungeon_runner.resurrect()
            else:
                log_warning(f"[EVENT] {name}: результат '{fight_result}'")
                stats["errors"] += 1

    return stats
