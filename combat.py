# ============================================
# VMMO Bot - Combat Functions
# ============================================

import time
import random
from config import (
    UNIT_SELECTORS,
    ATTACK_SELECTOR,
    DUNGEONS_URL,
    HELL_GAMES_URL,
    HELL_GAMES_SKIP_SKILLS,
)
from utils import antibot_delay, log, safe_click, safe_click_element
from backpack import cleanup_backpack_if_needed
from stats import get_stats


def units_present(page):
    """Проверяет наличие юнитов на поле боя"""
    for sel in UNIT_SELECTORS:
        if page.query_selector(sel):
            return True
    return False


def use_skills(page):
    """
    Использует один доступный скилл за вызов.
    После использования скилла ждёт 2 секунды (КД скиллов).
    Возвращает True если скилл был использован.
    """
    for pos in range(1, 6):
        wrapper_selector = f".wrap-skill-link._skill-pos-{pos}"
        try:
            wrapper = page.query_selector(wrapper_selector)
            if not wrapper:
                continue

            # Проверяем таймер скилла - если есть время (не пустой и не 00:00), скилл на КД
            timer = wrapper.query_selector(".time-counter")
            if timer:
                timer_text = timer.inner_text().strip()
                # Скилл на КД если таймер показывает время (не пустой и не 00:00)
                if timer_text and timer_text != "00:00":
                    continue

            # Скилл готов — используем
            skill_link = wrapper.query_selector("a.skill-link")
            if skill_link:
                try:
                    skill_link.dispatch_event("click")
                    log(f"⚡ Использован скилл _skill-pos-{pos}")
                    antibot_delay(1.8, 0.4)
                    return True
                except:
                    pass

        except Exception as e:
            pass  # Не спамим ошибками

    return False


def use_skills_hell(page):
    """
    Использует скиллы в Адских Играх (пропускает Талисман Доблести).
    """
    for pos in range(1, 6):
        # Пропускаем скиллы из списка исключений
        if pos in HELL_GAMES_SKIP_SKILLS:
            continue

        wrapper_selector = f".wrap-skill-link._skill-pos-{pos}"
        try:
            wrapper = page.query_selector(wrapper_selector)
            if not wrapper:
                continue

            timer = wrapper.query_selector(".time-counter")
            if timer:
                timer_text = timer.inner_text().strip()
                if timer_text and timer_text != "00:00":
                    continue

            skill_link = wrapper.query_selector("a.skill-link")
            if skill_link:
                try:
                    skill_link.dispatch_event("click")
                    log(f"⚡ Использован скилл _skill-pos-{pos}")
                    antibot_delay(1.8, 0.4)
                    return True
                except:
                    pass

        except Exception as e:
            pass

    return False


def check_dungeon_status(page):
    """
    Проверяет статус подземелья:
    - "Этап подземелья ... пройден!" → возвращает "stage_complete"
    - "Подземелье ... пройдено!" или "Подземелье зачищено!" → возвращает "dungeon_complete"
    - Иначе → возвращает None
    """
    try:
        # Проверяем URL на DungeonCompletedPage (страница завершения данжена)
        current_url = page.url.lower()
        if "dungeoncompleted" in current_url:
            log("🏆 Подземелье зачищено!")
            return "dungeon_complete"

        elements = page.query_selector_all("h2, h2 span")
        for el in elements:
            text = el.inner_text().strip()
            text_lower = text.lower()

            if "пройден" in text_lower or "зачищен" in text_lower:
                if "этап" in text_lower:
                    log(f"✅ {text}")
                    return "stage_complete"
                elif "подземелье" in text_lower:
                    log(f"🏆 {text}")
                    return "dungeon_complete"
    except Exception as e:
        print(f"❌ Ошибка при проверке статуса: {e}")
    return None


def click_continue_battle(page):
    """Нажимает кнопку 'Продолжить бой'"""
    try:
        buttons = page.query_selector_all("span.go-btn-in")
        for btn in buttons:
            text = btn.inner_text().strip()
            if "Продолжить бой" in text:
                log("🔄 Нажимаем 'Продолжить бой'")
                safe_click_element(btn)
                antibot_delay(1.5, 1.0)
                return True
    except Exception as e:
        print(f"❌ Ошибка при нажатии 'Продолжить бой': {e}")
    return False


def handle_stuck(page):
    """
    Вызывается когда бот застрял (много попыток без юнитов).
    Пытается найти кнопку "Продолжить" или "Продолжить бой".
    Возвращает:
        "continue" - если нашли и нажали кнопку продолжения
        "next_dungeon" - если нужно переходить к следующему данжену
    """
    log("🔄 Застряли! Ищем способ продолжить...")

    try:
        buttons = page.query_selector_all("span.go-btn-in")
        for btn in buttons:
            text = btn.inner_text().strip()
            if "Продолжить" in text:
                log(f"✅ Нашли кнопку '{text}' — нажимаем")
                safe_click_element(btn)
                antibot_delay(2.0, 1.0)
                return "continue"
    except Exception as e:
        print(f"⚠️ Ошибка при поиске кнопки продолжения: {e}")

    log("⏭️ Кнопка не найдена — переходим к следующему данжену")
    return "next_dungeon"


def check_death(page, dungeon_name=None):
    """
    Проверяет, умер ли персонаж.
    Если да — нажимает 'Покинуть бой' → 'Покинуть банду' → возвращается в подземелья.
    Возвращает True если персонаж погиб.

    dungeon_name: опциональное название данжена для логирования
    """
    try:
        fail_modal = page.query_selector("div.battlefield-modal._fail")
        if fail_modal:
            if dungeon_name:
                log(f"💀 Персонаж погиб в данжене: {dungeon_name}")
            else:
                log("💀 Персонаж погиб!")

            # 1) Нажимаем "Покинуть бой"
            leave_btn = fail_modal.query_selector("span.button-text")
            if leave_btn:
                safe_click_element(leave_btn)
                log("🚪 Нажали 'Покинуть бой'")
                antibot_delay(2.0, 1.5)

            # 2) Нажимаем "Покинуть банду"
            try:
                buttons = page.query_selector_all("span.go-btn-in")
                for btn in buttons:
                    text = btn.inner_text().strip()
                    if "Покинуть банду" in text:
                        safe_click_element(btn)
                        log("👋 Нажали 'Покинуть банду'")
                        antibot_delay(2.0, 1.5)
                        break
            except Exception as e:
                print(f"⚠️ Не удалось нажать 'Покинуть банду': {e}")

            # 3) Переходим в подземелья
            try:
                page.goto(DUNGEONS_URL)
                log("🏰 Вернулись в список подземелий")
                antibot_delay(2.0, 1.5)
            except Exception as e:
                print(f"⚠️ Не удалось перейти в подземелья: {e}")

            return True
    except Exception as e:
        print(f"❌ Ошибка при проверке смерти: {e}")
    return False


def has_enemies_hell(page):
    """
    Проверяет наличие врагов в Адских Играх.
    Враги на позициях 21-25.
    """
    try:
        for pos in range(21, 26):
            enemy = page.query_selector(f"div.unit._unit-pos-{pos}")
            if enemy:
                return True
        return False
    except:
        return False


def find_random_source(page):
    """
    Ищет рандомный доступный источник (не текущий и не заблокированный).
    Возвращает элемент или None.
    """
    try:
        sources = page.query_selector_all("a.source-link")
        available = []
        for source in sources:
            classes = source.get_attribute("class") or ""
            # Пропускаем текущий и заблокированный
            if "_current" in classes or "_lock" in classes:
                continue
            available.append(source)

        if available:
            return random.choice(available)
    except:
        pass
    return None


def has_keeper_enemy(page):
    """
    Проверяет наличие вражеского хранителя на позиции 22.
    """
    try:
        keeper = page.query_selector("div.unit._unit-pos-22 div.unit-show._keeper")
        return keeper is not None
    except:
        return False


def click_keeper(page):
    """
    Кликает на хранителя (позиция 22) чтобы выбрать его как цель.
    """
    try:
        keeper_link = page.query_selector("div.unit._unit-pos-22 a.unit-link")
        if keeper_link:
            keeper_link.dispatch_event("click")
            log("🎯 Выбрали хранителя как цель")
            antibot_delay(0.5, 0.3)
            return True
    except Exception as e:
        print(f"⚠️ Ошибка при клике на хранителя: {e}")
    return False


def find_light_source(page):
    """
    Ищет вражеский источник (side-light = враг, не текущий, не заблокированный).
    Возвращает элемент или None.
    """
    try:
        sources = page.query_selector_all("a.source-link")
        for source in sources:
            classes = source.get_attribute("class") or ""
            if "_side-light" in classes and "_current" not in classes and "_lock" not in classes:
                return source
    except:
        pass
    return None


def all_sources_dark(page):
    """
    Проверяет, все ли источники наши (side-dark).
    Возвращает True если все источники dark (наши).
    """
    try:
        sources = page.query_selector_all("a.source-link")
        for source in sources:
            classes = source.get_attribute("class") or ""
            if "_side-light" in classes:
                return False
        return True
    except:
        return False


def fight_in_hell_games(page, duration_seconds):
    """
    Переходит в Адские Игры и сражается указанное время (в секундах).

    Логика:
    1. Ищем light источник (вражеский) → переходим
    2. Кликаем на хранителя (pos-22) → бьём со скиллами
    3. Когда хранитель убит → ищем следующий light
    4. Когда все dark (наши) → ждём без скиллов пока появится light
    5. Появился light → переходим и убиваем
    """
    log(f"🔥 Идём в Адские Игры на {duration_seconds // 60} мин {duration_seconds % 60} сек")

    try:
        page.goto(HELL_GAMES_URL)
        time.sleep(3)
        antibot_delay(1.0, 1.0)
    except Exception as e:
        print(f"❌ Не удалось перейти в Адские Игры: {e}")
        return

    if "login" in page.url:
        print("❌ Куки не сработали — логин")
        return

    log("⚔️ Начинаем бой в Адских Играх!")

    end_time = time.time() + duration_seconds
    last_log_minute = -1
    keeper_selected = False  # Флаг: выбран ли хранитель как цель

    while time.time() < end_time:
        try:
            remaining = int(end_time - time.time())
            current_minute = remaining // 60
            if current_minute != last_log_minute and remaining > 0:
                log(f"⏱️ Осталось {current_minute} мин")
                last_log_minute = current_minute

            # Проверяем есть ли вражеский хранитель на pos-22
            if has_keeper_enemy(page):
                # Хранитель есть — выбираем его и бьём
                if not keeper_selected:
                    click_keeper(page)
                    keeper_selected = True

                # Используем скиллы (без Талисмана Доблести) и атакуем
                use_skills_hell(page)
                safe_click(page, ATTACK_SELECTOR, timeout=2000)
                antibot_delay(1.5, 0.5)
            else:
                # Хранителя нет — убит или мы в пустом источнике
                keeper_selected = False

                # Ищем вражеский источник (light)
                light_source = find_light_source(page)
                if light_source:
                    log("🌍 Переходим в вражеский источник (light)...")
                    light_source.dispatch_event("click")
                    time.sleep(3)
                    antibot_delay(1.0, 1.0)
                elif all_sources_dark(page):
                    # Все источники наши — атакуем без скиллов, ждём врага
                    safe_click(page, ATTACK_SELECTOR, timeout=2000)
                    antibot_delay(3.0, 1.0)
                else:
                    # Есть light, но заблокирован — ждём
                    time.sleep(3)
                    antibot_delay(1.0, 1.0)

        except Exception as e:
            print(f"Ошибка в бою Адских Игр: {e}")
            antibot_delay(2, 2)

    log("⏰ Время вышло! Возвращаемся в подземелья...")

    # Записываем время в Адских Играх
    get_stats().hell_games_time(duration_seconds)

    try:
        page.goto(DUNGEONS_URL)
        time.sleep(3)
        antibot_delay(1.0, 1.0)
        log("🏰 Вернулись в список подземелий")
    except Exception as e:
        print(f"❌ Не удалось вернуться в подземелья: {e}")

    cleanup_backpack_if_needed(page)
