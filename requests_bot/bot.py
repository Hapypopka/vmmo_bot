# ============================================
# VMMO Bot - Full Integration (requests version)
# ============================================
# Главный бот объединяющий все модули
# ============================================

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient
from requests_bot.run_dungeon import DungeonRunner
from requests_bot.event_dungeon import EventDungeonClient, EquipmentClient, try_event_dungeon
from requests_bot.hell_games import HellGamesClient, fight_in_hell_games
from requests_bot.mail import MailClient
from requests_bot.backpack import BackpackClient
from requests_bot.popups import PopupsClient
from requests_bot.pets import PetClient
from requests_bot.stats import init_stats, get_stats, print_stats, set_stats_profile
from requests_bot.watchdog import reset_watchdog, check_watchdog, reset_no_progress_counter
from requests_bot.config import (
    DUNGEONS_URL, BACKPACK_THRESHOLD, load_settings,
    set_profile, get_profile_name, get_profile_username, is_event_dungeon_enabled, get_credentials,
    is_pet_resurrection_enabled, record_death
)
from requests_bot.logger import (
    init_logger, get_log_file,
    log_info, log_warning, log_error, log_debug,
    log_session_start, log_session_end, log_cycle_start,
    log_dungeon_start, log_dungeon_result, log_watchdog
)

# Telegram уведомления (опционально)
try:
    from requests_bot.telegram_bot import notify_sync as telegram_notify
except ImportError:
    telegram_notify = lambda msg: None  # Заглушка если модуль недоступен


class VMMOBot:
    """Главный бот для VMMO"""

    def __init__(self):
        # Инициализируем логгер первым делом
        self.logger = init_logger()

        self.client = VMMOClient()
        self.dungeon_runner = None
        self.mail_client = None
        self.backpack_client = None
        self.popups_client = None
        self.event_client = None
        self.equip_client = None
        self.pet_client = None

        # Статистика (файловая)
        self.bot_stats = None

        # Локальная статистика сессии
        self.stats = {
            "dungeons_completed": 0,
            "deaths": 0,
            "total_actions": 0,
            "gold_collected": 0,
            "silver_collected": 0,
            "items_sold": 0,
            "hell_games_time": 0,
            "watchdog_triggers": 0,
            "errors": 0,
            "pets_resurrected": 0,
        }

        # Настройки
        self.settings = load_settings()
        self.backpack_threshold = self.settings.get("backpack_threshold", BACKPACK_THRESHOLD)

    def init_clients(self):
        """Инициализирует все клиенты"""
        self.dungeon_runner = DungeonRunner(self.client)
        self.mail_client = MailClient(self.client)
        self.backpack_client = BackpackClient(self.client)
        self.popups_client = PopupsClient(self.client)
        self.event_client = EventDungeonClient(self.client)
        self.equip_client = EquipmentClient(self.client)
        self.pet_client = PetClient(self.client)

    def login(self):
        """Авторизация"""
        log_info("Авторизация...")
        self.client.load_cookies()

        if not self.client.is_logged_in():
            log_warning("Куки устарели, логинимся...")
            # Берём креды из профиля
            username, password = get_credentials()
            if not self.client.login(username, password):
                log_error("Ошибка авторизации!")
                return False

        log_info("Авторизация успешна!")
        self.init_clients()

        # Инициализируем файловую статистику
        self.bot_stats = init_stats()
        print_stats()  # Показываем накопленную статистику

        return True

    def check_and_collect_mail(self):
        """Проверяет и собирает почту"""
        log_debug("Проверяю почту...")
        try:
            stats = self.mail_client.check_and_collect(
                on_backpack_full=self.cleanup_backpack
            )
            gold = stats.get("gold", 0)
            silver = stats.get("silver", 0)
            self.stats["gold_collected"] += gold
            self.stats["silver_collected"] += silver
            if gold > 0 or silver > 0:
                log_info(f"Почта: +{gold}g +{silver}s")
            return stats
        except Exception as e:
            log_error(f"Ошибка почты: {e}")
            self.stats["errors"] += 1
            return {}

    def cleanup_backpack(self):
        """Очищает рюкзак если нужно"""
        try:
            # Загружаем страницу с меню для получения актуального счётчика
            self.client.get("/city")
            current, total = self.backpack_client.get_backpack_count()
            log_debug(f"Рюкзак: {current}/{total}")

            if current >= self.backpack_threshold:
                log_info(f"Очищаю рюкзак ({current}/{total})...")
                stats = self.backpack_client.cleanup()
                # cleanup() возвращает: bonuses, disassembled, dropped
                disassembled = stats.get("disassembled", 0)
                dropped = stats.get("dropped", 0)
                total_cleaned = disassembled + dropped
                self.stats["items_sold"] += total_cleaned
                if total_cleaned > 0:
                    log_info(f"Очищено: {disassembled} разобрано, {dropped} выброшено")
                return True
        except Exception as e:
            log_error(f"Ошибка очистки рюкзака: {e}")
            self.stats["errors"] += 1
        return False

    def check_and_resurrect_pet(self):
        """Проверяет и воскрешает питомца если нужно"""
        if not is_pet_resurrection_enabled():
            return False

        try:
            if self.pet_client.check_and_resurrect():
                self.stats["pets_resurrected"] += 1
                log_info("Питомец воскрешён")
                return True
        except Exception as e:
            log_error(f"Ошибка воскрешения питомца: {e}")
            self.stats["errors"] += 1
        return False

    def try_event_dungeon(self):
        """Пробует войти в ивентовый данжен"""
        log_debug("Проверяю ивент 'Сталкер'...")
        try:
            result, cd_seconds = try_event_dungeon(self.client)

            if result == "entered":
                log_info("Вошли в ивентовый данжен!")
                return True, 0
            elif result == "on_cooldown":
                log_debug(f"Ивент на КД ({cd_seconds // 60}м)")
                return False, cd_seconds
            else:
                log_debug(f"Ивент недоступен: {result}")
                return False, 0
        except Exception as e:
            log_error(f"Ошибка ивента: {e}")
            self.stats["errors"] += 1
            return False, 0

    def get_min_dungeon_cooldown(self):
        """Получает минимальный КД среди всех данженов"""
        dungeons, _ = self.dungeon_runner.get_all_available_dungeons()
        if dungeons:
            return 0, None  # Есть доступные

        # Парсим КД из последнего вывода
        # TODO: улучшить - пока возвращаем фиксированное время
        return 600, "Unknown"  # 10 минут по умолчанию

    def run_dungeon_cycle(self):
        """
        Основной цикл прохождения данженов.
        Возвращает True если нужно продолжать, False для остановки.
        """
        # Сбрасываем watchdog в начале цикла
        reset_watchdog()
        reset_no_progress_counter()

        # Проверяем watchdog (если застряли)
        watchdog_result = check_watchdog(self.client, self.popups_client)
        if watchdog_result:
            log_watchdog(f"Сработал: {watchdog_result}")
            self.stats["watchdog_triggers"] += 1

        # 1. Проверяем ивент (если включен для профиля)
        entered_event = False
        event_cd = 0
        if is_event_dungeon_enabled():
            entered_event, event_cd = self.try_event_dungeon()
        else:
            log_debug("Ивент отключен для этого профиля")

        if entered_event:
            # Бой в ивенте
            log_dungeon_start("Сталкер (ивент)", "event_stalker")
            self.dungeon_runner.current_dungeon_id = "event_stalker"
            # Устанавливаем combat_url из текущего URL клиента
            self.dungeon_runner.combat_url = self.client.current_url
            result, actions = self.dungeon_runner.fight_until_done()
            self.stats["total_actions"] += actions

            if result == "completed":
                self.stats["dungeons_completed"] += 1
                log_dungeon_result("Сталкер (ивент)", result, actions)
            elif result == "died":
                self.stats["deaths"] += 1
                log_dungeon_result("Сталкер (ивент)", result, actions)
                self.dungeon_runner.resurrect()
                self.check_and_resurrect_pet()

        # 2. Проверяем рюкзак и почту
        self.cleanup_backpack()
        self.check_and_collect_mail()

        # 2.5. Проверяем готовый крафт (железо)
        try:
            if self.backpack_client.repeat_craft_if_ready():
                log_info("Крафт перезапущен")
        except Exception as e:
            log_debug(f"Ошибка проверки крафта: {e}")

        # 3. Получаем список данженов
        try:
            dungeons, api_link_url = self.dungeon_runner.get_all_available_dungeons()
        except Exception as e:
            log_error(f"Ошибка получения списка данженов: {e}")
            self.stats["errors"] += 1
            dungeons = []
            api_link_url = None

        if not dungeons:
            # Все на КД - идём в Hell Games (если включены)
            from requests_bot.config import is_hell_games_enabled
            min_cd, _ = self.get_min_dungeon_cooldown()
            if min_cd > 0 and is_hell_games_enabled():
                log_info(f"Все данжены на КД. Hell Games на {min_cd // 60}м...")
                self.stats["hell_games_time"] += min_cd
                try:
                    fight_in_hell_games(self.client, min_cd)
                except Exception as e:
                    log_error(f"Ошибка Hell Games: {e}")
                    self.stats["errors"] += 1
            elif min_cd > 0:
                # Hell Games отключены - просто ждём
                wait_time = min(min_cd, 60)  # Ждём максимум 60 сек за раз
                log_info(f"Все данжены на КД. Ждём {wait_time}с...")
                time.sleep(wait_time)

            # После Hell Games/ожидания снова проверяем данжены
            try:
                dungeons, api_link_url = self.dungeon_runner.get_all_available_dungeons()
            except Exception as e:
                log_error(f"Ошибка получения данженов после Hell Games: {e}")
                dungeons = []

        if not dungeons:
            log_debug("Данжены всё ещё на КД")
            return True  # Продолжаем цикл

        # 4. Проходим данжены по очереди
        for dungeon in dungeons:
            dungeon_name = dungeon['name']
            dungeon_id = dungeon['id']

            log_dungeon_start(dungeon_name, dungeon_id)

            try:
                # Входим в данжен
                if not self.dungeon_runner.enter_dungeon(dungeon_id, api_link_url):
                    log_warning(f"Не удалось войти в {dungeon_name}")
                    continue

                # Бой (лимит определяется автоматически по типу данжена)
                result, actions = self.dungeon_runner.fight_until_done()
                self.stats["total_actions"] += actions

                if result == "completed":
                    self.stats["dungeons_completed"] += 1
                    log_dungeon_result(dungeon_name, result, actions)

                    # Записываем в файловую статистику
                    if self.bot_stats:
                        self.bot_stats.dungeon_completed(dungeon_id, dungeon_name)
                        self.bot_stats.add_actions(actions)

                    # Очистка после данжена
                    self.cleanup_backpack()
                    self.check_and_collect_mail()
                    self.check_and_resurrect_pet()

                elif result == "died":
                    self.stats["deaths"] += 1
                    log_dungeon_result(dungeon_name, result, actions)

                    # Записываем смерть в файловую статистику
                    if self.bot_stats:
                        self.bot_stats.death_recorded(dungeon_id)

                    # Записываем смерть и снижаем сложность
                    current_diff = self.dungeon_runner.current_difficulty
                    new_diff, should_skip = record_death(dungeon_id, dungeon_name, current_diff)

                    # Уведомление в Telegram о смерти
                    username = get_profile_username()
                    if should_skip:
                        telegram_notify(f"💀 [{username}] Умер в {dungeon_name} (normal) - данж скипается!")
                    else:
                        telegram_notify(f"💀 [{username}] Умер в {dungeon_name} ({current_diff} -> {new_diff})")

                    self.dungeon_runner.resurrect()
                    self.check_and_resurrect_pet()

                elif result in ("watchdog", "stuck"):
                    self.stats["watchdog_triggers"] += 1
                    log_dungeon_result(dungeon_name, result, actions)
                    # Уведомление в Telegram о застревании
                    username = get_profile_username()
                    telegram_notify(f"⚠️ [{username}] Watchdog: застрял в {dungeon_name}")
                    # Пробуем вернуться в данжены
                    self.client.get("/dungeons?52")
                    reset_watchdog()

                else:
                    log_warning(f"Неизвестный результат: {result}")
                    log_dungeon_result(dungeon_name, result, actions)
                    # Пробуем вернуться в данжены
                    self.client.get("/dungeons?52")

            except Exception as e:
                log_error(f"Ошибка в данжене {dungeon_name}: {e}")
                log_debug(traceback.format_exc())
                self.stats["errors"] += 1
                # Пробуем восстановиться
                try:
                    self.client.get("/dungeons?52")
                except:
                    pass

            time.sleep(2)

        return True

    def print_session_stats(self):
        """Выводит статистику сессии"""
        stats_dict = {
            "Данженов пройдено": self.stats['dungeons_completed'],
            "Смертей": self.stats['deaths'],
            "Всего действий": self.stats['total_actions'],
            "Золото": self.stats['gold_collected'],
            "Серебро": self.stats['silver_collected'],
            "Продано предметов": self.stats['items_sold'],
            "Время в Hell Games": f"{self.stats['hell_games_time'] // 60}м",
            "Watchdog срабатываний": self.stats['watchdog_triggers'],
            "Питомцев воскрешено": self.stats['pets_resurrected'],
            "Ошибок": self.stats['errors'],
        }

        log_session_end(stats_dict)

        # Завершаем сессию и выводим общую статистику
        if self.bot_stats:
            self.bot_stats.end_session()
            print_stats()  # Выводит общую статистику из файла

    def run(self, max_cycles=None):
        """
        Запускает бота.

        Args:
            max_cycles: Максимальное количество циклов (None = бесконечно)
        """
        log_session_start()
        log_info(f"Лог файл: {get_log_file()}")

        if not self.login():
            return

        cycle = 0
        try:
            while True:
                cycle += 1
                log_cycle_start(cycle)

                try:
                    if not self.run_dungeon_cycle():
                        break
                except Exception as e:
                    log_error(f"Критическая ошибка в цикле {cycle}: {e}")
                    log_debug(traceback.format_exc())
                    self.stats["errors"] += 1
                    # Уведомление в Telegram
                    username = get_profile_username()
                    telegram_notify(f"🔴 [{username}] Критическая ошибка!\n{e}")
                    # Пробуем восстановиться
                    time.sleep(5)
                    try:
                        self.client.get("/dungeons?52")
                        reset_watchdog()
                    except:
                        pass

                if max_cycles and cycle >= max_cycles:
                    log_info(f"Достигнут лимит циклов ({max_cycles})")
                    break

                # Пауза между циклами
                time.sleep(5)

        except KeyboardInterrupt:
            log_warning("Остановлено пользователем (Ctrl+C)")

        finally:
            self.print_session_stats()


def main():
    """Точка входа"""
    import argparse
    import atexit

    parser = argparse.ArgumentParser(description="VMMO Bot (requests)")
    parser.add_argument("-p", "--profile", type=str, default=None,
                        help="Профиль персонажа (папка в profiles/)")
    parser.add_argument("--cycles", type=int, default=None,
                        help="Количество циклов (по умолчанию бесконечно)")
    parser.add_argument("--test", action="store_true",
                        help="Тестовый режим (1 цикл)")
    args = parser.parse_args()

    # Загружаем профиль если указан
    if args.profile:
        try:
            set_profile(args.profile)
            set_stats_profile(args.profile)  # Устанавливаем профиль для статистики
        except ValueError as e:
            print(f"[ERROR] {e}")
            return

    # Проверка на дубликат процесса через lock-файл
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profile_name = args.profile or "default"
    lock_file = os.path.join(script_dir, "profiles", profile_name, ".lock")

    # Проверяем существует ли lock и жив ли процесс
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r") as f:
                old_pid = int(f.read().strip())
            # Проверяем жив ли процесс
            os.kill(old_pid, 0)  # Не убивает, просто проверяет
            print(f"[ERROR] Бот {profile_name} уже запущен (PID: {old_pid}). Выход.")
            return
        except (ProcessLookupError, ValueError, PermissionError):
            # Процесс мёртв или PID невалидный - удаляем старый lock
            pass

    # Создаём lock-файл с нашим PID
    with open(lock_file, "w") as f:
        f.write(str(os.getpid()))

    # Удаляем lock при выходе
    def cleanup():
        try:
            os.remove(lock_file)
        except:
            pass
    atexit.register(cleanup)

    bot = VMMOBot()

    if args.test:
        bot.run(max_cycles=1)
    else:
        bot.run(max_cycles=args.cycles)


if __name__ == "__main__":
    main()
