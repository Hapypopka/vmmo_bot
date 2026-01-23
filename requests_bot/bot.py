# ============================================
# VMMO Bot - Full Integration (requests version)
# ============================================
# Главный бот объединяющий все модули
# ============================================

import os
import sys
import time
import traceback as tb_module  # Alias чтобы избежать конфликтов

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient
from requests_bot.run_dungeon import DungeonRunner
from requests_bot.event_dungeon import (
    EventDungeonClient, EquipmentClient, try_event_dungeon, try_ny_event_dungeon, set_ny_event_cooldown,
    try_event_dungeon_generic, set_event_cooldown, EVENT_DUNGEONS
)
from requests_bot.hell_games import HellGamesClient, fight_in_hell_games
from requests_bot.survival_mines import SurvivalMinesClient, fight_in_survival_mines
from requests_bot.arena import ArenaClient
from requests_bot.mail import MailClient
from requests_bot.daily_rewards import DailyRewardsClient
from requests_bot.backpack import BackpackClient
from requests_bot.popups import PopupsClient
from requests_bot.pets import PetClient
from requests_bot.stats import init_stats, get_stats, print_stats, set_stats_profile
from requests_bot.watchdog import reset_watchdog, check_watchdog, reset_no_progress_counter
from requests_bot.config import (
    DUNGEONS_URL, BACKPACK_THRESHOLD, load_settings,
    set_profile, get_profile_name, get_profile_username, is_event_dungeon_enabled, get_credentials,
    is_pet_resurrection_enabled, record_death, is_survival_mines_enabled, get_survival_mines_max_wave,
    get_skill_cooldowns, get_survival_mines_max_level, is_dungeons_enabled,
    is_hell_games_enabled, is_light_side,
    is_iron_craft_enabled, get_craft_items,
    is_ny_event_dungeon_enabled,
    is_arena_enabled, get_arena_max_fights,
    is_resource_selling_enabled,
    is_daily_rewards_enabled
)
from requests_bot.sell_resources import sell_resources
from requests_bot.logger import (
    init_logger, get_log_file,
    log_info, log_warning, log_error, log_debug,
    log_session_start, log_session_end, log_cycle_start,
    log_dungeon_start, log_dungeon_result, log_watchdog
)
from requests_bot.resource_history import (
    start_bot_session, end_bot_session, save_snapshot, should_save_snapshot
)
from requests_bot.resources import parse_resources, start_session, update_resources

# Telegram уведомления (опционально)
try:
    from requests_bot.telegram_bot import notify_sync as telegram_notify
except ImportError:
    telegram_notify = lambda msg: None  # Заглушка если модуль недоступен


# Текущая активность бота (для TG бота)
import json
from datetime import datetime

def set_activity(activity: str):
    """Записывает текущую активность бота в status.json"""
    try:
        from requests_bot.config import PROFILE_DIR
        status_file = os.path.join(PROFILE_DIR, "status.json")
        data = {
            "activity": activity,
            "updated": datetime.now().isoformat()
        }
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except:
        pass  # Не критично


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

        # Настройки (сначала из settings.json, потом из профиля)
        self.settings = load_settings()
        from requests_bot.config import get_profile_config
        profile_config = get_profile_config()
        self.backpack_threshold = profile_config.get("backpack_threshold",
                                    self.settings.get("backpack_threshold", BACKPACK_THRESHOLD))

    def init_clients(self):
        """Инициализирует все клиенты"""
        self.dungeon_runner = DungeonRunner(self.client)
        self.mail_client = MailClient(self.client)
        self.daily_rewards_client = DailyRewardsClient(self.client)
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

        # Проверяем и ремонтируем снаряжение при старте
        try:
            if self.client.repair_equipment():
                log_info("Снаряжение отремонтировано при старте")
        except Exception as e:
            log_debug(f"Ошибка проверки ремонта: {e}")

        # ПЕРВЫМ ДЕЛОМ - проверяем крафт!
        log_info("[CRAFT] Проверяю крафт сразу после логина...")
        self.check_craft()

        # Инициализируем файловую статистику
        self.bot_stats = init_stats()
        print_stats()  # Показываем накопленную статистику

        return True

    def try_restart_craft(self):
        """Проверяет готовность крафта и перезапускает если готов"""
        # Если iron_craft включен - не используем repeat, логика крафта в другом месте
        if is_iron_craft_enabled():
            return False
        try:
            if self.backpack_client.repeat_craft_if_ready():
                log_info("Крафт перезапущен")
                return True
        except Exception as e:
            log_debug(f"Ошибка проверки крафта: {e}")
        return False

    def check_craft(self):
        """
        ГЛАВНАЯ проверка крафта - вызывается ВЕЗДЕ!
        Это первый приоритет бота - крафт важнее всего.

        Returns:
            bool: True если крафт был обработан (забран/запущен)
        """
        if not is_iron_craft_enabled():
            # Iron craft отключен - используем простую проверку repeat
            return self.try_restart_craft()

        try:
            # Вызываем в цикле пока возвращает wait_time <= 5 (был забор или продажа)
            # Это нужно чтобы после забора сразу запустился новый крафт
            crafted = False
            for _ in range(3):  # Максимум 3 итерации чтобы не зациклиться
                is_active, wait_time = self.do_craft_step()
                if is_active:
                    crafted = True
                if wait_time > 5:
                    break  # Крафт запущен или в процессе - выходим
            return crafted
        except Exception as e:
            log_error(f"[CRAFT] Ошибка в check_craft: {e}")
            return False

    def try_arena(self):
        """Запускает арену если включена. Вызывается один раз в начале сессии."""
        if not is_arena_enabled():
            return
        set_activity("🏟️ Арена")

        log_info("[ARENA] Проверяю арену...")
        try:
            arena = ArenaClient(self.client)
            max_fights = get_arena_max_fights()

            # Проверяем количество боёв
            fights = arena.get_fights_remaining()
            if fights <= 5:  # MIN_FIGHTS_LEFT из arena.py
                log_info(f"[ARENA] Мало боёв ({fights}), пропускаю")
                return

            log_info(f"[ARENA] Доступно {fights} боёв, запускаю сессию (макс {max_fights})")
            stats = arena.run_arena_session(max_fights=max_fights)

            log_info(f"[ARENA] Итог: {stats['fights']} боёв, {stats['wins']} побед, "
                    f"{stats['points']} очков, рейтинг {stats['rating_change']:+.1f}")

            # Отправляем в Telegram
            username = get_profile_username()
            telegram_notify(f"⚔️ [{username}] Арена: {stats['fights']} боёв, "
                          f"{stats['wins']} побед, {stats['points']} очков")

            # После арены проверяем - может умерли и надо воскреснуть
            if stats['fights'] > stats['wins']:
                log_info("[ARENA] Были поражения, проверяю воскрешение...")
                try:
                    self.dungeon_runner.resurrect()
                    self.check_and_resurrect_pet()
                    # Ремонтируем снаряжение
                    if self.client.repair_equipment():
                        log_info("Снаряжение отремонтировано после арены")
                except Exception as e:
                    log_debug(f"Ошибка воскрешения после арены: {e}")

            # После арены СРАЗУ проверяем крафт!
            self.check_craft()

        except Exception as e:
            log_error(f"[ARENA] Ошибка: {e}")
            log_debug(tb_module.format_exc())

    def check_and_collect_mail(self):
        """Проверяет и собирает почту"""
        log_debug("Проверяю почту...")

        # Проверяем крафт перед сбором почты
        self.check_craft()

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

    def check_and_collect_daily_rewards(self):
        """Проверяет и собирает ежедневные награды"""
        if not is_daily_rewards_enabled():
            return None

        log_debug("Проверяю ежедневные награды...")

        try:
            result = self.daily_rewards_client.check_and_collect()
            if result.get('collected'):
                item = result.get('item_name', 'Unknown')
                day = result.get('day', '?')
                log_info(f"[DAILY] Собрана награда дня {day}: {item}")
            return result
        except Exception as e:
            log_error(f"Ошибка ежедневных наград: {e}")
            log_debug(tb_module.format_exc())
            return None

    def cleanup_backpack(self):
        """Очищает рюкзак если нужно"""
        try:
            # Загружаем страницу с меню для получения актуального счётчика
            self.client.get("/city")

            # Проверяем крафт при каждой очистке рюкзака
            self.check_craft()

            current, total = self.backpack_client.get_backpack_count()
            log_debug(f"Рюкзак: {current}/{total}")

            if current >= self.backpack_threshold:
                log_info(f"Очищаю рюкзак ({current}/{total})...")
                stats = self.backpack_client.cleanup(profile=get_profile_name())
                # cleanup() возвращает: bonuses, disassembled, dropped
                disassembled = stats.get("disassembled", 0)
                dropped = stats.get("dropped", 0)
                total_cleaned = disassembled + dropped
                self.stats["items_sold"] += total_cleaned
                if total_cleaned > 0:
                    log_info(f"Очищено: {disassembled} разобрано, {dropped} выброшено")

            # Продажа ресурсов на аукционе (если включено)
            if is_resource_selling_enabled():
                try:
                    sell_stats = sell_resources(self.client)
                    if sell_stats.get("sold", 0) > 0:
                        log_info(f"Продано ресурсов: {sell_stats['sold']}")
                        self.stats["items_sold"] += sell_stats["sold"]
                except Exception as e:
                    log_error(f"Ошибка продажи ресурсов: {e}")

            # Обновляем ресурсы после любой проверки рюкзака
            try:
                self.backpack_client.open_backpack()
                resources = parse_resources(self.client.current_page)
                if resources:
                    update_resources(resources)
                    log_debug(f"Ресурсы обновлены: {resources}")
            except Exception as e:
                log_debug(f"Ошибка обновления ресурсов: {e}")

            return current >= self.backpack_threshold
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

    def do_craft_step(self):
        """
        Выполняет один шаг бесконечного цикла крафта.

        Использует craft_items - список предметов для постоянного крафта.
        Логика:
        1. Проверяет инвентарь - если накоплено >= batch_size → продаёт
        2. Проверяет статус крафта - если готов → забирает
        3. Если крафт не идёт → запускает новый крафт

        Returns:
            tuple: (crafting_active, wait_time) - крафт активен и сколько ждать
        """
        if not is_iron_craft_enabled():
            return False, 0

        try:
            from requests_bot.config import get_craft_items
            from requests_bot.craft import CyclicCraftClient

            items = get_craft_items()
            if not items:
                log_debug("[CRAFT] Список автокрафта пуст")
                return False, 0

            craft = CyclicCraftClient(self.client, profile=get_profile_name())
            return craft.do_cyclic_craft_step()

        except Exception as e:
            log_error(f"[CRAFT] Ошибка: {e}")
            return False, 0

    def try_event_dungeon(self):
        """Пробует войти в ивентовый данжен Сталкер (ОТКЛЮЧЁН)"""
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

    def try_ny_event_dungeon_method(self):
        """Пробует войти в NY ивент - Логово Демона Мороза"""
        log_debug("Проверяю NY ивент 'Логово Демона Мороза'...")
        try:
            result, cd_seconds = try_ny_event_dungeon(self.client)

            if result == "entered":
                log_info("Вошли в Логово Демона Мороза!")
                return True, 0
            elif result == "on_cooldown":
                log_debug(f"NY ивент на КД ({cd_seconds // 60}м)")
                return False, cd_seconds
            else:
                log_debug(f"NY ивент недоступен: {result}")
                return False, 0
        except Exception as e:
            log_error(f"Ошибка NY ивента: {e}")
            self.stats["errors"] += 1
            return False, 0

    def get_min_dungeon_cooldown(self):
        """Получает минимальный КД среди всех данженов"""
        # Если данжены отключены - всегда "на КД" для запуска шахты/hell games
        if not is_dungeons_enabled():
            return 600, "Disabled"

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

        ПРИОРИТЕТ: Крафт > Ивенты > Данжены > Hell Games
        Крафт проверяется ВЕЗДЕ перед каждым действием!
        """
        # Сбрасываем watchdog в начале цикла
        reset_watchdog()
        reset_no_progress_counter()

        # ============================================
        # ПЕРВЫМ ДЕЛОМ - КРАФТ! Это главный приоритет!
        # ============================================
        self.check_craft()

        # Периодически сохраняем снэпшот ресурсов (раз в час)
        try:
            if should_save_snapshot():
                self.backpack_client.open_backpack()
                resources = parse_resources(self.client.current_page)
                if resources:
                    save_snapshot(resources, 'auto')
                    log_debug(f"[HISTORY] Снэпшот сохранён: {resources}")
        except Exception as e:
            log_debug(f"Ошибка сохранения снэпшота: {e}")

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
            set_activity("⚔️ Сталкер (ивент)")
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
                # Ремонтируем снаряжение после смерти в ивенте
                try:
                    if self.client.repair_equipment():
                        log_info("Снаряжение отремонтировано после смерти")
                except Exception as e:
                    log_debug(f"Ошибка ремонта после смерти: {e}")

        # 1.5. Проверяем ВСЕ ивент-данжены - ЦИКЛ пока хоть один доступен
        if is_ny_event_dungeon_enabled():
            total_event_runs = 0

            # Проходим по всем ивент-данженам в цикле
            while True:
                event_entered_any = False

                for dungeon_key, dungeon_config in EVENT_DUNGEONS.items():
                    dungeon_name = dungeon_config["name"]
                    dungeon_id = dungeon_config["id"]

                    # Сначала очищаем рюкзак и почту
                    self.cleanup_backpack()
                    self.check_and_collect_mail()

                    # ОБЯЗАТЕЛЬНО проверяем крафт перед ивентом!
                    self.check_craft()

                    # Пробуем войти в ивент-данжен
                    log_debug(f"Проверяю ивент: {dungeon_name}...")
                    result, cd = try_event_dungeon_generic(self.client, dungeon_key)

                    if result == "on_cooldown":
                        log_debug(f"{dungeon_name} на КД ({cd // 60}м)")
                        continue
                    elif result == "error":
                        log_debug(f"{dungeon_name}: ошибка входа")
                        continue
                    elif result != "entered":
                        continue

                    # Успешно вошли - бой
                    event_entered_any = True
                    total_event_runs += 1
                    set_activity(f"⚔️ {dungeon_name}")
                    log_dungeon_start(dungeon_name, dungeon_id)
                    self.dungeon_runner.current_dungeon_id = dungeon_id
                    self.dungeon_runner.combat_url = self.client.current_url
                    fight_result, actions = self.dungeon_runner.fight_until_done()
                    self.stats["total_actions"] += actions

                    if fight_result == "completed":
                        self.stats["dungeons_completed"] += 1
                        log_dungeon_result(dungeon_name, fight_result, actions)
                        # Парсим реальное КД с сервера и записываем
                        set_event_cooldown(dungeon_key, self.client)
                        # Проверяем крафт после ивента!
                        self.check_craft()
                    elif fight_result == "died":
                        self.stats["deaths"] += 1
                        log_dungeon_result(dungeon_name, fight_result, actions)
                        self.dungeon_runner.resurrect()
                        self.check_and_resurrect_pet()
                        try:
                            if self.client.repair_equipment():
                                log_info("Снаряжение отремонтировано после смерти")
                        except Exception as e:
                            log_debug(f"Ошибка ремонта после смерти: {e}")
                        # Проверяем крафт даже после смерти!
                        self.check_craft()
                    else:
                        log_debug(f"{dungeon_name}: неизвестный результат '{fight_result}'")

                # Если ни в один ивент не вошли - все на КД, выходим
                if not event_entered_any:
                    log_debug("Все ивент-данжены на КД или недоступны")
                    break

            if total_event_runs > 0:
                log_info(f"Ивенты: завершено {total_event_runs} заходов")
        else:
            log_debug("Ивент-данжены отключены для этого профиля")

        # 2. Проверяем рюкзак и почту
        self.cleanup_backpack()
        self.check_and_collect_mail()

        # 2.1. Проверяем ежедневные награды (если включены)
        self.check_and_collect_daily_rewards()

        # 2.5. Проверяем крафт - используем единый метод
        self.check_craft()

        # 3. Получаем список данженов (если включены)
        dungeons = []
        api_link_url = None

        if is_dungeons_enabled():
            try:
                dungeons, api_link_url = self.dungeon_runner.get_all_available_dungeons()
            except Exception as e:
                log_error(f"Ошибка получения списка данженов: {e}")
                self.stats["errors"] += 1
        else:
            log_debug("Данжены отключены для этого профиля")

        if not dungeons:
            # Все на КД - выбираем чем заняться
            min_cd, _ = self.get_min_dungeon_cooldown()

            if min_cd > 0 and is_survival_mines_enabled():
                # Приоритет 1: Заброшенная Шахта (с бонусом гильдии)
                set_activity("⛏️ Заброшенная Шахта")
                log_info("Все данжены на КД. Заброшенная Шахта...")
                try:
                    max_wave = get_survival_mines_max_wave()
                    max_level = get_survival_mines_max_level()
                    skill_cds = get_skill_cooldowns()
                    result = fight_in_survival_mines(self.client, skill_cds, max_wave, max_level)

                    # Если достигнут максимальный уровень - останавливаем бота
                    if result == "max_level_reached":
                        username = get_profile_username()
                        log_info(f"Достигнут максимальный уровень ({max_level}), останавливаю бота!")
                        telegram_notify(f"🎉 [{username}] Достигнут уровень {max_level}! Бот остановлен.")
                        return False  # Останавливаем цикл
                except Exception as e:
                    log_error(f"Ошибка Заброшенной Шахты: {e}")
                    self.stats["errors"] += 1
                # После Survival Mines СРАЗУ проверяем крафт!
                self.check_craft()

            elif min_cd > 0 and is_iron_craft_enabled():
                # Приоритет 2: Крафт (пока ждём КД)
                log_info("Все данжены на КД. Проверяю крафт...")
                try:
                    crafting, craft_wait = self.do_craft_step()
                except Exception as e:
                    log_error(f"Ошибка крафта: {e}")
                    import traceback
                    tb_module.print_exc()
                    self.stats["errors"] += 1

                # После крафта идём в Hell Games (если включены)
                if is_hell_games_enabled():
                    # Перепроверяем данжи - может КД уже закончился!
                    dungeons_check, _ = self.dungeon_runner.get_all_available_dungeons()
                    if dungeons_check:
                        log_info("Данж вышел с КД во время крафта, пропускаем Hell Games")
                    else:
                        # Пересчитываем min_cd заново
                        min_cd_now, _ = self.get_min_dungeon_cooldown()
                        if min_cd_now > 0:
                            set_activity("🔥 Адские Игры")
                            log_info(f"Крафт запущен, идём в Hell Games на {min_cd_now // 60}м...")
                            self.stats["hell_games_time"] += min_cd_now
                            try:
                                fight_in_hell_games(self.client, min_cd_now, is_light_side=is_light_side(), profile=get_profile_name())
                            except Exception as e:
                                log_error(f"Ошибка Hell Games: {e}")
                                self.stats["errors"] += 1
                            # После Hell Games СРАЗУ проверяем крафт!
                            self.check_craft()
                else:
                    # Hell Games не включены - проверяем почту/рюкзак и ждём
                    wait_time = min(min_cd, 60)
                    set_activity(f"⏳ Ждём КД ({min_cd // 60}м)")
                    log_info(f"Hell Games выключены, проверяю почту и ждём {wait_time}с...")
                    self.check_and_collect_mail()
                    self.cleanup_backpack()
                    time.sleep(wait_time)

            elif min_cd > 0 and is_hell_games_enabled():
                # Приоритет 3: Hell Games
                set_activity("🔥 Адские Игры")
                log_info(f"Все данжены на КД. Hell Games на {min_cd // 60}м...")
                self.stats["hell_games_time"] += min_cd
                try:
                    fight_in_hell_games(self.client, min_cd, is_light_side=is_light_side(), profile=get_profile_name())
                except Exception as e:
                    log_error(f"Ошибка Hell Games: {e}")
                    self.stats["errors"] += 1
                # После Hell Games СРАЗУ проверяем крафт!
                self.check_craft()

            elif min_cd > 0:
                # Ничего не включено - просто ждём
                wait_time = min(min_cd, 60)  # Ждём максимум 60 сек за раз
                set_activity(f"⏳ Ждём КД ({min_cd // 60}м)")
                log_info(f"Все данжены на КД. Ждём {wait_time}с...")
                time.sleep(wait_time)

            # После активности СНАЧАЛА проверяем крафт!
            self.check_craft()

            # Потом проверяем данжены (если включены)
            if is_dungeons_enabled():
                try:
                    dungeons, api_link_url = self.dungeon_runner.get_all_available_dungeons()
                except Exception as e:
                    log_error(f"Ошибка получения данженов: {e}")
                    dungeons = []

        if not dungeons:
            log_debug("Данжены всё ещё на КД")
            return True  # Продолжаем цикл

        # 4. Проходим данжены по очереди
        for dungeon in dungeons:
            dungeon_name = dungeon['name']
            dungeon_id = dungeon['id']

            # ОБЯЗАТЕЛЬНО проверяем крафт перед КАЖДЫМ данженом!
            self.check_craft()

            set_activity(f"⚔️ {dungeon_name}")
            log_dungeon_start(dungeon_name, dungeon_id)

            try:
                # Входим в данжен
                enter_result = self.dungeon_runner.enter_dungeon(dungeon_id, api_link_url)
                if enter_result == "stuck":
                    # Баг игры: кнопка "Начать бой!" не работает (Пороги Шэдоу Гарда и др.)
                    log_warning(f"{dungeon_name}: застряли в лобби (баг игры), пропускаем")
                    continue
                if enter_result == "died":
                    # Подземелье закрыто - смерть без воскрешения (Пороги)
                    log_warning(f"{dungeon_name}: подземелье закрыто (смерть)")
                    self.stats["deaths"] += 1
                    # Записываем смерть и снижаем сложность
                    current_diff = self.dungeon_runner.current_difficulty
                    new_diff, should_skip = record_death(dungeon_id, dungeon_name, current_diff)
                    username = get_profile_username()
                    if should_skip:
                        telegram_notify(f"💀 [{username}] Умер в {dungeon_name} (normal) - данж скипается!")
                    else:
                        telegram_notify(f"💀 [{username}] Умер в {dungeon_name} ({current_diff} -> {new_diff})")
                    continue
                if not enter_result:
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

                    # ОБЯЗАТЕЛЬНО проверяем крафт после КАЖДОГО данжена!
                    self.check_craft()

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
                    # Ремонтируем снаряжение после смерти
                    try:
                        if self.client.repair_equipment():
                            log_info("Снаряжение отремонтировано после смерти")
                    except Exception as e:
                        log_debug(f"Ошибка ремонта после смерти: {e}")
                    # Проверяем крафт даже после смерти!
                    self.check_craft()

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
                log_debug(tb_module.format_exc())
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

        # Инициализируем сессию ресурсов
        try:
            self.backpack_client.open_backpack()
            resources = parse_resources(self.client.current_page)
            if resources:
                start_session(resources)
                log_info(f"[RESOURCES] Старт сессии: {resources}")

                # Сохраняем в историю и проверяем offline изменения
                session_id, offline_changes = start_bot_session(resources)
                self._history_session_id = session_id

                if offline_changes:
                    changes_str = ", ".join(
                        f"{k}: {v:+d}" for k, v in offline_changes['changes'].items()
                    )
                    log_info(f"[RESOURCES] Изменения вне бота: {changes_str}")
                    telegram_notify(f"📊 [{get_profile_username()}] Изменения вне бота:\n{changes_str}")
        except Exception as e:
            log_debug(f"Ошибка инициализации ресурсов: {e}")

        # Арена - только в начале сессии, один раз
        self.try_arena()

        cycle = 0
        try:
            while True:
                cycle += 1
                log_cycle_start(cycle)

                # Проверяем авторизацию в начале каждого цикла
                if not self.client.ensure_logged_in():
                    log_error("Не удалось восстановить сессию, выход")
                    break

                # Проверяем не умер ли персонаж (на кладбище)
                if self.client.is_dead():
                    log_warning("Персонаж на кладбище! Ухожу...")
                    self.stats["deaths"] += 1
                    telegram_notify(f"💀 [{get_profile_username()}] Умер в данже")
                    if not self.client.leave_graveyard():
                        log_error("Не удалось уйти с кладбища!")
                        time.sleep(60)
                        continue

                try:
                    if not self.run_dungeon_cycle():
                        break
                except Exception as e:
                    log_error(f"Критическая ошибка в цикле {cycle}: {e}")
                    log_debug(tb_module.format_exc())
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
            # Сохраняем финальные ресурсы в историю
            try:
                self.backpack_client.open_backpack()
                resources = parse_resources(self.client.current_page)
                if resources:
                    session_id = getattr(self, '_history_session_id', None)
                    end_bot_session(resources, session_id)
                    log_info(f"[RESOURCES] Сессия завершена, данные сохранены в историю")
            except Exception as e:
                log_debug(f"Ошибка сохранения финальных ресурсов: {e}")

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
