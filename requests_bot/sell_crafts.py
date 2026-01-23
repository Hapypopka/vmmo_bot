#!/usr/bin/env python3
"""
Скрипт для продажи всех крафтов на аукционе у всех персонажей.
Запускается как: python -m requests_bot.sell_crafts [--telegram]
"""

import os
import sys
import json
import argparse
import io

# Добавляем родительскую папку в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SuppressOutput:
    """Контекстный менеджер для подавления stdout/stderr"""
    def __init__(self):
        self._stdout = None
        self._stderr = None

    def __enter__(self):
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        return self

    def __exit__(self, *args):
        sys.stdout = self._stdout
        sys.stderr = self._stderr


# Импортируем с подавлением вывода
with SuppressOutput():
    from requests_bot.client import VMMOClient
    from requests_bot.config import set_profile, get_credentials

# Пути
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")

# Профили и имена
PROFILE_NAMES = {
    "char1": "nza",
    "char2": "Happypoq",
    "char3": "Arilyn",
    "char4": "Lovelion",
    "char5": "Хеппипопка",
    "char6": "Faizka",
    "char7": "Подкачок",
    "char8": "Один Чар",
}


def is_bot_running(profile: str) -> bool:
    """Проверяет, запущен ли бот для профиля (по lock файлу)"""
    lock_file = os.path.join(PROFILES_DIR, profile, ".lock")
    if not os.path.exists(lock_file):
        return False

    try:
        with open(lock_file, "r") as f:
            content = f.read().strip()

        if "|" in content:
            pid_str = content.split("|")[0]
        else:
            pid_str = content

        pid = int(pid_str)

        # Проверяем существует ли процесс
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def sell_crafts_for_profile(profile: str) -> dict:
    """
    Продаёт все крафты на аукцион для одного профиля.

    Returns:
        dict: {"profile": str, "name": str, "sold": int, "errors": int, "error": str|None, "skipped": bool}
    """
    name = PROFILE_NAMES.get(profile, profile)
    result = {
        "profile": profile,
        "name": name,
        "sold": 0,
        "errors": 0,
        "error": None,
        "skipped": False
    }

    # Проверяем, не запущен ли бот
    if is_bot_running(profile):
        result["skipped"] = True
        result["error"] = "бот работает"
        return result

    try:
        # Подавляем весь вывод от клиента
        with SuppressOutput():
            set_profile(profile)
            username, password = get_credentials()

            client = VMMOClient()
            if not client.login(username, password):
                result["error"] = "Не удалось авторизоваться"
                return result

            # Импортируем IronCraftClient для sell_all_mining
            from requests_bot.craft import IronCraftClient
            craft = IronCraftClient(client)

            # Продаём все крафты на аукцион
            craft.sell_all_mining(mode="all")

            result["sold"] = craft.auction_client.items_listed if hasattr(craft, 'auction_client') else 0

    except Exception as e:
        result["error"] = str(e)

    return result


def main():
    parser = argparse.ArgumentParser(description="Продажа крафтов на аукционе")
    parser.add_argument("--telegram", action="store_true", help="Формат вывода для Telegram")
    parser.add_argument("--profile", type=str, help="Конкретный профиль (char1-char8)")
    args = parser.parse_args()

    # Определяем профили
    if args.profile:
        if args.profile not in PROFILE_NAMES:
            print(f"❌ Профиль {args.profile} не найден")
            sys.exit(1)
        profiles = [args.profile]
    else:
        profiles = list(PROFILE_NAMES.keys())

    results = []
    for profile in profiles:
        result = sell_crafts_for_profile(profile)
        results.append(result)

    # Формат вывода
    if args.telegram:
        lines = ["💰 Продажа крафтов на аукционе:\n"]
        total_sold = 0
        total_skipped = 0

        for r in results:
            if r.get("skipped"):
                lines.append(f"⏭️ {r['name']}: пропущен (бот работает)")
                total_skipped += 1
            elif r["error"]:
                lines.append(f"❌ {r['name']}: {r['error']}")
            else:
                lines.append(f"✅ {r['name']}: продано")
                total_sold += 1

        processed = len(results) - total_skipped
        lines.append(f"\n📊 Обработано: {processed}, пропущено: {total_skipped}")
        print("\n".join(lines))
    else:
        # JSON для программного использования
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
