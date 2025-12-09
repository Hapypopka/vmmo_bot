# ============================================
# VMMO Dungeon Bot - Warrior
# ============================================
# Автоматизированный бот для прохождения подземелий
# Работает на Windows и Linux (сервер)
# ============================================

from playwright.sync_api import sync_playwright
import time
import json
import os
import sys
import threading
import argparse

# Определяем ОС для клавиатурного ввода
IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    import msvcrt
else:
    # На Linux/Mac клавиатурный ввод не поддерживается в фоне
    msvcrt = None

from config import (
    SCRIPT_DIR,
    BASE_URL,
    DUNGEONS_URL,
    RESTART_INTERVAL,
    MAX_NO_UNITS_ATTEMPTS,
    ATTACK_SELECTOR,
    BROWSER_VIEWPORT,
    BROWSER_SCREEN,
)
from dungeon_config import DUNGEON_ORDER, DUNGEONS, START_DUNGEON_INDEX
from utils import antibot_delay, log, safe_click, reset_watchdog, is_watchdog_triggered, get_watchdog_idle_time, init_logging, log_error, save_debug_screenshot
from popups import collect_loot, close_all_popups, priority_checks, emergency_unstuck
from backpack import cleanup_backpack_if_needed
from combat import (
    units_present,
    use_skills,
    check_dungeon_status,
    click_continue_battle,
    check_death,
)
from dungeon import (
    find_next_available_dungeon,
    get_min_cooldown_time,
    enter_dungeon,
    go_to_next_dungeon,
)
from combat import fight_in_hell_games
from navigation import smart_recovery, recover_to_dungeons
from stats import init_stats, get_stats, print_stats


# ========== УПРАВЛЕНИЕ ПАУЗОЙ ==========
class PauseController:
    """Контроллер паузы — нажми P для паузы/продолжения"""

    def __init__(self):
        self.paused = False
        self.running = True
        self._lock = threading.Lock()

    def toggle_pause(self):
        with self._lock:
            self.paused = not self.paused
            if self.paused:
                print(f"\n{'='*50}")
                print("⏸️  ПАУЗА — нажми P для продолжения")
                print(f"{'='*50}\n")
            else:
                print(f"\n{'='*50}")
                print("▶️  ПРОДОЛЖАЕМ")
                print(f"{'='*50}\n")

    def is_paused(self):
        with self._lock:
            return self.paused

    def stop(self):
        self.running = False


def keyboard_listener(controller):
    """Слушатель клавиатуры в отдельном потоке (только Windows)"""
    if not IS_WINDOWS or msvcrt is None:
        return  # На Linux не работает

    while controller.running:
        try:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                # P или p (английская) или з или З (русская раскладка)
                if key in [b'p', b'P', b'\xaf', b'\x8f']:  # p, P, з, З
                    controller.toggle_pause()
                # S или s — показать статистику
                elif key in [b's', b'S', b'\xfb', b'\xdb']:  # s, S, ы, Ы
                    print_stats()
            time.sleep(0.1)
        except Exception:
            pass


# Глобальный контроллер паузы
pause_controller = PauseController()


def main(headless=False, use_chromium=False):
    with sync_playwright() as p:
        # Запуск браузера (Chromium легче по памяти)
        if use_chromium:
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--disable-translate",
                    "--metrics-recording-only",
                    "--no-first-run",
                ]
            )
        else:
            browser = p.firefox.launch(
                headless=headless,
                args=["--start-maximized"]
            )

        # Контекст с размером экрана
        context = browser.new_context(
            viewport=BROWSER_VIEWPORT,
            screen=BROWSER_SCREEN,
        )

        # Загружаем куки
        cookies_path = os.path.join(SCRIPT_DIR, "cookies.json")
        print(f"📁 Загружаем куки из: {cookies_path}")
        with open(cookies_path, "r", encoding="utf-8") as f:
            saved_cookies = json.load(f)
        context.add_cookies(saved_cookies)

        page = context.new_page()

        # Заходим на главную, чтобы куки применились
        page.goto(BASE_URL)
        time.sleep(2)

        # Переходим на данжены
        page.goto(DUNGEONS_URL)
        time.sleep(6)

        if "login" in page.url:
            print("❌ Куки не сработали — логин")
            return

        print("✅ Бот запущен — страница данженов загружена")

        # Инициализируем статистику
        stats = init_stats()

        # Проверяем рюкзак перед началом
        cleanup_backpack_if_needed(page)

        # Ищем первый доступный данжен
        log("🔍 Ищем доступный данжен...")
        current_dungeon_index = find_next_available_dungeon(page, START_DUNGEON_INDEX - 1)

        if current_dungeon_index is None:
            # Все на КД — идём в Адские Игры
            min_cd, min_dungeon = get_min_cooldown_time(page)
            if min_cd and min_cd > 0:
                log(f"🎯 Минимальный КД: {min_dungeon} ({min_cd // 60}м {min_cd % 60}с)")
                fight_in_hell_games(page, min_cd)
                current_dungeon_index = find_next_available_dungeon(page, START_DUNGEON_INDEX - 1)

            if current_dungeon_index is None:
                print("❌ Все данжены на КД даже после ожидания!")
                return

        current_dungeon = DUNGEON_ORDER[current_dungeon_index]

        # Входим в данжен
        if not enter_dungeon(page, current_dungeon):
            print("❌ Не удалось войти в данжен")
            return

        print("✅ Вошли в данжен — начинаем бой")
        print(f"\n💡 Нажми P для паузы/продолжения\n")

        # Счётчики
        no_units_attempts = 0
        enter_failure_count = 0
        session_start_time = time.time()

        # ========== ОСНОВНОЙ ЦИКЛ БОЯ ==========
        while True:
            # Проверка паузы
            while pause_controller.is_paused():
                time.sleep(0.5)
                reset_watchdog()  # Не срабатывать во время паузы

            # Проверка времени для перезапуска
            elapsed = time.time() - session_start_time
            if elapsed >= RESTART_INTERVAL:
                log(f"🔄 Прошёл {RESTART_INTERVAL // 60} мин — перезапуск сессии...")
                # Завершаем сессию и выводим статистику
                stats.end_session()
                print(stats.get_session_summary())
                break

            # ===== WATCHDOG: Проверка застревания =====
            if is_watchdog_triggered():
                idle_time = int(get_watchdog_idle_time())
                log(f"🚨 WATCHDOG: Бот простаивает {idle_time} сек — запуск аварийного выхода")
                save_debug_screenshot(page, "watchdog")
                emergency_unstuck(page)
                no_units_attempts = 0
                continue

            try:
                # ===== ПРИОРИТЕТНЫЕ ПРОВЕРКИ =====
                # Если есть "Начать бой" или "Покинуть банду" — нажимаем и продолжаем
                if priority_checks(page):
                    no_units_attempts = 0
                    reset_watchdog()
                    continue

                # Закрытие попапов (включая "Банда собрана")
                close_all_popups(page)

                # Сбор лута
                collect_loot(page)

                # Проверка смерти
                if check_death(page):
                    stats.death_recorded(current_dungeon)
                    new_index, enter_failure_count = go_to_next_dungeon(
                        page, current_dungeon_index, enter_failure_count
                    )
                    if new_index is not None:
                        current_dungeon_index = new_index
                        current_dungeon = DUNGEON_ORDER[current_dungeon_index]
                    no_units_attempts = 0
                    continue

                # Проверка статуса подземелья
                status = check_dungeon_status(page)

                if status == "stage_complete":
                    stats.stage_completed()
                    click_continue_battle(page)
                    no_units_attempts = 0
                    reset_watchdog()
                    continue

                elif status == "dungeon_complete":
                    # Записываем завершение данжена
                    stats.dungeon_completed(current_dungeon, DUNGEONS.get(current_dungeon, {}).get("name"))
                    new_index, enter_failure_count = go_to_next_dungeon(
                        page, current_dungeon_index, enter_failure_count
                    )
                    if new_index is not None:
                        current_dungeon_index = new_index
                        current_dungeon = DUNGEON_ORDER[current_dungeon_index]
                    no_units_attempts = 0
                    reset_watchdog()
                    continue

                # Используем скиллы
                use_skills(page)

                # Проверяем юнитов
                if units_present(page):
                    no_units_attempts = 0
                    enter_failure_count = 0
                    reset_watchdog()  # Есть юниты = активность
                    log("⚔️ Есть юнит — атакуем!")

                    if safe_click(page, ATTACK_SELECTOR, timeout=5000):
                        log("🗡️ Атака!")
                        reset_watchdog()
                    else:
                        log("⚠️ Ошибка при атаке")

                else:
                    no_units_attempts += 1
                    log(f"❌ Юнитов нет — попытка {no_units_attempts}")

                    if no_units_attempts >= MAX_NO_UNITS_ATTEMPTS:
                        # Умное восстановление вместо простого handle_stuck
                        log("🧠 Запуск умного восстановления...")
                        action = smart_recovery(page, context="battle")

                        if action == "find_dungeon":
                            # Мы в подземельях - ищем новый данжен
                            new_index = find_next_available_dungeon(page, current_dungeon_index)
                            if new_index is not None:
                                current_dungeon_index = new_index
                                current_dungeon = DUNGEON_ORDER[current_dungeon_index]
                                if enter_dungeon(page, current_dungeon):
                                    log("✅ Вошли в новый данжен")
                                else:
                                    enter_failure_count += 1
                            else:
                                # Все на КД - идём в Адские Игры
                                min_cd, min_dungeon = get_min_cooldown_time(page)
                                if min_cd and min_cd > 0:
                                    log(f"🎯 Все на КД. Минимальный: {min_dungeon} ({min_cd // 60}м)")
                                    fight_in_hell_games(page, min_cd)

                        elif action == "continue_battle":
                            # Продолжаем бой
                            log("⚔️ Продолжаем бой")

                        no_units_attempts = 0
                        continue

                    safe_click(page, ATTACK_SELECTOR, timeout=2000)

                # Антибот задержка
                antibot_delay(0.8, 0.4)

            except Exception as e:
                log_error(f"Ошибка в основном цикле: {e}", page)
                # При ошибке пробуем восстановиться
                log("🔄 Попытка восстановления после ошибки...")
                if recover_to_dungeons(page):
                    # Ищем новый данжен
                    new_index = find_next_available_dungeon(page, current_dungeon_index)
                    if new_index is not None:
                        current_dungeon_index = new_index
                        current_dungeon = DUNGEON_ORDER[current_dungeon_index]
                        enter_dungeon(page, current_dungeon)
                antibot_delay(2, 2)


# ========== ЗАПУСК С АВТОПЕРЕЗАПУСКОМ ==========
if __name__ == "__main__":
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(description="VMMO Dungeon Bot - Warrior")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Запуск в headless режиме (без GUI, для серверов)"
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="Режим сервера: headless + без клавиатурного управления"
    )
    parser.add_argument(
        "--chromium",
        action="store_true",
        help="Использовать Chromium вместо Firefox (меньше памяти)"
    )
    args = parser.parse_args()

    # Устанавливаем режим headless
    headless_mode = args.headless or args.server
    use_chromium = args.chromium or args.server  # На сервере по умолчанию Chromium

    if headless_mode:
        print("🖥️  Режим: HEADLESS (без GUI)")
    else:
        print("🖥️  Режим: с GUI")

    if use_chromium:
        print("🌐 Браузер: Chromium (оптимизирован по памяти)")
    else:
        print("🦊 Браузер: Firefox")

    # Запускаем слушатель клавиатуры только на Windows и не в серверном режиме
    if IS_WINDOWS and not args.server:
        keyboard_thread = threading.Thread(target=keyboard_listener, args=(pause_controller,), daemon=True)
        keyboard_thread.start()
        print(f"\n{'='*50}")
        print("💡 Управление: P — пауза/продолжение, S — статистика")
        print(f"{'='*50}\n")
    else:
        print("ℹ️  Клавиатурное управление отключено (сервер/Linux)")

    # Инициализируем логирование в файл
    init_logging()
    log("🚀 Бот запущен")

    # Выводим накопленную статистику при запуске
    print_stats()

    restart_count = 0
    try:
        while True:
            restart_count += 1
            print(f"\n{'='*50}")
            print(f"🚀 Запуск сессии #{restart_count} — {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*50}\n")

            try:
                main(headless=headless_mode, use_chromium=use_chromium)
            except Exception as e:
                log_error(f"Критическая ошибка: {e}")

            print(f"\n{time.strftime('%H:%M:%S')} ⏳ Пауза 10 сек перед перезапуском...")
            time.sleep(10)
    finally:
        pause_controller.stop()
