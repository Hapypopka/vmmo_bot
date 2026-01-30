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
import logging
from datetime import datetime

# Добавляем родительскую папку в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Настройка логирования в файл
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "sell_crafts.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)


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

# Пути (SCRIPT_DIR уже определён выше для логов)
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")


def get_all_profiles() -> dict:
    """Динамически определяет все профили из папки profiles/"""
    profiles = {}
    if not os.path.exists(PROFILES_DIR):
        return profiles

    for name in sorted(os.listdir(PROFILES_DIR)):
        profile_dir = os.path.join(PROFILES_DIR, name)
        if os.path.isdir(profile_dir) and name.startswith("char"):
            # Пробуем получить имя из config.json
            config_path = os.path.join(profile_dir, "config.json")
            display_name = name
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        display_name = config.get("username", name)
                except Exception:
                    pass
            profiles[name] = display_name

    return profiles


# Профили определяются динамически
PROFILE_NAMES = get_all_profiles()


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


def sell_crafts_for_profile(profile: str, suppress_stdout: bool = False) -> dict:
    """
    Продаёт все крафты на аукцион для одного профиля.

    Args:
        profile: Имя профиля
        suppress_stdout: Подавлять stdout (для SSE режима)

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

    logger.info(f"=== Начинаю обработку {profile} ({name}) ===")

    # Проверяем, не запущен ли бот
    if is_bot_running(profile):
        result["skipped"] = True
        result["error"] = "бот работает"
        logger.info(f"{profile}: пропущен - бот работает")
        return result

    try:
        # В stream-режиме подавляем весь stdout чтобы не мешать SSE
        if suppress_stdout:
            original_stdout = sys.stdout
            sys.stdout = io.StringIO()

        try:
            logger.info(f"{profile}: устанавливаю профиль...")
            set_profile(profile)
            username, password = get_credentials()
            logger.info(f"{profile}: username={username}")

            logger.info(f"{profile}: создаю клиент...")
            client = VMMOClient()

            logger.info(f"{profile}: логинюсь...")
            if not client.login(username, password):
                result["error"] = "Не удалось авторизоваться"
                logger.error(f"{profile}: ошибка авторизации")
                return result

            logger.info(f"{profile}: авторизация успешна, создаю IronCraftClient...")

            # Импортируем IronCraftClient для sell_all_mining
            from requests_bot.craft import IronCraftClient
            craft = IronCraftClient(client)

            logger.info(f"{profile}: запускаю sell_all_mining(mode='all', force_min_stack=1)...")
            # Продаём все крафты на аукцион (force_min_stack=1 - продаём всё, игнорируя лимиты)
            sold_count = craft.sell_all_mining(mode="all", force_min_stack=1)
            result["sold"] = sold_count or 0

            logger.info(f"{profile}: завершено, продано: {sold_count}")
        finally:
            if suppress_stdout:
                sys.stdout = original_stdout

    except Exception as e:
        result["error"] = str(e)
        logger.exception(f"{profile}: ИСКЛЮЧЕНИЕ: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Продажа крафтов на аукционе")
    parser.add_argument("--telegram", action="store_true", help="Формат вывода для Telegram")
    parser.add_argument("--stream", action="store_true", help="Стриминг прогресса (для SSE)")
    parser.add_argument("--profile", type=str, help="Конкретный профиль")
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info(f"ЗАПУСК sell_crafts.py в {datetime.now()}")
    logger.info(f"Найдено профилей: {len(PROFILE_NAMES)}")
    logger.info(f"Профили: {list(PROFILE_NAMES.keys())}")

    # Определяем профили
    if args.profile:
        if args.profile not in PROFILE_NAMES:
            logger.error(f"Профиль {args.profile} не найден!")
            print(f"❌ Профиль {args.profile} не найден")
            sys.exit(1)
        profiles = [args.profile]
    else:
        profiles = list(PROFILE_NAMES.keys())

    logger.info(f"Будут обработаны: {profiles}")

    # Режим стриминга - выводим JSON для каждого профиля отдельно
    if args.stream:
        total = len(profiles)
        # Начальное событие
        print(json.dumps({"type": "start", "total": total}, ensure_ascii=False), flush=True)

        for i, profile in enumerate(profiles):
            # Событие "начал обработку"
            name = PROFILE_NAMES.get(profile, profile)
            print(json.dumps({
                "type": "processing",
                "profile": profile,
                "name": name,
                "current": i + 1,
                "total": total
            }, ensure_ascii=False), flush=True)

            result = sell_crafts_for_profile(profile, suppress_stdout=True)

            # Событие "результат"
            print(json.dumps({
                "type": "result",
                "profile": profile,
                "name": name,
                "sold": result.get("sold", 0),
                "skipped": result.get("skipped", False),
                "error": result.get("error"),
                "current": i + 1,
                "total": total
            }, ensure_ascii=False), flush=True)

        return

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
