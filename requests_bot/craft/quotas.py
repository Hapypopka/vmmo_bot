# ============================================
# VMMO Craft Quotas
# ============================================
# Система квот для распределения ботов по рецептам
# ============================================

import time

from requests_bot.craft.recipes import RECIPES
from requests_bot.craft.distribution import (
    FileLock,
    FINAL_RECIPES,
    CRAFT_LOCKS_LOCKFILE,
    LOCK_TTL,
    load_craft_locks,
    save_craft_locks,
)


def _get_full_requirements_static(recipe_id, count=1):
    """
    Статическая версия get_full_requirements без необходимости создавать CraftPriceChecker.
    Рекурсивно вычисляет все базовые ресурсы для крафта.

    Returns:
        dict: {"minerals": int, "sapphires": int, "rubies": int, "silver": int, "total_time": int}
    """
    if recipe_id not in RECIPES:
        return {"minerals": 0, "sapphires": 0, "rubies": 0, "silver": 0, "total_time": 0}

    recipe = RECIPES[recipe_id]
    result = {
        "minerals": 0,
        "sapphires": 0,
        "rubies": 0,
        "silver": 0,
        "total_time": 0,
    }

    # Время на сам крафт
    result["total_time"] = recipe.get("craft_time", 0) * count

    # Ресурсы этого рецепта
    if "minerals" in recipe:
        result["minerals"] = recipe["minerals"] * count
    if "sapphires" in recipe:
        result["sapphires"] = recipe["sapphires"] * count
    if "rubies" in recipe:
        result["rubies"] = recipe["rubies"] * count
    if "silver" in recipe:
        result["silver"] = recipe["silver"] * count

    # Рекурсивно обрабатываем зависимости
    if "requires" in recipe:
        for req_id, req_count in recipe["requires"].items():
            total_req = req_count * count
            sub_req = _get_full_requirements_static(req_id, total_req)

            result["minerals"] += sub_req["minerals"]
            result["sapphires"] += sub_req["sapphires"]
            result["rubies"] += sub_req["rubies"]
            result["silver"] += sub_req["silver"]
            result["total_time"] += sub_req["total_time"]

    return result


def get_craft_time_hours(recipe_id):
    """
    Возвращает полное время крафта цепочки в часах.

    Args:
        recipe_id: ID рецепта

    Returns:
        float: время в часах
    """
    reqs = _get_full_requirements_static(recipe_id)
    return reqs["total_time"] / 3600


def get_max_bots_for_recipe(recipe_id):
    """
    Определяет максимум ботов для рецепта на основе времени крафта.

    Логика:
    - >= 4 часов (платиновый слиток ~13ч) → max 2 бота
    - >= 2 часов (бронзовый/торовый слиток) → max 3 бота
    - < 2 часов (быстрые крафты) → max 5 ботов

    Args:
        recipe_id: ID рецепта

    Returns:
        int: максимум ботов
    """
    hours = get_craft_time_hours(recipe_id)

    if hours >= 4:
        return 2  # Очень долгие крафты - только 1-2 бота
    elif hours >= 2:
        return 3  # Долгие крафты - до 3 ботов
    else:
        return 5  # Быстрые крафты - до 5 ботов


def get_optimal_batch_size(recipe_id):
    """
    Определяет оптимальный batch_size для продажи на основе времени крафта.

    Логика:
    - Очень долгий крафт (> 3ч) → 1 шт (платиновый слиток)
    - Долгий (1-3ч) → 2-3 шт (бронзовый слиток, слиток тора)
    - Средний (30м-1ч) → 5 шт (железный слиток, медный слиток)
    - Быстрый (10-30м) → 7 шт (бронза, железо)
    - Очень быстрый (< 10м) → 10 шт (медь, руда)

    Args:
        recipe_id: ID рецепта

    Returns:
        int: оптимальный batch_size
    """
    if recipe_id not in RECIPES:
        return 5  # дефолт

    reqs = _get_full_requirements_static(recipe_id)
    total_time_sec = reqs["total_time"]
    total_time_min = total_time_sec / 60

    if total_time_min > 180:  # > 3 часов
        return 1
    elif total_time_min > 120:  # 2-3 часа
        return 2
    elif total_time_min > 60:  # 1-2 часа
        return 3
    elif total_time_min > 30:  # 30м - 1ч
        return 5
    elif total_time_min > 10:  # 10-30м
        return 7
    else:  # < 10м
        return 10


def get_sorted_recipes_by_profit(cached_prices):
    """
    Возвращает список рецептов отсортированных по профиту.

    Args:
        cached_prices: dict {item_name: price}

    Returns:
        list: [(recipe_id, profit_per_hour), ...] отсортированный по убыванию профита
    """
    if not cached_prices:
        return [(r, 0) for r in FINAL_RECIPES]

    # Комиссия аукциона (5%)
    AUCTION_FEE = 0.05

    recipe_profits = []

    for recipe_id in FINAL_RECIPES:
        if recipe_id not in RECIPES:
            continue

        recipe = RECIPES[recipe_id]
        result_name = recipe["name"]
        sell_price = cached_prices.get(result_name, 0)

        if sell_price <= 0:
            recipe_profits.append((recipe_id, 0))
            continue

        # Расчёт себестоимости
        reqs = _get_full_requirements_static(recipe_id)
        mineral_price = cached_prices.get("Минерал", 0)

        total_cost = (
            reqs["minerals"] * mineral_price +
            reqs["silver"] / 100.0
        )
        total_time = reqs["total_time"]

        if total_time <= 0:
            recipe_profits.append((recipe_id, 0))
            continue

        # Учитываем комиссию аукциона 5%
        net_sell_price = sell_price * (1 - AUCTION_FEE)
        profit = net_sell_price - total_cost
        profit_per_hour = (profit / total_time) * 3600
        recipe_profits.append((recipe_id, profit_per_hour))

    # Сортируем по профиту (убывание)
    recipe_profits.sort(key=lambda x: x[1], reverse=True)
    return recipe_profits


def get_profitable_recipes(cached_prices):
    """
    Возвращает рецепты с профитом >= 10% от среднего (но >= 0).
    Fallback: топ-3 если ничего не прошло фильтр.

    Args:
        cached_prices: dict {item_name: price}

    Returns:
        list: [(recipe_id, profit_per_hour), ...] отсортированный по убыванию профита
    """
    sorted_recipes = get_sorted_recipes_by_profit(cached_prices)

    # Считаем средний профит среди положительных
    profits = [p for _, p in sorted_recipes if p > 0]
    if not profits:
        print("[CRAFT_QUOTAS] Все рецепты убыточные, берём топ-3")
        return sorted_recipes[:3]

    avg_profit = sum(profits) / len(profits)
    threshold = max(avg_profit * 0.1, 0)  # 10% от среднего, но не меньше 0

    profitable = [(r, p) for r, p in sorted_recipes if p >= threshold]

    if not profitable:
        print(f"[CRAFT_QUOTAS] Нет рецептов с профитом >= {threshold:.1f}з/ч, берём топ-3")
        return sorted_recipes[:3]

    print(f"[CRAFT_QUOTAS] Порог: {threshold:.1f}з/ч (10% от avg={avg_profit:.1f}), прошло: {len(profitable)} рецептов")
    return profitable


def calculate_quotas(profitable_recipes, total_bots=21):
    """
    Распределяет ботов по рецептам с учётом весов И времени крафта.

    Веса по позиции: 1-й=5, 2-й=4, 3-й=4, 4-й=3, 5-й=3, 6-й=2, остальные=1

    Args:
        profitable_recipes: list of (recipe_id, profit) отсортированный по убыванию
        total_bots: общее количество ботов

    Returns:
        dict: {recipe_id: quota, ...}
    """
    weights = [5, 4, 4, 3, 3, 2, 1, 1, 1, 1, 1]  # макс 11 рецептов

    quotas = {}
    remaining = total_bots

    for i, (recipe_id, profit) in enumerate(profitable_recipes):
        weight = weights[i] if i < len(weights) else 1
        max_for_this = get_max_bots_for_recipe(recipe_id)
        quota = min(weight, max_for_this, remaining)
        quotas[recipe_id] = quota
        remaining -= quota

        hours = get_craft_time_hours(recipe_id)
        if hours >= 2:
            print(f"[CRAFT_QUOTAS] {recipe_id}: {hours:.1f}ч → лимит {max_for_this} ботов")

        if remaining <= 0:
            break

    # Если остались боты - добавляем к рецептам где ещё есть место до лимита
    if remaining > 0:
        for recipe_id in quotas:
            max_for_this = get_max_bots_for_recipe(recipe_id)
            add = min(remaining, max_for_this - quotas[recipe_id])
            if add > 0:
                quotas[recipe_id] += add
                remaining -= add
            if remaining <= 0:
                break

    # Если ВСЁ ЕЩЁ остались боты - распределяем равномерно по ВСЕМ рецептам
    # КРОМЕ platinumBar (слишком долгий - 13ч)
    if remaining > 0:
        for recipe_id in FINAL_RECIPES:
            if recipe_id not in quotas:
                quotas[recipe_id] = 0

        while remaining > 0:
            eligible = {r: q for r, q in quotas.items() if r != "platinumBar"}
            if not eligible:
                eligible = quotas

            min_recipe = min(eligible.keys(), key=lambda r: quotas[r])
            quotas[min_recipe] += 1
            remaining -= 1

        print(f"[CRAFT_QUOTAS] Равномерно распределены лишние боты")

    return quotas


def acquire_craft_lock(profile, cached_prices=None):
    """
    Берёт лок на крафт для профиля (с file lock для атомарности).

    Логика:
    1. Если у профиля есть активный лок - продлеваем
    2. Получаем профитные рецепты и квоты
    3. Считаем сколько ботов на каждом рецепте
    4. Берём рецепт где quota > текущих ботов
    5. Если все квоты заполнены - берём топовый

    Args:
        profile: имя профиля (char1, char2, ...)
        cached_prices: кэш цен (опционально, для расчёта профита)

    Returns:
        str: recipe_id который взяли
    """
    try:
        with FileLock(CRAFT_LOCKS_LOCKFILE):
            locks = load_craft_locks()
            now = time.time()

            # Проверяем - может у нас уже есть активный лок?
            if profile in locks:
                lock_info = locks[profile]
                if now - lock_info.get("timestamp", 0) <= LOCK_TTL:
                    recipe_id = lock_info.get("recipe_id")
                    locks[profile]["timestamp"] = now
                    save_craft_locks(locks)
                    return recipe_id

            # Считаем активных ботов
            active_bots = 0
            for p, lock_info in locks.items():
                timestamp = lock_info.get("timestamp", 0)
                if now - timestamp <= LOCK_TTL:
                    active_bots += 1

            # Получаем профитные рецепты и рассчитываем квоты
            profitable = get_profitable_recipes(cached_prices)
            quotas = calculate_quotas(profitable, total_bots=max(active_bots + 1, 21))

            # Считаем ботов на каждом рецепте
            bot_counts = {recipe: 0 for recipe in FINAL_RECIPES}
            for p, lock_info in locks.items():
                recipe_id = lock_info.get("recipe_id")
                if not recipe_id or recipe_id not in FINAL_RECIPES:
                    continue
                timestamp = lock_info.get("timestamp", 0)
                if now - timestamp > LOCK_TTL:
                    continue
                bot_counts[recipe_id] = bot_counts.get(recipe_id, 0) + 1

            # Ищем рецепт где quota > текущих ботов
            for recipe_id, profit in profitable:
                quota = quotas.get(recipe_id, 0)
                current = bot_counts.get(recipe_id, 0)
                if current < quota:
                    locks[profile] = {"recipe_id": recipe_id, "timestamp": now}
                    save_craft_locks(locks)
                    print(f"[CRAFT_LOCKS] {profile}: взял {recipe_id} (ботов: {current}/{quota}, профит: {profit:.1f}з/ч)")
                    return recipe_id

            # Все квоты заполнены - берём топовый рецепт
            if profitable:
                recipe_id = profitable[0][0]
                profit = profitable[0][1]
                current = bot_counts.get(recipe_id, 0)
                locks[profile] = {"recipe_id": recipe_id, "timestamp": now}
                save_craft_locks(locks)
                print(f"[CRAFT_LOCKS] {profile}: все квоты заполнены, превышаю на {recipe_id} (ботов: {current}+1, профит: {profit:.1f}з/ч)")
                return recipe_id

            # Fallback - первый из списка
            recipe_id = FINAL_RECIPES[0]
            locks[profile] = {"recipe_id": recipe_id, "timestamp": now}
            save_craft_locks(locks)
            print(f"[CRAFT_LOCKS] {profile}: fallback на {recipe_id}")
            return recipe_id

    except Exception as e:
        print(f"[CRAFT_LOCKS] Ошибка acquire_craft_lock: {e}")
        return FINAL_RECIPES[0]
