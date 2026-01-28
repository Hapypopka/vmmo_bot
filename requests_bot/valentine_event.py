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

BASE_URL = "https://vmmo.vten.ru"

# Ивент-данжены
VALENTINE_DUNGEONS = {
    "SurtCaves": {
        "id": "SurtCaves",
        "name": "Пещеры Сурта",
        "difficulty": "normal",
    },
    "HallOfHearts": {
        "id": "HallOfHearts",
        "name": "Зал Сердец",
        "difficulty": "normal",
    },
    "MysteriousForest": {
        "id": "MysteriousForest",
        "name": "Загадочный Лес",
        "difficulty": "normal",
    },
}

# Кэш КД данженов (в памяти)
_cooldown_cache = {}


def get_lobby_url(dungeon_id: str, difficulty: str = "normal") -> str:
    """Возвращает URL для входа в данжен"""
    return f"{BASE_URL}/dungeon/lobby/{dungeon_id}?1={difficulty}"


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
    difficulty = dungeon["difficulty"]

    # Проверяем кэш КД
    is_available, remaining = check_cooldown(dungeon_id)
    if not is_available:
        log_debug(f"[VALENTINE] {name} на КД (кэш): {remaining // 60}м")
        return "on_cooldown", remaining

    # Пробуем войти напрямую в lobby
    lobby_url = get_lobby_url(dungeon_id, difficulty)
    log_debug(f"[VALENTINE] Пробую войти: {name} -> {lobby_url}")

    client.get(lobby_url)
    time.sleep(0.5)

    current_url = client.current_url
    html = client.current_page

    # Проверяем результат
    if "/error/" in current_url or "accessDenied" in current_url:
        log_debug(f"[VALENTINE] {name}: доступ запрещён")
        return "error", 0

    # Проверяем редирект на город/данжены (значит на КД)
    if "/city" in current_url or ("/dungeons" in current_url and "lobby" not in current_url):
        # Парсим КД со страницы событий
        cd = parse_cooldown_from_page(html, dungeon_id)
        if cd:
            set_cooldown(dungeon_id, cd)
            log_debug(f"[VALENTINE] {name} на КД: {cd // 60}м")
            return "on_cooldown", cd
        else:
            # Дефолтный КД 6 часов
            set_cooldown(dungeon_id, 6 * 3600)
            return "on_cooldown", 6 * 3600

    # Проверяем что мы в lobby или бою
    if "/dungeon/lobby/" in current_url or "/combat" in current_url.lower():
        # Ищем кнопку "Начать бой"
        if "Начать бой" in html:
            # Кликаем на кнопку начала боя
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            start_btn = None
            for btn in soup.select('a.go-btn, button'):
                text = btn.get_text(strip=True)
                if 'начать бой' in text.lower():
                    href = btn.get('href')
                    if href:
                        start_btn = href if href.startswith('http') else urljoin(current_url, href)
                        break

            if start_btn:
                log_debug(f"[VALENTINE] Нажимаю 'Начать бой': {start_btn}")
                client.get(start_btn)
                time.sleep(0.5)

        log_info(f"[VALENTINE] Вошли в {name}!")
        return "entered", 0

    # Проверяем что мы уже в бою
    if "combat" in html.lower() or "skill" in html.lower() or "АТАКА" in html:
        log_info(f"[VALENTINE] Уже в бою: {name}")
        return "entered", 0

    log_warning(f"[VALENTINE] {name}: неизвестное состояние")
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
        # Дефолтный КД 6 часов
        set_cooldown(dungeon_id, 6 * 3600)
        log_debug(f"[VALENTINE] КД после победы {dungeon_id}: 6ч (дефолт)")


def run_valentine_dungeons(client, dungeon_runner) -> dict:
    """
    Проходит все доступные ивент-данжены.

    Args:
        client: VMMOClient
        dungeon_runner: DungeonRunner для боя

    Returns:
        dict: {"completed": int, "on_cooldown": int, "errors": int}
    """
    stats = {"completed": 0, "on_cooldown": 0, "errors": 0}

    for dungeon_id, dungeon_config in VALENTINE_DUNGEONS.items():
        name = dungeon_config["name"]

        log_debug(f"[VALENTINE] Проверяю: {name}...")
        result, cd = try_enter_dungeon(client, dungeon_id)

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
            log_info(f"[VALENTINE] Бой в {name}...")
            dungeon_runner.current_dungeon_id = dungeon_id
            dungeon_runner.combat_url = client.current_url

            fight_result, actions = dungeon_runner.fight_until_done()

            if fight_result == "completed":
                log_info(f"[VALENTINE] {name} пройден! ({actions} действий)")
                stats["completed"] += 1
                # Устанавливаем КД
                set_cooldown_after_completion(client, dungeon_id)
            elif fight_result == "died":
                log_warning(f"[VALENTINE] Смерть в {name}")
                stats["errors"] += 1
                dungeon_runner.resurrect()
            else:
                log_warning(f"[VALENTINE] {name}: результат '{fight_result}'")
                stats["errors"] += 1

    return stats
