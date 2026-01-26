# ============================================
# VMMO Craft Package
# ============================================
# Система крафта для горного дела
# ============================================

# Экспорт констант из recipes.py
from .recipes import (
    ITEM_NAMES,
    RECIPES,
    CRAFT_ORDER_IRON,
    CRAFT_ORDER_BRONZE,
    _RECIPE_PAGE_CACHE,
    get_recipe,
    get_item_name,
    get_craft_time,
    get_recipe_level,
    get_recipe_requires,
)

# Экспорт из distribution.py (локи, координация)
from .distribution import (
    FileLock,
    FINAL_RECIPES,
    CRAFT_LOCKS_FILE,
    CRAFT_LOCKS_LOCKFILE,
    LOCK_TTL,
    load_craft_locks,
    save_craft_locks,
    get_recipe_bot_counts,
    refresh_craft_lock,
    update_craft_progress,
    release_craft_lock,
)

# Экспорт из quotas.py (квоты, распределение)
from .quotas import (
    _get_full_requirements_static,
    get_craft_time_hours,
    get_max_bots_for_recipe,
    get_optimal_batch_size,
    get_sorted_recipes_by_profit,
    get_profitable_recipes,
    calculate_quotas,
    acquire_craft_lock,
)

# Экспорт из prices.py (кэш цен)
from .prices import (
    SHARED_CACHE_FILE,
    CACHE_UPDATE_LOCKFILE,
    CACHE_TTL,
    AUCTION_FEE,
    AUCTION_CATEGORIES,
    load_shared_cache,
    save_shared_cache,
    get_cached_price,
    is_cache_expired,
)

# Классы остаются в основном модуле requests_bot/craft.py
# для обратной совместимости (IronCraftClient, CyclicCraftClient)
