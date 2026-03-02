# ============================================
# VMMO Resources Tracker
# ============================================
# Отслеживание ресурсов персонажа по сессиям
# ============================================

import os
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup

from requests_bot.config import PROFILES_DIR, get_profile_name

# Маппинг иконок на названия ресурсов
RESOURCE_ICONS = {
    "money_gold": "золото",
    "money_silver": "серебро",
    "skull": "черепа",
    "mineral": "минералы",
    "amethyst": "сапфиры",
    "ruby": "рубины",
    "stamp": "марки",
}

# Максимум сессий в истории
MAX_HISTORY = 5


def _get_resources_file():
    """Возвращает путь к файлу ресурсов текущего профиля"""
    profile = get_profile_name()
    if profile:
        return os.path.join(PROFILES_DIR, profile, "resources.json")
    return None


def _load_resources_data():
    """Загружает данные о ресурсах из файла"""
    filepath = _get_resources_file()
    if not filepath or not os.path.exists(filepath):
        return {"current_session": None, "history": []}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception):
        return {"current_session": None, "history": []}


def _save_resources_data(data):
    """Сохраняет данные о ресурсах в файл"""
    filepath = _get_resources_file()
    if not filepath:
        return

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[RESOURCES] Ошибка сохранения: {e}")


def parse_resources(html):
    """
    Парсит ресурсы из HTML страницы рюкзака.

    Структура HTML:
    <span class="res">
        <img src="/images/icons/money_gold.png">2363
    </span>

    Args:
        html: HTML страницы

    Returns:
        dict: {"золото": 123, "серебро": 45, ...} или None если не найдено
    """
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Ищем блок ресурсов
    resources_label = soup.find("span", class_="text-gold", string=re.compile(r"Ресурсы"))
    if not resources_label:
        return None

    # Родительский div содержит все ресурсы
    parent = resources_label.find_parent("div")
    if not parent:
        return None

    resources = {}

    # Парсим каждый span.res который содержит img
    for res_span in parent.find_all("span", class_="res"):
        # Ищем иконку ВНУТРИ этого span
        img = res_span.find("img")
        if img and img.get("src"):
            src = img.get("src", "")
            # Определяем тип ресурса по иконке
            for icon_key, rus_name in RESOURCE_ICONS.items():
                if icon_key in src:
                    # Число идёт после img, внутри того же span
                    # Берём весь текст span и извлекаем число
                    text = res_span.get_text(strip=True)
                    num = re.sub(r"[^\d]", "", text)
                    if num:
                        resources[rus_name] = int(num)
                    break

    return resources if resources else None


def reset_session_time():
    """
    Сбрасывает start_time текущей сессии на текущее время.
    Используется при старте бота, даже если не удалось распарсить ресурсы.
    """
    data = _load_resources_data()
    now = datetime.now().isoformat()

    if data.get("current_session"):
        data["current_session"]["start_time"] = now
        data["current_session"]["last_update"] = now
    else:
        # Создаём пустую сессию
        data["current_session"] = {
            "start_time": now,
            "last_update": now,
            "start": {},
            "current": {},
        }

    _save_resources_data(data)
    print(f"[RESOURCES] Сессия сброшена: {now}")


def start_session(resources):
    """
    Начинает новую сессию.
    Если была предыдущая сессия - сохраняет её в историю.

    Args:
        resources: dict с текущими ресурсами
    """
    if not resources:
        return

    data = _load_resources_data()
    now = datetime.now().isoformat()

    # Если была предыдущая сессия - сохраняем в историю
    if data.get("current_session") and data["current_session"].get("start"):
        old_session = data["current_session"]
        start_res = old_session.get("start", {})
        current_res = old_session.get("current", start_res)

        # Считаем заработанное
        earned = {}
        for key in current_res:
            diff = current_res.get(key, 0) - start_res.get(key, 0)
            if diff != 0:
                earned[key] = diff

        # Добавляем в историю
        history_entry = {
            "start_time": old_session.get("start_time"),
            "end_time": old_session.get("last_update", now),
            "earned": earned,
            "duration_hours": _calc_duration_hours(
                old_session.get("start_time"),
                old_session.get("last_update", now)
            )
        }

        data["history"].insert(0, history_entry)
        # Ограничиваем историю
        data["history"] = data["history"][:MAX_HISTORY]

    # Создаём новую сессию
    data["current_session"] = {
        "start_time": now,
        "last_update": now,
        "start": resources.copy(),
        "current": resources.copy(),
    }

    _save_resources_data(data)
    print(f"[RESOURCES] Новая сессия: {resources}")


def update_resources(resources):
    """
    Обновляет текущие ресурсы.

    Args:
        resources: dict с текущими ресурсами
    """
    if not resources:
        return

    data = _load_resources_data()

    # Если нет текущей сессии - создаём
    if not data.get("current_session"):
        start_session(resources)
        return

    # Защита от неполного парса — не перезаписывать если новых ресурсов меньше
    prev = data["current_session"].get("current", {})
    if prev and len(resources) < len(prev):
        # Мержим: обновляем только те ресурсы что пришли, остальные оставляем
        merged = prev.copy()
        merged.update(resources)
        data["current_session"]["current"] = merged
    else:
        data["current_session"]["current"] = resources.copy()
    data["current_session"]["last_update"] = datetime.now().isoformat()

    _save_resources_data(data)


def _calc_duration_hours(start_time_str, end_time_str):
    """Вычисляет длительность в часах"""
    try:
        start = datetime.fromisoformat(start_time_str)
        end = datetime.fromisoformat(end_time_str)
        delta = end - start
        return round(delta.total_seconds() / 3600, 1)
    except Exception:
        return 0


def get_session_stats():
    """
    Возвращает статистику текущей сессии и историю.

    Returns:
        dict: {
            "current": {"earned": {...}, "duration_hours": 5.2},
            "history": [...]
        }
    """
    data = _load_resources_data()
    result = {
        "current": None,
        "history": data.get("history", [])
    }

    session = data.get("current_session")
    if session and session.get("start"):
        start_res = session["start"]
        current_res = session.get("current", start_res)

        earned = {}
        for key in set(list(start_res.keys()) + list(current_res.keys())):
            diff = current_res.get(key, 0) - start_res.get(key, 0)
            if diff != 0:
                earned[key] = diff

        result["current"] = {
            "start_time": session.get("start_time"),
            "duration_hours": _calc_duration_hours(
                session.get("start_time"),
                session.get("last_update", datetime.now().isoformat())
            ),
            "earned": earned,
            "current_values": current_res,
        }

    return result


def format_stats_message(username):
    """
    Форматирует сообщение со статистикой для Telegram.

    Args:
        username: имя персонажа

    Returns:
        str: отформатированное сообщение
    """
    stats = get_session_stats()
    lines = [f"📊 Статистика {username}:"]

    # Текущая сессия
    if stats["current"]:
        curr = stats["current"]
        hours = curr["duration_hours"]
        lines.append(f"\n🔸 Текущая сессия ({hours:.1f}ч):")

        earned = curr["earned"]
        if earned:
            for res, val in earned.items():
                sign = "+" if val > 0 else ""
                lines.append(f"  {res}: {sign}{val}")
        else:
            lines.append("  (нет изменений)")

        # Текущие значения
        lines.append(f"\n💰 Сейчас:")
        for res, val in curr["current_values"].items():
            lines.append(f"  {res}: {val}")

    # История
    if stats["history"]:
        lines.append(f"\n📜 Последние сессии:")
        for i, h in enumerate(stats["history"][:5], 1):
            hours = h.get("duration_hours", 0)
            earned = h.get("earned", {})

            # Краткая сводка
            summary_parts = []
            if "золото" in earned:
                summary_parts.append(f"💰{earned['золото']:+d}")
            if "черепа" in earned:
                summary_parts.append(f"💀{earned['черепа']:+d}")
            if "минералы" in earned:
                summary_parts.append(f"⛏️{earned['минералы']:+d}")

            summary = ", ".join(summary_parts) if summary_parts else "нет данных"
            lines.append(f"  {i}. {hours:.1f}ч: {summary}")

    return "\n".join(lines)
