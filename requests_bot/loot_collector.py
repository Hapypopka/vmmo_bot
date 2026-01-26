# ============================================
# VMMO Loot Collector
# ============================================
# Общая логика сбора лута через refresher endpoint
# Используется в: run_dungeon.py, hell_games.py, survival_mines.py, arena.py
# ============================================

import re
from typing import Set, Optional, Callable
from urllib.parse import urljoin

# Логирование
try:
    from requests_bot.logger import log_debug, log_warning, log_error
except ImportError:
    def log_debug(msg): pass
    def log_warning(msg): print(f"[WARN] {msg}")
    def log_error(msg): print(f"[ERROR] {msg}")


def parse_loot_take_url(html: str) -> Optional[str]:
    """
    Извлекает lootTakeUrl из HTML/AJAX ответа.

    Args:
        html: HTML или AJAX текст

    Returns:
        URL для сбора лута или None
    """
    match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", html)
    return match.group(1) if match else None


def parse_loot_ids(html: str) -> list[str]:
    """
    Извлекает ID лута из dropLoot событий.

    Args:
        html: HTML или AJAX текст содержащий dropLoot

    Returns:
        Список ID лута
    """
    if "dropLoot" not in html:
        return []

    return re.findall(r"id:\s*'(\d+)'", html)


def collect_loot_from_refresher(
    session,
    refresher_url: str,
    loot_take_url: str,
    collected_ids: Set[str],
    base_url: str = "",
    timeout: int = 10,
    on_collect: Optional[Callable[[str], None]] = None,
    log_prefix: str = "LOOT"
) -> tuple[int, Optional[str]]:
    """
    Собирает лут через refresher endpoint.

    Это основной метод сбора лута в VMMO. Браузер вызывает refresher
    каждые ~500ms, мы вызываем его реже (каждые N атак).

    Args:
        session: requests.Session для HTTP запросов
        refresher_url: URL refresher endpoint
        loot_take_url: Базовый URL для сбора лута (может обновиться)
        collected_ids: Множество уже собранных ID (будет обновлено)
        base_url: Базовый URL для преобразования относительных путей
        timeout: Таймаут запроса
        on_collect: Опциональный callback(loot_id) после сбора каждого предмета
        log_prefix: Префикс для логов

    Returns:
        (collected_count, updated_loot_url):
        - Количество собранных предметов
        - Новый loot_take_url (если обновился) или None
    """
    if not refresher_url:
        return 0, None

    try:
        # Преобразуем относительный URL в абсолютный если нужно
        if base_url and not refresher_url.startswith("http"):
            url = urljoin(base_url, refresher_url)
        else:
            url = refresher_url

        resp = session.get(url, timeout=timeout)
        if resp.status_code != 200:
            return 0, None

        response_text = resp.text

        # Проверяем обновление loot_take_url
        new_loot_url = parse_loot_take_url(response_text)

        # Ищем лут
        loot_ids = parse_loot_ids(response_text)
        if not loot_ids:
            return 0, new_loot_url

        # Используем текущий или обновлённый URL
        take_url_base = new_loot_url or loot_take_url
        if not take_url_base:
            return 0, new_loot_url

        collected = 0
        for loot_id in loot_ids:
            if loot_id in collected_ids:
                continue

            take_url = take_url_base + loot_id
            try:
                session.get(take_url, timeout=5)
                collected_ids.add(loot_id)
                collected += 1
                log_debug(f"[{log_prefix}] Собран: {loot_id}")

                if on_collect:
                    on_collect(loot_id)

            except Exception as e:
                log_warning(f"[{log_prefix}] Ошибка сбора {loot_id}: {e}")

        return collected, new_loot_url

    except Exception as e:
        log_error(f"[{log_prefix}] Ошибка refresher: {e}")
        return 0, None


class LootCollector:
    """
    Класс для управления сбором лута.

    Инкапсулирует состояние (collected_ids, loot_take_url) и предоставляет
    удобный интерфейс.

    Example:
        collector = LootCollector(client.session)
        collector.setup(page_id="123", dungeon_path="dungeon/combat/dSanctuary")

        # В цикле боя
        collected = collector.collect()
    """

    def __init__(self, session, log_prefix: str = "LOOT"):
        """
        Args:
            session: requests.Session
            log_prefix: Префикс для логов
        """
        self.session = session
        self.log_prefix = log_prefix

        self.refresher_url: Optional[str] = None
        self.loot_take_url: Optional[str] = None
        self.collected_ids: Set[str] = set()
        self.total_collected: int = 0

    def setup(
        self,
        page_id: str,
        dungeon_path: str,
        difficulty_param: str = "",
        base_url: str = "https://vmmo.vten.ru"
    ):
        """
        Настраивает refresher URL.

        Args:
            page_id: ID страницы (ptxPageId)
            dungeon_path: Путь к данжену (например "dungeon/combat/survMines")
            difficulty_param: Параметр сложности (например "1=normal")
            base_url: Базовый URL сервера
        """
        # Формат: /dungeon/combat/dSanctuary?{pageId}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher
        self.refresher_url = (
            f"{base_url}/{dungeon_path}?{page_id}-1.IBehaviorListener.0-"
            f"combatPanel-container-battlefield-refresher"
        )
        if difficulty_param:
            self.refresher_url += f"&{difficulty_param}"

        self.collected_ids.clear()
        self.total_collected = 0
        log_debug(f"[{self.log_prefix}] Refresher настроен: page_id={page_id}")

    def setup_from_html(self, html: str, base_url: str = ""):
        """
        Извлекает loot_take_url из HTML.

        Args:
            html: HTML страницы боя
            base_url: Базовый URL
        """
        self.loot_take_url = parse_loot_take_url(html)
        log_debug(f"[{self.log_prefix}] loot_take_url: {self.loot_take_url}")

    def collect(self) -> int:
        """
        Собирает лут через refresher.

        Returns:
            Количество собранных предметов
        """
        def on_collect(loot_id):
            self.total_collected += 1

        count, new_url = collect_loot_from_refresher(
            session=self.session,
            refresher_url=self.refresher_url,
            loot_take_url=self.loot_take_url,
            collected_ids=self.collected_ids,
            on_collect=on_collect,
            log_prefix=self.log_prefix
        )

        if new_url:
            self.loot_take_url = new_url

        return count

    def reset(self):
        """Сбрасывает состояние для нового боя"""
        self.collected_ids.clear()
        # total_collected НЕ сбрасываем - это статистика за сессию
