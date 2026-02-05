# ============================================
# VMMO Sales Tracker - Статистика продаж
# ============================================
# Трекает что продалось, что вернулось (истекло)
# Данные для анализа спроса на крафт
# ============================================

import json
import os
import time
import fcntl
from datetime import datetime
from pathlib import Path

# Файл статистики (общий для всех ботов)
SALES_FILE = Path(__file__).parent.parent / "profiles" / "sales_stats.json"
LOCK_FILE = Path(__file__).parent.parent / "profiles" / ".sales_lock"


def _with_file_lock(func):
    """Декоратор для блокировки файла при записи"""
    def wrapper(*args, **kwargs):
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCK_FILE, "w") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)  # Эксклюзивная блокировка
                return func(*args, **kwargs)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)  # Снимаем блокировку
    return wrapper


def load_sales_stats() -> dict:
    """Загружает статистику продаж"""
    if not SALES_FILE.exists():
        return {
            "sold": [],      # Проданные лоты
            "expired": [],   # Истекшие (не проданные)
            "listed": [],    # Выставленные на аукцион
        }

    try:
        with open(SALES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[SALES] Ошибка загрузки: {e}")
        return {"sold": [], "expired": [], "listed": []}


def save_sales_stats(stats: dict):
    """Сохраняет статистику"""
    try:
        SALES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SALES_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[SALES] Ошибка сохранения: {e}")


@_with_file_lock
def record_sale(item_name: str, count: int, gold: int, silver: int, profile: str = "unknown"):
    """
    Записывает успешную продажу.

    Args:
        item_name: Название предмета
        count: Количество
        gold: Золото
        silver: Серебро
        profile: Профиль бота
    """
    stats = load_sales_stats()

    total_silver = gold * 100 + silver
    price_per_unit = total_silver // count if count > 0 else total_silver

    stats["sold"].append({
        "item": item_name,
        "count": count,
        "gold": gold,
        "silver": silver,
        "price_per_unit": price_per_unit,
        "profile": profile,
        "timestamp": datetime.now().isoformat(),
    })

    save_sales_stats(stats)
    print(f"[SALES] Записана продажа: {item_name} x{count} за {gold}g {silver}s")


@_with_file_lock
def record_expired(item_name: str, count: int = 1, profile: str = "unknown"):
    """
    Записывает истекший (не проданный) лот.

    Args:
        item_name: Название предмета
        count: Количество
        profile: Профиль бота
    """
    stats = load_sales_stats()

    stats["expired"].append({
        "item": item_name,
        "count": count,
        "profile": profile,
        "timestamp": datetime.now().isoformat(),
    })

    save_sales_stats(stats)
    print(f"[SALES] Записан истекший лот: {item_name} x{count}")


@_with_file_lock
def record_listed(item_name: str, count: int, gold: int, silver: int, profile: str = "unknown"):
    """
    Записывает выставленный на аукцион лот.

    Args:
        item_name: Название предмета
        count: Количество
        gold: Цена (золото)
        silver: Цена (серебро)
        profile: Профиль бота
    """
    stats = load_sales_stats()

    total_silver = gold * 100 + silver
    price_per_unit = total_silver // count if count > 0 else total_silver

    stats["listed"].append({
        "item": item_name,
        "count": count,
        "gold": gold,
        "silver": silver,
        "price_per_unit": price_per_unit,
        "profile": profile,
        "timestamp": datetime.now().isoformat(),
    })

    save_sales_stats(stats)


def get_sales_summary(days: int = 7) -> dict:
    """
    Получает сводку по продажам за N дней.

    Returns:
        dict: {item_name: {sold: X, expired: Y, sell_rate: Z%}}
    """
    stats = load_sales_stats()
    cutoff = datetime.now().timestamp() - (days * 24 * 3600)

    summary = {}

    # Считаем продажи
    for sale in stats.get("sold", []):
        try:
            ts = datetime.fromisoformat(sale["timestamp"]).timestamp()
            if ts < cutoff:
                continue
        except Exception:
            continue

        item = sale["item"]
        count = sale.get("count", 1)

        if item not in summary:
            summary[item] = {"sold": 0, "expired": 0, "total_gold": 0}

        summary[item]["sold"] += count
        summary[item]["total_gold"] += sale.get("gold", 0) + sale.get("silver", 0) / 100

    # Считаем истекшие
    for expired in stats.get("expired", []):
        try:
            ts = datetime.fromisoformat(expired["timestamp"]).timestamp()
            if ts < cutoff:
                continue
        except Exception:
            continue

        item = expired["item"]
        count = expired.get("count", 1)

        if item not in summary:
            summary[item] = {"sold": 0, "expired": 0, "total_gold": 0}

        summary[item]["expired"] += count

    # Считаем процент продаж
    for item, data in summary.items():
        total = data["sold"] + data["expired"]
        if total > 0:
            data["sell_rate"] = round(data["sold"] / total * 100, 1)
        else:
            data["sell_rate"] = 0

    return summary


def print_sales_report(days: int = 7):
    """Выводит отчёт по продажам"""
    summary = get_sales_summary(days)

    if not summary:
        print(f"Нет данных за последние {days} дней")
        return

    print(f"\n{'='*60}")
    print(f"СТАТИСТИКА ПРОДАЖ (последние {days} дней)")
    print(f"{'='*60}")
    print(f"{'Предмет':<25} {'Продано':>8} {'Истекло':>8} {'Успех %':>8} {'Доход':>10}")
    print("-" * 60)

    # Сортируем по проценту продаж
    sorted_items = sorted(summary.items(), key=lambda x: x[1]["sell_rate"], reverse=True)

    for item, data in sorted_items:
        gold = data["total_gold"]
        print(f"{item:<25} {data['sold']:>8} {data['expired']:>8} {data['sell_rate']:>7}% {gold:>9.1f}g")

    print("=" * 60)

    # Рекомендации
    print("\nРЕКОМЕНДАЦИИ:")
    for item, data in sorted_items:
        if data["sell_rate"] >= 80:
            print(f"  ✅ {item}: высокий спрос ({data['sell_rate']}%)")
        elif data["sell_rate"] <= 30 and (data["sold"] + data["expired"]) >= 5:
            print(f"  ❌ {item}: низкий спрос ({data['sell_rate']}%), рассмотреть отключение")


if __name__ == "__main__":
    print_sales_report(7)
