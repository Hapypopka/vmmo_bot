# ============================================
# VMMO Bot - Full Integration (requests version)
# ============================================
# Главный бот объединяющий все модули
# ============================================

import os
import sys
import time
import traceback as tb_module  # Alias чтобы избежать конфликтов
from datetime import datetime, timezone, timedelta
from requests.exceptions import ConnectionError as RequestsConnectionError

# Московское время (UTC+3)
MSK = timezone(timedelta(hours=3))
NIGHT_START = 0   # 00:00 МСК
NIGHT_END = 8     # 08:00 МСК

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient
from requests_bot.run_dungeon import DungeonRunner
# ARCHIVED: event_dungeon.py moved to archive/events/ (NY event ended 2026-01)
from requests_bot.hell_games import HellGamesClient, fight_in_hell_games
from requests_bot.survival_mines import SurvivalMinesClient, fight_in_survival_mines
from requests_bot.arena import ArenaClient
from requests_bot.mail import MailClient
from requests_bot.daily_rewards import DailyRewardsClient, LibraryClient
from requests_bot.backpack import BackpackClient
from requests_bot.popups import PopupsClient
from requests_bot.pets import PetClient
from requests_bot.stats import init_stats, get_stats, print_stats, set_stats_profile
from requests_bot.watchdog import (
    reset_watchdog, check_watchdog, reset_no_progress_counter,
    mark_progress, reset_progress_tracking, check_auto_recovery, trigger_auto_restart
)
from requests_bot.config import (
    DUNGEONS_URL, BACKPACK_THRESHOLD, load_settings,
    set_profile, get_profile_name, get_profile_username, get_credentials,
    is_pet_resurrection_enabled, record_death, record_lock, is_survival_mines_enabled, get_survival_mines_max_wave,
    get_skill_cooldowns, get_survival_mines_max_level, is_dungeons_enabled,
    is_hell_games_enabled, is_light_side,
    is_iron_craft_enabled, get_craft_items, is_sell_crafts_on_startup,
    is_craft_only_mode,
    is_arena_enabled, get_arena_max_fights, is_arena_gold,
    is_resource_selling_enabled,
    is_daily_rewards_enabled,
    is_valentine_event_enabled,
    is_party_dungeon_enabled, get_party_dungeon_config,
    is_event_party_enabled, get_event_party_config,
    is_wake_for_event_party_at_night,
)
from requests_bot.valentine_event import run_valentine_dungeons, VALENTINE_DUNGEONS, update_cooldowns_from_server as update_event_cooldowns


class AutoRestartException(Exception):
    """Бросается когда бот должен перезапуститься (re-login + новая сессия)"""
    pass
from requests_bot.party_dungeon import run_party_dungeon
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
from requests_bot.resources import parse_resources, start_session, update_resources, reset_session_time

# Telegram уведомления (опционально)
try:
    from requests_bot.telegram_bot import notify_sync as telegram_notify
except ImportError:
    telegram_notify = lambda msg: None  # Заглушка если модуль недоступен


# Текущая активность бота (для TG бота)
import json
from datetime import datetime

# Дебаунс записи status.json: если активность та же — пишем не чаще 1 раза в 3 сек.
# Смена активности пишется сразу.
_activity_last_value = None
_activity_last_write = 0.0

def set_activity(activity: str):
    """Записывает текущую активность бота в status.json"""
    global _activity_last_value, _activity_last_write
    now = time.time()
    if activity == _activity_last_value and (now - _activity_last_write) < 3.0:
        return
    try:
        from requests_bot.config import PROFILE_DIR
        status_file = os.path.join(PROFILE_DIR, "status.json")
        data = {
            "activity": activity,
            "updated": datetime.now().isoformat()
        }
        # Атомарная запись через temp+replace — веб-панель не прочитает полуфайл.
        tmp_file = status_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_file, status_file)
        _activity_last_value = activity
        _activity_last_write = now
    except Exception:
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
        self.craft_client = None  # Создаётся один раз, хранит выбранный рецепт

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
        self.mail_client = MailClient(self.client, profile=get_profile_name())
        self.daily_rewards_client = DailyRewardsClient(self.client)
        self.library_client = LibraryClient(self.client)
        self.backpack_client = BackpackClient(self.client)
        self.popups_client = PopupsClient(self.client)
        self.pet_client = PetClient(self.client)

        # Крафт клиент создаётся ОДИН РАЗ - хранит выбранный рецепт всю сессию
        if is_iron_craft_enabled():
            from requests_bot.craft import CyclicCraftClient
            self.craft_client = CyclicCraftClient(self.client, profile=get_profile_name())

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

        # Инициализируем сессию ресурсов ПЕРЕД крафтом
        # (иначе check_craft уходит на другую страницу и parse_resources не работает)
        self._init_resources_session()

        # Продаём ВСЕ крафты при старте (если включено)
        # Это очищает старые материалы от предыдущих режимов крафта
        if is_sell_crafts_on_startup() and is_iron_craft_enabled():
            try:
                log_info("[STARTUP] Продаю старые крафты перед началом...")
                from requests_bot.craft import IronCraftClient
                temp_craft = IronCraftClient(self.client)
                sold = temp_craft.sell_all_mining(mode="all", force_min_stack=1)
                if sold:
                    log_info(f"[STARTUP] Продано {sold} лотов")
            except Exception as e:
                log_warning(f"[STARTUP] Ошибка продажи крафтов: {e}")

        # Теперь проверяем крафт
        log_info("[CRAFT] Проверяю крафт сразу после логина...")
        self.check_craft()

        # Инициализируем файловую статистику
        self.bot_stats = init_stats()
        print_stats()  # Показываем накопленную статистику

        return True

    def _init_resources_session(self):
        """Инициализирует сессию трекинга ресурсов"""
        # ВСЕГДА сбрасываем время при старте бота
        reset_session_time()

        try:
            self.backpack_client.open_backpack()
            resources = parse_resources(self.client.current_page)
            if resources:
                start_session(resources)
                log_info(f"[RESOURCES] Старт сессии: {resources}")

                # Сохраняем в историю
                session_id, _ = start_bot_session(resources)
                self._history_session_id = session_id
            else:
                log_warning(f"[RESOURCES] Не удалось распарсить ресурсы! URL: {self.client.current_url}")
        except Exception as e:
            log_warning(f"[RESOURCES] Ошибка инициализации: {e}")

    def check_craft(self):
        """
        ГЛАВНАЯ проверка крафта - вызывается ВЕЗДЕ!
        Это первый приоритет бота - крафт важнее всего.

        Returns:
            bool: True если крафт был обработан (забран/запущен)
        """
        if not is_iron_craft_enabled():
            return False  # Крафт отключен

        # Быстрая проверка - если крафт ещё идёт, не делаем HTTP запросы
        from requests_bot.config import get_craft_finish_time
        finish_time = get_craft_finish_time()
        if finish_time and time.time() < finish_time:
            return False  # Крафт ещё идёт, рано проверять

        try:
            # Один вызов - забирает готовый и/или запускает новый
            is_active, wait_time = self.do_craft_step()
            return is_active
        except Exception as e:
            log_error(f"[CRAFT] Ошибка в check_craft: {e}")
            return False

    def try_arena(self):
        """Запускает арену если включена. Вызывается один раз в начале сессии."""
        if not is_arena_enabled() and not is_arena_gold():
            return
        set_activity("🏟️ Арена")

        log_info("[ARENA] Проверяю арену...")
        try:
            gold = is_arena_gold()
            arena = ArenaClient(self.client, gold=gold)
            max_fights = get_arena_max_fights()
            if gold:
                log_info("[ARENA] Режим: за золото")

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
            stop_reason = stats.get("stop_reason", "")
            if stop_reason:
                telegram_notify(f"🛑 [{username}] Арена остановлена: {stop_reason}\n"
                              f"{stats['fights']} боёв, {stats['wins']} побед")
            else:
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
                mark_progress("mail")  # Отмечаем прогресс
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

    def check_library(self):
        """Проверяет и открывает бесплатную книгу в Великой Библиотеке"""
        if not is_daily_rewards_enabled():
            return None

        try:
            self.library_client.check_and_collect()
        except Exception as e:
            log_error(f"Ошибка библиотеки: {e}")

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
                    mark_progress("item")  # Отмечаем прогресс

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

        Использует self.craft_client который создаётся ОДИН РАЗ при старте.
        Рецепт выбирается при первом вызове и крафтится всю сессию.

        Returns:
            tuple: (crafting_active, wait_time) - крафт активен и сколько ждать
        """
        if not is_iron_craft_enabled():
            return False, 0

        if not self.craft_client:
            log_debug("[CRAFT] Крафт клиент не инициализирован")
            return False, 0

        try:
            from requests_bot.config import get_craft_items, get_setting
            items = get_craft_items()
            auto_select = get_setting("auto_select_craft", True)
            if not items and not auto_select:
                log_debug("[CRAFT] Список автокрафта пуст и автовыбор выключен")
                return False, 0

            return self.craft_client.do_cyclic_craft_step()

        except Exception as e:
            log_error(f"[CRAFT] Ошибка: {e}")
            return False, 0

    def check_valentine_dungeons(self):
        """
        Проверяет и проходит ивент-данжены если доступны.
        Вызывается как в начале цикла, так и во время ожидания КД обычных данжей.

        Returns:
            int: Количество пройденных данженов
        """
        event_enabled = is_valentine_event_enabled()
        log_debug(f"[EVENT] check_valentine_dungeons вызван, enabled={event_enabled}")
        if not event_enabled:
            return 0

        # 2026-05-19: ивент Затерянный храм проходим соло на брутале —
        # event-party больше не нужна, блокировка снята.

        completed = 0
        try:
            from requests_bot.valentine_event import try_enter_dungeon, set_cooldown_after_completion, update_cooldowns_from_server
            # get_dungeon_difficulty/record_death раньше реэкспортились через valentine_event,
            # но я их там убрал при FireTower-фиксе — импортирую напрямую из config
            from requests_bot.config import get_dungeon_difficulty, record_death

            # Обновляем КД с сервера
            update_cooldowns_from_server(self.client)

            for dungeon_id, dungeon_config in VALENTINE_DUNGEONS.items():
                name = dungeon_config["name"]
                # Ключи VALENTINE_DUNGEONS без префикса dng: (нужно для URL).
                # А deaths.json / DUNGEON_ACTION_LIMITS / dungeon_difficulties
                # используют формат с префиксом — добавляем при lookup'ах.
                full_id = f"dng:{dungeon_id}"
                difficulty = get_dungeon_difficulty(full_id)
                # Ивент-данж использует ту же механику что обычные данжи:
                # деффолт brutal, понижение через deaths.json при смертях.
                if difficulty == "skip":
                    continue

                # Очищаем рюкзак перед ивентом
                self.cleanup_backpack()
                self.check_and_collect_mail()
                self.check_craft()

                result, cd = try_enter_dungeon(self.client, dungeon_id)

                if result == "on_cooldown":
                    log_debug(f"[EVENT] {name} на КД ({cd // 60}м)")
                    continue
                elif result in ("error", "skipped"):
                    continue
                elif result == "entered":
                    diff_name = {"brutal": "брутал", "hero": "героик", "normal": "нормал"}.get(difficulty, difficulty)
                    set_activity(f"☄️ {name} ({diff_name})")
                    log_info(f"[EVENT] Бой в {name} ({diff_name})...")
                    self.dungeon_runner.current_dungeon_id = full_id
                    self.dungeon_runner.combat_url = self.client.current_url
                    fight_result, actions = self.dungeon_runner.fight_until_done()
                    self.stats["total_actions"] += actions

                    if fight_result == "completed":
                        self.stats["dungeons_completed"] += 1
                        mark_progress("dungeon")
                        log_info(f"[EVENT] {name} пройден! ({actions} действий)")
                        set_cooldown_after_completion(self.client, dungeon_id)
                        completed += 1
                        self.check_craft()
                    elif fight_result == "died":
                        self.stats["deaths"] += 1
                        # Понижаем сложность (смерть при сетевых сбоях не считается)
                        new_diff, should_skip = record_death(
                            full_id, name, difficulty,
                            suspect=self.client.had_recent_net_error())
                        if should_skip:
                            log_warning(f"[EVENT] Смерть в {name} → СКИП")
                        else:
                            new_diff_name = {"brutal": "брутал", "hero": "героик", "normal": "нормал"}.get(new_diff, new_diff)
                            log_warning(f"[EVENT] Смерть в {name} → {new_diff_name}")
                        self.dungeon_runner.resurrect()
                        self.check_and_resurrect_pet()
                        try:
                            if self.client.repair_equipment():
                                log_info("Снаряжение отремонтировано после смерти")
                        except Exception as e:
                            log_debug(f"Ошибка ремонта: {e}")
                        self.check_craft()
                    else:
                        # Например max_actions_reached / timeout — fight_until_done не вернул
                        # ни completed ни died. На сервере данж мог зачёлкнуться (КД встанет),
                        # но мы это не зафиксировали — обновим КД на следующем тике.
                        log_warning(f"[EVENT] {name}: бой оборван ({fight_result}, {actions} действий)")
        except Exception as e:
            log_error(f"[EVENT] Ошибка: {e}")
            self.stats["errors"] += 1

        return completed

    def _cleanup_event_cooldowns_inactive(self):
        """Прокси на valentine_event.cleanup_inactive_event_cooldowns().

        Логика убрана в valentine_event.py чтобы не плодить дублирующих
        работ с shared_party_state.json в bot.py.
        """
        from requests_bot.valentine_event import cleanup_inactive_event_cooldowns
        cleanup_inactive_event_cooldowns()

    def _is_event_party_active(self):
        """Раньше блокировал одиночный заход в ивент чтобы не сломать координацию с мембером.
        2026-05-19: Затерянный храм проходим соло на брутале — event-party больше не нужна.
        Метод оставлен ради совместимости со старыми вызовами, всегда False."""
        return False

    def _sleep_with_event_party_wakeup(self):
        """Ночной режим с пробуждениями для ивент-пати.

        Логика разная для leader/member, чтобы они синхронизировались:

        2026-05-19: режим теперь СОЛО.
            Раньше будили мембера/лидера для координированной пати в FireTower.
            Сейчас Затерянный храм проходим в одиночку — просыпаемся когда
            КД=0, проходим, спим дальше до 08:00 МСК.

        Цикл:
            1. Спим ~5 мин (джиттер 270-330с).
            2. Если утро — выходим.
            3. ensure_logged_in (сессия могла протухнуть за ночь).
            4. update_cooldowns_from_server — свежий КД с сервера.
            5. Если ивент-данж доступен → check_valentine_dungeons() (соло).
            6. Обратно в сон.

        Никаких обычных данжей/крафта/арены ночью.
        """
        import random
        from requests_bot.valentine_event import (
            update_cooldowns_from_server as update_event_cooldowns,
            check_cooldown,
            VALENTINE_DUNGEONS,
        )

        log_info("🌙 Ночной режим (event-wake, соло): сплю до 08:00 МСК")
        set_activity("🌙 Сон (event-wake)")

        while True:
            # Спим джиттер ~5 мин: чаще не нужно, КД ивента 4-6ч
            jitter = random.randint(270, 330)
            time.sleep(jitter)

            # Проверка — настало ли утро
            now_msk = datetime.now(MSK)
            if not (NIGHT_START <= now_msk.hour < NIGHT_END):
                log_info("☀️ Утро — выхожу из ночного цикла")
                set_activity("☀️ Просыпаюсь")
                return

            try:
                if not self.client.ensure_logged_in():
                    log_warning("Не удалось залогиниться ночью — спим дальше")
                    continue

                # Обновляем КД с сервера — он же положит свежее в кэш
                update_event_cooldowns(self.client)

                # Проверяем — все ли ивент-данжи на КД?
                all_on_cd = all(
                    not check_cooldown(d_id)[0] for d_id in VALENTINE_DUNGEONS
                )
                if all_on_cd:
                    continue  # Все на КД — спим дальше

                log_info("⚡ Ивент-данж доступен ночью → захожу соло")
                set_activity("⚡ Ивент ночью (соло)")
                result = self.check_valentine_dungeons()
                log_info(f"🌙 Ночной заход завершён (пройдено: {result}), возвращаюсь в сон")
            except Exception as e:
                log_error(f"Ошибка ночного ивент-захода: {e}")
                log_debug(tb_module.format_exc())
            finally:
                set_activity("🌙 Сон (event-wake)")

    def check_event_party(self):
        """Координированная пати в ивент-данж.

        Логика разделена для leader/member чтобы не разсинхронизировались
        в дневном режиме (ночной режим уже синхронизирован отдельно):

        Мембер (быстрый путь, БЕЗ HTTP в большинстве вызовов):
            1. find_forming_party() — дешёвая проверка shared_party_state.json.
            2. Если forming-пати лидера НЕТ — return None СРАЗУ.
               Бот пойдёт делать обычные данжи / крафт. На следующем цикле
               снова дёшево проверит — затраты минимальны.
            3. Если forming-пати ЕСТЬ — обновляем КД с сервера, идём в
               run_event_party (там join + ждём инвайт).

            Раньше мембер ВСЕГДА делал HTTP-запрос update_event_cooldowns
            каждый цикл (~75с) → лидер инвайтил мембера в первые ~15с
            forming-окна, а мембер замечал forming через минуту. Они
            хронически промахивались друг по другу.

        Лидер:
            1. update_event_cooldowns с сервера → публикация в shared state.
            2. Проверка своего КД через shared state.
            3. Cleanup призрачных мемберов (event_party_enabled=False).
            4. run_event_party — соберёт мемберов, создаст пати, инвайтит.

        Returns:
            "completed"/"died"/"error"/"timeout" — результат боя
            "member_waiting" — мембер был в forming-пати, но что-то пошло не так
            None — пати нет, бот должен делать обычную активность
        """
        # 2026-05-19: Затерянный храм соло на брутале — event-party полностью отключена.
        # Игнорируем флаг event_party_enabled в конфигах (их деплоить нельзя).
        return None

        if not is_event_party_enabled():
            return None

        # Orphan-pending cooldown: после детекта застрявшего pending на мембере
        # дальнейшие попытки бесполезны до TTL. Спим 30 мин в памяти процесса
        # — после рестарта бота cooldown сбрасывается (и это намеренно: рестарт
        # бывает редко, не хочется чтобы он мешал восстановлению).
        import time as _t
        if getattr(self, "_event_party_orphan_until", 0) > _t.time():
            remaining = int(self._event_party_orphan_until - _t.time())
            log_debug(f"[EVENT-PARTY] Orphan-cooldown ещё {remaining}с, skip")
            return None

        from requests_bot.party_dungeon import run_event_party, find_forming_party
        from requests_bot.valentine_event import is_dungeon_on_cooldown_for_profile

        cfg = get_event_party_config()
        role = cfg.get("role", "member")
        dungeon_id = cfg.get("dungeon_id", "dng:FireTower")
        event_key = dungeon_id.replace("dng:", "")
        my_profile = get_profile_name()

        # === МЕМБЕР: быстрый путь без HTTP ===
        if role == "member":
            forming = find_forming_party(my_profile)
            if not forming or forming.get("dungeon_id") != dungeon_id:
                # Race-window: лидер мог запустить forming чуть позже мембера
                # (на ~5-15 сек — у обоих свои pre-cycle действия: лидер делает
                # update_event_cooldowns HTTP, мембер быстрее). Без retry мембер
                # упускал forming и уходил на 10-20 мин в обычку, а лидер
                # 180 сек впустую ждал в лобби. Делаем 5 повторов по 3 сек —
                # за 15 сек лидер успеет записать forming в shared state.
                import time as _t
                for _ in range(5):
                    _t.sleep(3)
                    forming = find_forming_party(my_profile)
                    if forming and forming.get("dungeon_id") == dungeon_id:
                        log_info(f"[EVENT-PARTY] Forming-пати найдена после ожидания")
                        break
                if not forming or forming.get("dungeon_id") != dungeon_id:
                    return None

            log_info(f"⚡ [EVENT-PARTY] Лидер создал forming-пати → присоединяюсь")
            try:
                update_event_cooldowns(self.client)
            except Exception as e:
                log_warning(f"[EVENT-PARTY] Не удалось обновить КД: {e}")

            # Свой КД мог появиться между циклами — перепроверим
            if is_dungeon_on_cooldown_for_profile(my_profile, event_key):
                log_debug(f"[EVENT-PARTY] У меня КД на {event_key} → не вступаю")
                return None

            # Гильдийский бонус (Сила+Здоровье) перед event-party боем —
            # без него пати в брутал/героик не вытягивает.
            # check_active возвращает True если бонус уже взят (1ч действия)
            # — лишних трат серебра нет.
            try:
                from requests_bot.survival_mines import ensure_guild_bonus
                ensure_guild_bonus(self.client)
            except Exception as e:
                log_warning(f"[EVENT-PARTY] Не удалось взять гильд-бонус: {e}")

            # Retry на случай "intermittent" сервера: если первая попытка
            # завершилась таймаутом (мембер не получил invite, сервер дропнул
            # push), пробуем ещё раз. Сервер иногда пушит, иногда нет —
            # 2-3 попытки увеличивают шанс.
            #
            # Между попытками делаем RELOGIN: WS-канал заблокирован 403 Fraud,
            # invite приходит только в HTML notice первых ~2 минут свежей сессии.
            # Без relogin retry бесполезен — pending уже висит на сервере и
            # новый push не отправляется.
            result = None
            for attempt in range(3):
                try:
                    result = run_event_party(self.client, self.dungeon_runner, dungeon_id, role)
                except Exception as e:
                    log_error(f"[EVENT-PARTY] Ошибка: {e}")
                    import traceback
                    traceback.print_exc()
                    return "error"
                if result in ("completed", "died"):
                    return result  # бой произошёл — выходим
                if result is None:
                    # Уже в пати / forming исчезла — не повторяем
                    return "member_waiting"
                # timeout / error — пробуем ещё раз через relogin
                if attempt < 2:
                    log_warning(
                        f"[EVENT-PARTY] Мембер: попытка {attempt + 1} → '{result}', "
                        f"делаю relogin для свежей сессии и retry"
                    )
                    try:
                        self.client.session.cookies.clear()
                        self.client._cached_soup = None
                        self.client._cached_soup_for = None
                        if not self.client.login():
                            log_warning("[EVENT-PARTY] Мембер: relogin упал — пауза 30с и retry со старой сессией")
                            import time as _t
                            _t.sleep(30)
                    except Exception as e:
                        log_warning(f"[EVENT-PARTY] Мембер: ошибка при relogin: {e} — пауза 30с")
                        import time as _t
                        _t.sleep(30)
            return result if result else "member_waiting"

        # === ЛИДЕР: полный путь с HTTP ===
        try:
            update_event_cooldowns(self.client)
        except Exception as e:
            log_warning(f"[EVENT-PARTY] Не удалось обновить КД с сервера: {e}")

        if is_dungeon_on_cooldown_for_profile(my_profile, event_key):
            log_debug(f"[EVENT-PARTY] У меня КД на {event_key} → обычная активность")
            return None

        # Удаляем призрачных мемберов (event_party_enabled=False),
        # чтобы не ждать тех кто отключил ивент-пати в UI.
        self._cleanup_event_cooldowns_inactive()

        # Гильдийский бонус перед event-party боем — см. коммент в ветке мембера.
        try:
            from requests_bot.survival_mines import ensure_guild_bonus
            ensure_guild_bonus(self.client)
        except Exception as e:
            log_warning(f"[EVENT-PARTY] Не удалось взять гильд-бонус: {e}")

        # Retry для лидера — см. коммент в ветке мембера.
        result = None
        for attempt in range(3):
            try:
                result = run_event_party(self.client, self.dungeon_runner, dungeon_id, role)
            except Exception as e:
                log_error(f"[EVENT-PARTY] Ошибка: {e}")
                import traceback
                traceback.print_exc()
                return "error"
            if result in ("completed", "died"):
                return result
            if result is None:
                # Нет мемберов / уже в пати / КД — не повторяем
                return None
            if result == "orphan_pending":
                # На мембере застрял pending от прошлого цикла, сервер дропает
                # новые invite. Retry бесполезен пока pending не expire (TTL
                # неизвестен, минимум 10 минут наблюдалось). Засыпаем длинно,
                # чтобы дать серверу шанс почистить очередь. В обычку
                # возвращаемся — пусть лидер крафтит/бегает данжи.
                import time as _t
                self._event_party_orphan_until = _t.time() + 1800  # 30 мин
                log_warning("[EVENT-PARTY] Лидер: orphan-pending у мембера, cooldown 30 мин")
                return "orphan_pending"
            # timeout / error — пробуем ещё раз
            if attempt < 2:
                # 90 сек пауза — см. коммент в ветке мембера
                log_warning(f"[EVENT-PARTY] Лидер: попытка {attempt + 1} → '{result}', retry через 90с")
                import time as _t
                _t.sleep(90)
        return result

    def check_party_dungeon(self):
        """Пробует пройти пати-данж (координация с другими ботами).

        Перебирает все данжи из PARTY_DUNGEONS, идёт в первый без КД.

        Returns:
            str or None: результат ("completed", "died", "timeout", "error") или None
        """
        if not is_party_dungeon_enabled():
            return None

        from requests_bot.party_dungeon import PARTY_DUNGEONS, is_on_cooldown, find_forming_party

        cfg = get_party_dungeon_config()
        difficulty = cfg["difficulty"]
        profile = get_profile_name()

        role = cfg.get("role", "member")
        configured_dungeon = cfg.get("dungeon_id")  # из конфига профиля

        # 1. Сначала проверяем — есть ли уже forming пати, к которой можно присоединиться
        forming = find_forming_party(profile)
        if forming:
            dungeon_id = forming["dungeon_id"]
            log_info(f"[PARTY] Найдена forming пати {forming['id']} для {dungeon_id}, присоединяюсь")
        elif role == "leader":
            # Лидер: сначала пробуем данж из конфига (раньше был баг — игнорировался,
            # лидер брал первый попавшийся из PARTY_DUNGEONS).
            target_members = cfg.get("members", 2)
            dungeon_id = None

            if configured_dungeon and configured_dungeon in PARTY_DUNGEONS:
                # Используем явно настроенный данж если на нём нет КД
                dcfg = PARTY_DUNGEONS[configured_dungeon]
                if dcfg.get("max_members", 5) >= target_members and not is_on_cooldown(profile, configured_dungeon):
                    dungeon_id = configured_dungeon
                    log_info(f"[PARTY] Лидер: иду в настроенный {dungeon_id}")
                else:
                    log_debug(f"[PARTY] Лидер: настроенный {configured_dungeon} на КД или размер не подходит — fallback")

            if not dungeon_id:
                # Fallback: первый доступный данж из словаря
                for did, dcfg in PARTY_DUNGEONS.items():
                    if dcfg.get("max_members", 5) < target_members:
                        continue
                    if not is_on_cooldown(profile, did):
                        dungeon_id = did
                        break
        else:
            # Мембер — только присоединяется, не создаёт
            dungeon_id = None

        if not dungeon_id:
            if role == "member":
                # КРИТИЧНО: мембер с включённой пати НЕ должен идти в обычные данжи
                # пока ждёт лидера — иначе уйдёт в данж и пропустит инвайт.
                # Возвращаем спец-значение чтобы run_dungeon_cycle мог пропустить
                # обычные данжи и просто подождать.
                log_debug("[PARTY] Мембер ждёт лидера, обычные данжи пропускаем")
                return "member_waiting"
            log_debug("[PARTY] Нет подходящей пати (все на КД)")
            return None

        log_info(f"[PARTY] Проверяю пати-данж {dungeon_id}...")

        try:
            # Если forming пати уже найдена — мембер. Иначе используем роль из конфига.
            effective_role = "member" if forming else role
            result = run_party_dungeon(
                self.client, self.dungeon_runner,
                dungeon_id=dungeon_id, difficulty=difficulty,
                role=effective_role,
            )
        except Exception as e:
            log_error(f"[PARTY] Ошибка: {e}")
            import traceback
            traceback.print_exc()
            return "error"

        if result is None:
            log_debug("[PARTY] Пропуск (КД или уже в пати)")
            return None

        if result == "completed":
            self.stats["dungeons_completed"] += 1
            mark_progress("dungeon")
            log_info(f"[PARTY] Данж пройден!")
            self.cleanup_backpack()
            self.check_and_collect_mail()
            self.check_craft()
        elif result == "died":
            self.stats["deaths"] += 1
            log_warning(f"[PARTY] Смерть в пати-данже")
            self.dungeon_runner.resurrect()
            self.check_and_resurrect_pet()
            try:
                if self.client.repair_equipment():
                    log_info("Снаряжение отремонтировано после смерти в пати-данже")
            except Exception:
                pass
            self.check_craft()
        elif result in ("timeout", "error"):
            log_warning(f"[PARTY] Результат: {result}")

        return result

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

    def _run_craft_only_cycle(self):
        """Цикл для craft-only ботов (например Пупупу — получатель золота).

        ТОЛЬКО крафт и продажа крафта. Никакой очистки рюкзака, почты,
        данжей, ивентов, арены, шахты. Рюкзак/рубины не трогаем — на них
        завязан трансфер золота через аукцион.
        """
        reset_watchdog()

        if not is_iron_craft_enabled():
            # Крафт не настроен — бот просто простаивает, ничего не делает
            set_activity("💤 Простой (только крафт)")
            log_debug("[CRAFT-ONLY] Крафт не включён — простаиваю")
            time.sleep(60)
            return True

        set_activity("🔨 Только крафт")
        wait = 30
        try:
            # do_craft_step → do_cyclic_craft_step сам и крафтит, и продаёт накопленное
            _crafting, craft_wait = self.do_craft_step()
            if craft_wait:
                wait = craft_wait
        except Exception as e:
            log_error(f"[CRAFT-ONLY] Ошибка крафта: {e}")
            self.stats["errors"] += 1

        # Ждём от 5 до 60 сек до следующего шага крафта
        time.sleep(max(5, min(wait, 60)))
        return True

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
        # Режим «только крафт» (Пупупу-получатель золота):
        # никаких данжей/рюкзака/почты/ивентов — только крафт и продажа крафта.
        # ============================================
        if is_craft_only_mode():
            return self._run_craft_only_cycle()

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

        # 1. Проверяем рюкзак и почту
        self.cleanup_backpack()
        self.check_and_collect_mail()

        # 2.1. Проверяем ежедневные награды и библиотеку (если включены)
        self.check_and_collect_daily_rewards()
        self.check_library()

        # 2.5. Проверяем крафт - используем единый метод
        self.check_craft()

        # 2.6. Ивент-данж Древний Лес (если включен)
        self.check_valentine_dungeons()

        # 2.7. Event-party (Пупупу+Полюби в ивент когда у обоих КД=0)
        event_party_result = self.check_event_party()
        if event_party_result == "member_waiting":
            log_debug("[EVENT-PARTY] Мембер: жду лидера, цикл закончил")
            return True
        if event_party_result == "completed":
            log_info("[EVENT-PARTY] Ивент-данж пройден в пати!")
            return True
        if event_party_result == "orphan_pending":
            # Cooldown уже выставлен в check_event_party. Дальше — обычка.
            log_info("[EVENT-PARTY] Orphan-pending, ушёл в обычные данжи на 30 мин")

        # 2.8. Обычная пати-данж (если включён)
        party_result = self.check_party_dungeon()
        if party_result == "member_waiting":
            # Мембер ждёт лидера — НЕ идём в обычные данжи (упустит инвайт).
            # Возврат True = run_dungeon_cycle отработал, основной цикл сделает sleep(5)
            # и через 5 сек попробует снова — за это время лидер мог создать пати.
            log_debug("[PARTY] Мембер: жду лидера, цикл закончил")
            return True

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
            # Все на КД - пробуем пати-данж ещё раз (мембер мог пропустить forming пати)
            party_result = self.check_party_dungeon()
            if party_result:
                return True  # Прошли пати-данж, вернуться в главный цикл

            # Все на КД - проверяем ивент-данж (может КД уже спал)
            valentine_done = self.check_valentine_dungeons()
            if valentine_done > 0:
                log_info(f"[EVENT] Пройдено {valentine_done} ивент-данженов во время КД")

            # Дэйли-караваны таверны (не чаще раза в 3ч, см. tavern_quests)
            try:
                from requests_bot.tavern_quests import run_tavern_caravans
                caravans_done = run_tavern_caravans(self.client, self.dungeon_runner)
                if caravans_done:
                    log_info(f"[TAVERN] Караваны: сделано {caravans_done} квестов во время КД")
            except Exception as e:
                log_warning(f"[TAVERN] Ошибка караванов: {e}")

            # Выбираем чем заняться
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
                # После Survival Mines проверяем крафт и ивент
                self.check_craft()
                self.check_valentine_dungeons()

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
                                result = fight_in_hell_games(self.client, min_cd_now, is_light_side=is_light_side(), profile=get_profile_name())
                                if not result:
                                    # Умерли и не смогли восстановиться в Hell Games
                                    log_info("Hell Games вернули False, воскрешаемся...")
                                    self.dungeon_runner.resurrect()
                                    self.check_and_resurrect_pet()
                                    if self.client.repair_equipment():
                                        log_info("Снаряжение отремонтировано после Hell Games")
                            except Exception as e:
                                log_error(f"Ошибка Hell Games: {e}")
                                self.stats["errors"] += 1
                            # После Hell Games проверяем крафт и ивент
                            self.check_craft()
                            self.check_valentine_dungeons()
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
                    result = fight_in_hell_games(self.client, min_cd, is_light_side=is_light_side(), profile=get_profile_name())
                    if not result:
                        # Умерли и не смогли восстановиться в Hell Games
                        log_info("Hell Games вернули False, воскрешаемся...")
                        self.dungeon_runner.resurrect()
                        self.check_and_resurrect_pet()
                        if self.client.repair_equipment():
                            log_info("Снаряжение отремонтировано после Hell Games")
                except Exception as e:
                    log_error(f"Ошибка Hell Games: {e}")
                    self.stats["errors"] += 1
                # После Hell Games проверяем крафт и ивент
                self.check_craft()
                self.check_valentine_dungeons()

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
                    new_diff, should_skip = record_death(
                        dungeon_id, dungeon_name, current_diff,
                        suspect=self.client.had_recent_net_error())
                    username = get_profile_username()
                    if should_skip:
                        log_warning(f"💀 [{username}] Умер в {dungeon_name} (normal) - данж скипается!")
                    else:
                        log_warning(f"💀 [{username}] Умер в {dungeon_name} ({current_diff} -> {new_diff})")
                    continue
                if enter_result == "locked_prerequisite":
                    # Игра требует пройти другой данж первым — скипаем навсегда.
                    # Реальный кейс: char13 не прошёл 'Путь к Барону', поэтому
                    # 'Владения Барона' всегда недоступен → бот зациклился.
                    detail = self.dungeon_runner.last_lock_detail
                    record_lock(dungeon_id, dungeon_name, reason="prerequisite", detail=detail)
                    log_warning(f"{dungeon_name}: заблокирован (нужно пройти {detail}) — скипаем")
                    continue
                if enter_result == "locked_level":
                    detail = self.dungeon_runner.last_lock_detail
                    record_lock(dungeon_id, dungeon_name, reason="level", detail=detail)
                    log_warning(f"{dungeon_name}: заблокирован (нужен {detail} ур.) — скипаем")
                    continue
                if not enter_result:
                    log_warning(f"Не удалось войти в {dungeon_name}")
                    continue

                # Бой (лимит определяется автоматически по типу данжена)
                result, actions = self.dungeon_runner.fight_until_done()
                self.stats["total_actions"] += actions

                if result == "completed":
                    self.stats["dungeons_completed"] += 1
                    mark_progress("dungeon")  # Отмечаем прогресс для авторестарта
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
                    new_diff, should_skip = record_death(
                        dungeon_id, dungeon_name, current_diff,
                        suspect=self.client.had_recent_net_error())

                    username = get_profile_username()
                    if should_skip:
                        log_warning(f"💀 [{username}] Умер в {dungeon_name} (normal) - данж скипается!")
                    else:
                        log_warning(f"💀 [{username}] Умер в {dungeon_name} ({current_diff} -> {new_diff})")

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

                    # Проверяем - может сервер на обновлении?
                    if self.client.is_server_updating():
                        log_info("Watchdog сработал во время обновления сервера - ждём...")
                        if self.client.wait_for_server(max_wait_minutes=10):
                            log_info("Сервер доступен, продолжаем...")
                            reset_watchdog()
                            continue  # Продолжаем цикл данженов
                    else:
                        # Уведомление в Telegram о застревании
                        username = get_profile_username()
                        telegram_notify(f"⚠️ [{username}] Watchdog: застрял в {dungeon_name}")

                    # Пробуем вернуться в данжены
                    self.client.get("/dungeons?52")
                    reset_watchdog()

                else:
                    log_warning(f"Неизвестный результат: {result}")
                    log_dungeon_result(dungeon_name, result, actions)

                    # Проверяем - может персонаж умер но не задетектили?
                    if self.client.is_dead():
                        log_warning(f"После unknown обнаружен на кладбище - это была смерть!")
                        self.stats["deaths"] += 1

                        # Записываем смерть в файловую статистику
                        if self.bot_stats:
                            self.bot_stats.death_recorded(dungeon_id)

                        # Записываем в deaths.json для системы сложности
                        current_difficulty = get_dungeon_difficulty(dungeon_id)
                        new_difficulty, should_skip = record_death(
                            dungeon_id, dungeon_name, current_difficulty,
                            suspect=self.client.had_recent_net_error())
                        if should_skip:
                            log_warning(f"Данжен {dungeon_name} добавлен в скип (много смертей)")
                        else:
                            log_info(f"Сложность {dungeon_name}: {current_difficulty} -> {new_difficulty}")

                        username = get_profile_username()
                        log_warning(f"💀 [{username}] Умер в {dungeon_name} (unknown->died)")

                        # Воскрешаемся
                        self.dungeon_runner.resurrect()
                        try:
                            if self.client.repair_equipment():
                                log_info("Снаряжение отремонтировано после смерти")
                        except Exception as e:
                            log_debug(f"Ошибка ремонта после смерти: {e}")
                    else:
                        # Пробуем вернуться в данжены
                        self.client.get("/dungeons?52")

            except Exception as e:
                log_error(f"Ошибка в данжене {dungeon_name}: {e}")
                log_debug(tb_module.format_exc())
                self.stats["errors"] += 1
                # Пробуем восстановиться
                try:
                    self.client.get("/dungeons?52")
                except Exception:
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

        # Ресурсы уже инициализированы в login() -> _init_resources_session()

        # Сбрасываем трекинг прогресса для авторестарта
        reset_progress_tracking()

        # Арена - только в начале сессии, один раз
        self.try_arena()

        cycle = 0
        try:
            while True:
                # Ночной режим: 00:00-08:00 МСК — спим
                now_msk = datetime.now(MSK)
                if NIGHT_START <= now_msk.hour < NIGHT_END:
                    if is_wake_for_event_party_at_night() and is_valentine_event_enabled():
                        # Особый режим: спим, но просыпаемся для соло-ивента
                        # (Затерянный храм) когда КД=0. Раньше тут была пати —
                        # её больше нет, но флаг wake_for_event_party_at_night
                        # переиспользуем (чтобы не менять конфиги профилей).
                        # Никаких обычных данжей/крафта/арены ночью.
                        self._sleep_with_event_party_wakeup()
                    else:
                        # Обычный ночной режим: глухой sleep до 08:00
                        wake_up = now_msk.replace(hour=NIGHT_END, minute=0, second=0, microsecond=0)
                        sleep_seconds = int((wake_up - now_msk).total_seconds())
                        log_info(f"🌙 Ночной режим: сплю до 08:00 МСК ({sleep_seconds // 3600}ч {(sleep_seconds % 3600) // 60}м)")
                        set_activity("🌙 Сон до 08:00")
                        time.sleep(sleep_seconds)
                        log_info("☀️ Просыпаюсь!")
                        set_activity("☀️ Просыпаюсь")

                cycle += 1
                log_cycle_start(cycle)

                # Проверяем авторизацию в начале каждого цикла
                # При ConnectionError — ждём и ретраим (сервер может быть временно недоступен)
                try:
                    logged_in = self.client.ensure_logged_in()
                except (RequestsConnectionError, OSError) as conn_err:
                    logged_in = False
                    log_warning(f"Сервер недоступен: {conn_err.__class__.__name__}")
                    # Ждём с нарастающей задержкой: 30с, 60с, 120с, 120с...
                    max_conn_retries = 10
                    for attempt in range(1, max_conn_retries + 1):
                        delay = min(30 * (2 ** (attempt - 1)), 120)
                        log_info(f"Жду {delay}с перед попыткой {attempt}/{max_conn_retries}...")
                        time.sleep(delay)
                        try:
                            logged_in = self.client.ensure_logged_in()
                            if logged_in:
                                log_info(f"Сервер снова доступен! Продолжаю работу.")
                                break
                        except (RequestsConnectionError, OSError):
                            log_warning(f"Попытка {attempt}/{max_conn_retries} — сервер всё ещё недоступен")
                            continue
                if not logged_in:
                    log_error("Не удалось восстановить сессию, выход")
                    break

                # Проверяем не умер ли персонаж (на кладбище)
                if self.client.is_dead():
                    log_warning("Персонаж на кладбище! Ухожу...")
                    self.stats["deaths"] += 1
                    log_warning(f"💀 [{get_profile_username()}] Умер в данже")
                    if not self.client.leave_graveyard():
                        log_error("Не удалось уйти с кладбища!")
                        time.sleep(60)
                        continue

                try:
                    if not self.run_dungeon_cycle():
                        break
                except (RequestsConnectionError, OSError) as conn_err:
                    # Сервер упал во время цикла — ждём, не считаем критической ошибкой
                    log_warning(f"Потеря связи в цикле {cycle}: {conn_err.__class__.__name__}")
                    time.sleep(60)
                    continue
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
                    except Exception:
                        pass

                # Проверяем авторестарт (20 мин без прогресса)
                if check_auto_recovery():
                    username = get_profile_username()
                    telegram_notify(f"🔄 [{username}] Авторестарт: нет прогресса 20+ мин")
                    raise AutoRestartException("Нет прогресса 20+ мин")

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
        except Exception:
            pass
    atexit.register(cleanup)

    max_restarts = 10
    restart_count = 0

    while restart_count <= max_restarts:
        bot = VMMOBot()
        try:
            if args.test:
                bot.run(max_cycles=1)
            else:
                bot.run(max_cycles=args.cycles)
            break  # Нормальный выход
        except KeyboardInterrupt:
            log_info("Бот остановлен пользователем (Ctrl+C)")
            break
        except AutoRestartException as e:
            restart_count += 1
            log_info(f"[AUTO-RESTART] {e} — перезапуск #{restart_count}/{max_restarts}")
            time.sleep(5)
            continue
        except Exception as e:
            # Глобальный обработчик - ловит ВСЕ необработанные ошибки
            restart_count += 1
            log_error(f"FATAL ERROR: {e}")
            log_error(tb_module.format_exc())
            if restart_count <= max_restarts:
                log_info(f"[AUTO-RESTART] Перезапуск после ошибки #{restart_count}/{max_restarts}")
                time.sleep(10)
                continue
            else:
                log_error(f"Достигнут лимит рестартов ({max_restarts}), выход")
                break


if __name__ == "__main__":
    main()
