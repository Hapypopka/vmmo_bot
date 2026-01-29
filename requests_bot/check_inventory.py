#!/usr/bin/env python3
"""
Check craft inventory across all profiles.
Usage: python -m requests_bot.check_inventory [--telegram]
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Путь к профилям
PROFILES_DIR = Path(__file__).parent.parent / "profiles"

# Названия предметов
ITEM_NAMES = {
    "rawOre": "Руда",
    "iron": "Железо",
    "ironBar": "Жел.Слиток",
    "copperOre": "Мед.Руда",
    "copper": "Медь",
    "copperBar": "Мед.Слиток",
    "bronze": "Бронза",
    "bronzeBar": "Бр.Слиток",
    "platinum": "Платина",
    "platinumBar": "Пл.Слиток",
    "thor": "Тор",
    "thorBar": "Тор.Слиток",
    "twilightSteel": "Сум.Сталь",
    "twilightAnthracite": "Сум.Антрацит",
}


def get_craft_inventory(profile: str) -> dict:
    """Получает инвентарь крафта из файла"""
    inv_file = PROFILES_DIR / profile / "craft_inventory.json"
    if not inv_file.exists():
        return {}

    try:
        with open(inv_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("inventory", {})
    except Exception:
        return {}


def get_craft_mode(profile: str) -> str:
    """Получает режим крафта из конфига"""
    config_file = PROFILES_DIR / profile / "config.json"
    if not config_file.exists():
        return "?"

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("craft_mode", "iron")
    except Exception:
        return "?"


def print_inventory_table():
    """Выводит таблицу инвентаря крафта"""
    print("=" * 80)
    print("ИНВЕНТАРЬ КРАФТА")
    print("=" * 80)

    # Заголовок
    print(f"{'Чар':<8} {'Режим':<8} | {'Руда':>5} {'Жел':>5} {'Слит':>5} | {'МедР':>5} {'Медь':>5} {'МСл':>5} {'Брон':>5} {'БрСл':>5}")
    print("-" * 80)

    # Суммы
    totals = {
        "rawOre": 0, "iron": 0, "ironBar": 0,
        "copperOre": 0, "copper": 0, "copperBar": 0,
        "bronze": 0, "bronzeBar": 0
    }

    # Профили
    profiles = sorted([d.name for d in PROFILES_DIR.iterdir() if d.is_dir() and d.name.startswith("char")])

    for profile in profiles:
        inv = get_craft_inventory(profile)
        mode = get_craft_mode(profile)

        if not inv:
            continue

        # Железная цепочка
        ore = inv.get("rawOre", 0)
        iron = inv.get("iron", 0)
        iron_bar = inv.get("ironBar", 0)

        # Медная/бронзовая цепочка
        cu_ore = inv.get("copperOre", 0)
        copper = inv.get("copper", 0)
        cu_bar = inv.get("copperBar", 0)
        bronze = inv.get("bronze", 0)
        br_bar = inv.get("bronzeBar", 0)

        # Суммируем
        totals["rawOre"] += ore
        totals["iron"] += iron
        totals["ironBar"] += iron_bar
        totals["copperOre"] += cu_ore
        totals["copper"] += copper
        totals["copperBar"] += cu_bar
        totals["bronze"] += bronze
        totals["bronzeBar"] += br_bar

        print(f"{profile:<8} {mode:<8} | {ore:>5} {iron:>5} {iron_bar:>5} | {cu_ore:>5} {copper:>5} {cu_bar:>5} {bronze:>5} {br_bar:>5}")

    # Итоги
    print("-" * 80)
    print(f"{'ИТОГО':<8} {'':<8} | {totals['rawOre']:>5} {totals['iron']:>5} {totals['ironBar']:>5} | {totals['copperOre']:>5} {totals['copper']:>5} {totals['copperBar']:>5} {totals['bronze']:>5} {totals['bronzeBar']:>5}")
    print("=" * 80)


def print_inventory_compact():
    """Компактный вывод для телеграма/веб-панели с детализацией"""
    lines = []
    lines.append("📦 ИНВЕНТАРЬ КРАФТА")
    lines.append("=" * 55)
    lines.append("")
    lines.append("Чар      Режим   | Руда Жел Слит | МРуд Медь МСл Брон БрСл")
    lines.append("-" * 55)

    # Суммы
    totals = {
        "rawOre": 0, "iron": 0, "ironBar": 0,
        "copperOre": 0, "copper": 0, "copperBar": 0,
        "bronze": 0, "bronzeBar": 0
    }

    profiles = sorted(
        [d.name for d in PROFILES_DIR.iterdir() if d.is_dir() and d.name.startswith("char")],
        key=lambda x: int(x[4:])
    )

    for profile in profiles:
        inv = get_craft_inventory(profile)
        mode = get_craft_mode(profile)

        if not inv:
            continue

        # Железная цепочка
        ore = inv.get("rawOre", 0)
        iron = inv.get("iron", 0)
        iron_bar = inv.get("ironBar", 0)

        # Медная/бронзовая цепочка
        cu_ore = inv.get("copperOre", 0)
        copper = inv.get("copper", 0)
        cu_bar = inv.get("copperBar", 0)
        bronze = inv.get("bronze", 0)
        br_bar = inv.get("bronzeBar", 0)

        # Суммируем
        totals["rawOre"] += ore
        totals["iron"] += iron
        totals["ironBar"] += iron_bar
        totals["copperOre"] += cu_ore
        totals["copper"] += copper
        totals["copperBar"] += cu_bar
        totals["bronze"] += bronze
        totals["bronzeBar"] += br_bar

        # Показываем только если есть что-то
        has_items = any([ore, iron, iron_bar, cu_ore, copper, cu_bar, bronze, br_bar])
        if has_items:
            lines.append(f"{profile:<8} {mode:<7} | {ore:>4} {iron:>3} {iron_bar:>4} | {cu_ore:>4} {copper:>4} {cu_bar:>3} {bronze:>4} {br_bar:>4}")

    lines.append("-" * 55)
    lines.append(f"{'ИТОГО':<8} {'':<7} | {totals['rawOre']:>4} {totals['iron']:>3} {totals['ironBar']:>4} | {totals['copperOre']:>4} {totals['copper']:>4} {totals['copperBar']:>3} {totals['bronze']:>4} {totals['bronzeBar']:>4}")
    lines.append("=" * 55)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Check craft inventory")
    parser.add_argument("--telegram", action="store_true", help="Compact output for telegram/web")
    args = parser.parse_args()

    if args.telegram:
        print(print_inventory_compact())
    else:
        print_inventory_table()


if __name__ == "__main__":
    main()
