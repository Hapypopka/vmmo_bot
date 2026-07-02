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
            "sold": [],       # Проданные лоты
            "expired": [],    # Истекшие (не проданные)
            "listed": [],     # Выставленные на аукцион
            "transfers": [],  # Лоты перегона золота (gold_transfer, не доход)
        }

    try:
        with open(SALES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("transfers", [])
            return data
    except Exception as e:
        print(f"[SALES] Ошибка загрузки: {e}")
        return {"sold": [], "expired": [], "listed": [], "transfers": []}


def save_sales_stats(stats: dict):
    """Сохраняет статистику"""
    try:
        SALES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SALES_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[SALES] Ошибка сохранения: {e}")


# Комиссия аукциона (продавец получает меньше выставленной цены)
AUCTION_FEE = 0.05

# Имя-заглушка, когда из письма не удалось извлечь название лота
UNKNOWN_ITEM = "(неизвестно)"


# Окно, в течение которого приход денег матчится с лотом перегона
TRANSFER_MATCH_WINDOW_SEC = 24 * 3600


@_with_file_lock
def record_transfer(gold: int, silver: int, profile: str = "unknown"):
    """
    Записывает лот ПЕРЕГОНА золота (gold_transfer): мейн продал рубины альту
    по завышенной цене. Это НЕ доход — деньги перекладываются между своими
    чарами. Позже record_sale сматчит приход и пометит продажу как transfer.
    """
    stats = load_sales_stats()
    stats["transfers"].append({
        "gold": gold,
        "silver": silver,
        "total_silver": gold * 100 + silver,
        "profile": profile,
        "consumed": False,
        "timestamp": datetime.now().isoformat(),
    })
    save_sales_stats(stats)
    print(f"[SALES] Записан лот перегона: {gold}g {silver}s")


def _match_and_consume_transfer(stats: dict, total_silver: int) -> bool:
    """
    Проверяет, не является ли пришедшая сумма выкупом лота перегона.
    Перегонные лоты дорогие (Рубин 49-70g) и записаны в stats["transfers"];
    продавец получает цену за вычетом 5% комиссии. Матчим по сумме (gross или
    net) в пределах окна, помечаем лот consumed (чтобы не сматчить дважды).

    Returns:
        True, если приход — это перегон (не реальный доход).
    """
    from datetime import datetime as _dt
    now = _dt.now().timestamp()
    for t in reversed(stats.get("transfers", [])):
        if t.get("consumed"):
            continue
        try:
            ts = _dt.fromisoformat(t["timestamp"]).timestamp()
        except Exception:
            ts = now
        if now - ts > TRANSFER_MATCH_WINDOW_SEC:
            continue
        gross = t.get("total_silver", 0)
        net = round(gross * (1 - AUCTION_FEE))
        if abs(gross - total_silver) <= 1 or abs(net - total_silver) <= 1:
            t["consumed"] = True
            return True
    return False


# Окно, в пределах которого продажу можно сматчить с выставленным лотом
MATCH_WINDOW_SEC = 3 * 24 * 3600


def _match_listed_lot(stats: dict, profile: str, total_silver: int):
    """
    Матчит продажу с ранее выставленным лотом (FIFO — самый старый непогашенный
    первым) по профилю + цене (gross или net −5%). Помечает лот consumed,
    чтобы один лот не матчился с двумя продажами. Возвращает имя, количество и
    timestamp выставления (для расчёта времени до продажи).

    Returns:
        (item_name, count, listed_ts) или (None, None, None).
    """
    now = datetime.now().timestamp()
    for lot in stats.get("listed", []):  # forward = от старых к свежим (FIFO)
        if lot.get("consumed"):
            continue
        if lot.get("profile") != profile:
            continue
        ts_str = lot.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str).timestamp()
        except Exception:
            continue
        if now - ts > MATCH_WINDOW_SEC:
            continue
        lot_total = lot.get("gold", 0) * 100 + lot.get("silver", 0)
        net = round(lot_total * (1 - AUCTION_FEE))
        if abs(lot_total - total_silver) <= 1 or abs(net - total_silver) <= 1:
            lot["consumed"] = True
            return lot.get("item"), lot.get("count", 1), ts_str
    return None, None, None


@_with_file_lock
def record_sale(item_name: str, count: int, gold: int, silver: int, profile: str = "unknown"):
    """
    Записывает успешную продажу.

    Args:
        item_name: Название предмета (может быть UNKNOWN_ITEM/None — тогда
                   попытаемся восстановить по цене из stats["listed"])
        count: Количество
        gold: Золото
        silver: Серебро
        profile: Профиль бота
    """
    stats = load_sales_stats()

    total_silver = gold * 100 + silver
    price_per_unit = total_silver // count if count > 0 else total_silver

    # 1. Сначала проверяем — не выкуп ли это лота перегона золота.
    #    Это НЕ доход (деньги перекладываются между своими чарами).
    is_transfer = _match_and_consume_transfer(stats, total_silver)

    # 2. Если имя не извлеклось из письма — матчим по сумме прихода с ранее
    #    выставленным лотом (даёт и имя, и время до продажи = спрос).
    guessed = False
    time_to_sell = None  # секунд от выставления до продажи
    if not is_transfer and (not item_name or item_name == UNKNOWN_ITEM):
        g_name, g_count, listed_ts = _match_listed_lot(stats, profile, total_silver)
        if g_name:
            item_name = g_name
            if count <= 1 and g_count:
                count = g_count
            price_per_unit = total_silver // count if count > 0 else total_silver
            guessed = True
            if listed_ts:
                try:
                    delta = datetime.now().timestamp() - datetime.fromisoformat(listed_ts).timestamp()
                    if delta >= 0:
                        time_to_sell = int(delta)
                except Exception:
                    pass

    stats["sold"].append({
        "item": item_name or UNKNOWN_ITEM,
        "count": count,
        "gold": gold,
        "silver": silver,
        "price_per_unit": price_per_unit,
        "profile": profile,
        "guessed": guessed,           # имя восстановлено по цене, а не из письма
        "transfer": is_transfer,       # перегон золота, не считать доходом
        "time_to_sell": time_to_sell,  # секунд от выставления до продажи (спрос)
        "timestamp": datetime.now().isoformat(),
    })

    save_sales_stats(stats)
    if is_transfer:
        print(f"[SALES] Перегон золота (не доход): {gold}g {silver}s")
    else:
        suffix = " (по цене)" if guessed else ""
        print(f"[SALES] Записана продажа: {item_name or UNKNOWN_ITEM}{suffix} x{count} за {gold}g {silver}s")


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
