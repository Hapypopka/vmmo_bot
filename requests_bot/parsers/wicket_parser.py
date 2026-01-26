# ============================================
# VMMO Wicket AJAX Parser
# ============================================
# Общий парсер для Wicket AJAX URLs
# Используется в: combat.py, hell_games.py, survival_mines.py, run_dungeon.py
# ============================================

import re
from typing import Dict, Optional, List, Tuple


def parse_ajax_urls(html: str) -> Dict[str, str]:
    """
    Извлекает все Wicket AJAX URLs из HTML.

    Поддерживаемые паттерны:
    1. Wicket.Ajax.ajax({"c":"element_id","u":"url"...})
    2. "c":"element_id","u":"url" (в массивах обработчиков)

    Args:
        html: HTML контент страницы

    Returns:
        Dict[element_id, url]: словарь элемент -> URL
    """
    urls = {}

    if not html:
        return urls

    # Паттерн 1: Wicket.Ajax.ajax({"c":"element_id","u":"url"...})
    pattern1 = r'Wicket\.Ajax\.ajax\(\{[^}]*"c":"([^"]+)"[^}]*"u":"([^"]+)"'
    matches = re.findall(pattern1, html)
    for element_id, url in matches:
        urls[element_id] = url

    # Паттерн 2: "c":"element_id","u":"url" (в массивах обработчиков)
    pattern2 = r'"c":"([^"]+)","u":"([^"]+)"'
    matches2 = re.findall(pattern2, html)
    for element_id, url in matches2:
        if element_id not in urls:
            urls[element_id] = url

    return urls


def find_wicket_link(html: str, element_id: str) -> Optional[str]:
    """
    Находит URL для конкретного элемента.

    Args:
        html: HTML контент
        element_id: ID элемента (например "ptx_combat_rich2_attack_link")

    Returns:
        URL или None если не найден
    """
    urls = parse_ajax_urls(html)
    return urls.get(element_id)


def get_attack_url(html: str) -> Optional[str]:
    """Получает URL кнопки атаки"""
    return find_wicket_link(html, "ptx_combat_rich2_attack_link")


def get_skill_urls(html: str) -> Dict[int, str]:
    """
    Получает URLs скиллов из HTML.

    Returns:
        Dict[skill_position (1-5), url]
    """
    urls = parse_ajax_urls(html)
    skills = {}

    for element_id, url in urls.items():
        if "skillBlock" in url and "skillLink" in url:
            match = re.search(r'skills-(\d+)-skillBlock', url)
            if match:
                skill_pos = int(match.group(1)) + 1  # 0-indexed -> 1-indexed
                skills[skill_pos] = url

    return skills


def get_source_urls(html: str) -> Dict[int, str]:
    """
    Получает URLs источников энергии.

    Returns:
        Dict[source_position (1-N), url]
    """
    urls = parse_ajax_urls(html)
    sources = {}

    for element_id, url in urls.items():
        if "sourceBlock" in url and "sourceBlockInner" in url:
            match = re.search(r'sources-(\d+)', url)
            if match:
                source_pos = int(match.group(1)) + 1
                sources[source_pos] = url

    return sources


def find_url_containing(html: str, *patterns: str) -> Optional[str]:
    """
    Находит URL содержащий все указанные паттерны.

    Args:
        html: HTML контент
        *patterns: Строки которые должны содержаться в URL

    Returns:
        URL или None

    Example:
        find_url_containing(html, "linkStartCombat")
        find_url_containing(html, "basket", "reset")
    """
    urls = parse_ajax_urls(html)

    for element_id, url in urls.items():
        if all(p in url for p in patterns):
            return url

    return None


class WicketParser:
    """
    Класс-обёртка для парсинга Wicket страниц.
    Кэширует результаты парсинга для повторного использования.
    """

    def __init__(self, html: str, base_url: str = ""):
        self.html = html
        self.base_url = base_url
        self._ajax_urls: Optional[Dict[str, str]] = None

    @property
    def ajax_urls(self) -> Dict[str, str]:
        """Ленивый парсинг AJAX URLs"""
        if self._ajax_urls is None:
            self._ajax_urls = parse_ajax_urls(self.html)
        return self._ajax_urls

    def get_url(self, element_id: str) -> Optional[str]:
        """Получает URL по ID элемента"""
        return self.ajax_urls.get(element_id)

    def get_attack_url(self) -> Optional[str]:
        """URL атаки"""
        return self.get_url("ptx_combat_rich2_attack_link")

    def get_skill_urls(self) -> Dict[int, str]:
        """URLs скиллов"""
        return get_skill_urls(self.html)

    def get_source_urls(self) -> Dict[int, str]:
        """URLs источников"""
        return get_source_urls(self.html)

    def find_url(self, *patterns: str) -> Optional[str]:
        """Найти URL содержащий паттерны"""
        return find_url_containing(self.html, *patterns)

    def has_element(self, element_id: str) -> bool:
        """Проверяет наличие элемента"""
        return element_id in self.ajax_urls
