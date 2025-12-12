# ============================================
# VMMO Bot - Dungeon Management
# ============================================

import time
from config import (
    DUNGEONS_BUTTON_SELECTOR,
    DUNGEONS_URL,
    MAX_ENTER_FAILURES,
)
from dungeon_config import DUNGEON_ORDER, DUNGEONS, DIFFICULTY_SELECTOR
from utils import antibot_delay, log, parse_cooldown_time, safe_click, safe_click_element
from popups import close_all_popups
from backpack import cleanup_backpack_if_needed, repeat_craft_if_ready
from combat import fight_in_hell_games


# Счётчик попыток нажать "В подземелье!" для предотвращения бесконечного цикла
_widget_enter_attempts = 0
MAX_WIDGET_ENTER_ATTEMPTS = 3  # Максимум 3 попытки войти через виджет


def reset_widget_attempts():
    """Сбрасывает счётчик попыток виджета (вызывать после успешного входа в данжен)"""
    global _widget_enter_attempts
    _widget_enter_attempts = 0


def clear_blocking_widget(page):
    """
    Если есть виджет с "В подземелье" — разбираемся с ним.
    Виджет блокирует клики на данжены!

    Логика:
    1. Пробуем "В подземелье!" → если вход успешен (есть "Начать бой") — ок
    2. Если вход закрыт — покидаем банду
    3. После MAX_WIDGET_ENTER_ATTEMPTS неудачных попыток — принудительно покидаем банду

    Возвращает True если виджет убран или его не было.
    """
    global _widget_enter_attempts

    try:
        widget = page.query_selector("div.widget")
        if not widget:
            return True  # Нет виджета — всё ок

        # Проверяем есть ли кнопка "В подземелье"
        widget_text = widget.inner_text()
        if "В подземелье" not in widget_text:
            return True  # Виджет не про данжен

        log("🔔 Обнаружен виджет 'В подземелье' — пробуем войти...")

        # Ищем кнопку "В подземелье!" в виджете
        buttons = widget.query_selector_all("a.go-btn")
        enter_btn = None
        leave_btn = None

        for btn in buttons:
            btn_text = btn.inner_text().strip()
            if "В подземелье" in btn_text:
                enter_btn = btn
            elif "Покинуть банду" in btn_text:
                leave_btn = btn

        # Проверяем лимит попыток
        if _widget_enter_attempts >= MAX_WIDGET_ENTER_ATTEMPTS:
            log(f"🚫 Достигнут лимит попыток ({MAX_WIDGET_ENTER_ATTEMPTS}) — принудительно покидаем банду")
            _widget_enter_attempts = 0  # Сбрасываем счётчик

            # Ищем кнопку "Покинуть банду" и нажимаем
            leave_buttons = page.query_selector_all("a.go-btn")
            for btn in leave_buttons:
                if "Покинуть банду" in btn.inner_text():
                    btn.dispatch_event("click")
                    log("👋 Покинули банду (лимит попыток)")
                    time.sleep(2)
                    antibot_delay(1.0, 1.0)
                    # После выхода из банды — возвращаемся в подземелья
                    page.goto(DUNGEONS_URL)
                    time.sleep(4)
                    antibot_delay(1.0, 1.0)
                    return True

            # Если кнопки нет — принудительный переход
            page.goto(DUNGEONS_URL)
            time.sleep(4)
            antibot_delay(1.0, 1.0)
            return True

        if enter_btn:
            _widget_enter_attempts += 1
            log(f"🔄 Попытка входа через виджет {_widget_enter_attempts}/{MAX_WIDGET_ENTER_ATTEMPTS}")

            # Пробуем войти
            enter_btn.dispatch_event("click")
            log("✅ Нажали 'В подземелье!'")
            time.sleep(3)
            antibot_delay(1.0, 1.0)

            # Проверяем — получилось войти? (есть кнопка "Начать бой!")
            try:
                start_btn = page.wait_for_selector("span.go-btn-in._font-art", timeout=5000)
                if start_btn:
                    # Проверяем текст и НАЖИМАЕМ "Начать бой!"
                    all_btns = page.query_selector_all("a.go-btn")
                    for btn in all_btns:
                        if "Начать бой" in btn.inner_text():
                            btn.dispatch_event("click")
                            log("⚔️ Нажали 'Начать бой!' (из виджета)")
                            antibot_delay(3.0, 1.5)
                            _widget_enter_attempts = 0  # Успех — сбрасываем счётчик
                            return "started_battle"  # Специальное значение — бой начат
            except:
                pass

            # Вход не удался (нет "Начать бой") — покидаем банду
            log("⚠️ Вход закрыт — покидаем банду...")

            # Ищем кнопку "Покинуть банду" на текущей странице
            leave_buttons = page.query_selector_all("a.go-btn")
            for btn in leave_buttons:
                if "Покинуть банду" in btn.inner_text():
                    btn.dispatch_event("click")
                    log("👋 Покинули банду")
                    time.sleep(2)
                    antibot_delay(1.0, 1.0)
                    _widget_enter_attempts = 0  # Сбрасываем счётчик после выхода
                    # После выхода из банды — возвращаемся в подземелья
                    log("🏰 Возвращаемся в подземелья...")
                    page.goto(DUNGEONS_URL)
                    time.sleep(4)
                    antibot_delay(1.0, 1.0)
                    return True

            # Если кнопки нет — переходим на /dungeons
            log("🔄 Принудительный выход из банды...")
            _widget_enter_attempts = 0  # Сбрасываем счётчик после выхода
            page.goto(DUNGEONS_URL)
            time.sleep(4)
            antibot_delay(1.0, 1.0)
            return True

        elif leave_btn:
            # Только кнопка "Покинуть банду" — нажимаем
            leave_btn.dispatch_event("click")
            log("👋 Покинули банду (виджет)")
            time.sleep(2)
            antibot_delay(1.0, 1.0)
            _widget_enter_attempts = 0  # Сбрасываем счётчик
            # После выхода из банды — возвращаемся в подземелья
            log("🏰 Возвращаемся в подземелья...")
            page.goto(DUNGEONS_URL)
            time.sleep(4)
            antibot_delay(1.0, 1.0)
            return True

    except Exception as e:
        log(f"⚠️ Ошибка при обработке виджета: {e}")

    return True


def force_refresh(page):
    """
    Принудительно обновляет страницу и возвращается в подземелья.
    Используется когда клики не работают.
    """
    log("🔄 Принудительное обновление страницы...")
    try:
        page.goto(DUNGEONS_URL)
        time.sleep(5)
        antibot_delay(1.0, 1.0)
        log("✅ Страница обновлена")
        return True
    except Exception as e:
        print(f"❌ Ошибка при обновлении: {e}")
        return False


def check_dungeon_cooldown(page, dungeon_id):
    """
    Проверяет, есть ли кулдаун у данжена.
    Возвращает (on_cooldown: bool, cd_time: str)
    """
    try:
        selector = f'div[title="{dungeon_id}"]'
        dungeon_div = page.query_selector(selector)

        if not dungeon_div:
            print(f"⚠️ DEBUG: Не найден div для {dungeon_id}")
            return True, "не найден"

        cooldown_icon = dungeon_div.query_selector("[class*='dungeon-cooldown']")

        if cooldown_icon:
            cooldown_name = dungeon_div.query_selector("span.map-item-name")
            if cooldown_name:
                cd_text = cooldown_name.inner_text().strip()
                if cd_text:
                    return True, cd_text
            return True, "КД"

        return False, None
    except Exception as e:
        print(f"❌ Ошибка при проверке КД: {e}")
        return True, "ошибка"


def find_next_available_dungeon(page, current_index):
    """
    Ищет следующий данжен без кулдауна.
    Возвращает индекс доступного данжена, "started_battle" если бой начат, или None если все на КД.
    """
    # Сначала убираем блокирующий виджет (если есть)
    widget_result = clear_blocking_widget(page)
    if widget_result == "started_battle":
        # Бой уже начат через виджет — не ищем данжены
        return "started_battle"

    checked = 0
    next_index = current_index

    while checked < len(DUNGEON_ORDER):
        next_index = (next_index + 1) % len(DUNGEON_ORDER)
        dungeon_id = DUNGEON_ORDER[next_index]
        dungeon_name = DUNGEONS.get(dungeon_id, {}).get("name", dungeon_id)

        on_cooldown, cd_time = check_dungeon_cooldown(page, dungeon_id)

        if on_cooldown:
            log(f"⏳ {dungeon_name} на КД: {cd_time}")
        else:
            log(f"✅ {dungeon_name} доступен!")
            return next_index

        checked += 1

    log("❌ Все данжены на кулдауне!")
    return None


def get_min_cooldown_time(page):
    """
    Проверяет все данжены и возвращает минимальное время КД в секундах.
    Возвращает (секунды, название_данжена) или (None, None)
    """
    min_seconds = None
    min_dungeon = None

    for dungeon_id in DUNGEON_ORDER:
        dungeon_name = DUNGEONS.get(dungeon_id, {}).get("name", dungeon_id)
        on_cooldown, cd_time = check_dungeon_cooldown(page, dungeon_id)

        if on_cooldown and cd_time and cd_time not in ["не найден", "ошибка", "КД"]:
            seconds = parse_cooldown_time(cd_time)
            if seconds and (min_seconds is None or seconds < min_seconds):
                min_seconds = seconds
                min_dungeon = dungeon_name

    return min_seconds, min_dungeon


def enter_dungeon(page, dungeon_id):
    """Вход в данжен"""
    from navigation import detect_location

    dungeon_config = DUNGEONS.get(dungeon_id)
    if not dungeon_config:
        print(f"❌ Неизвестный данжен: {dungeon_id}")
        return False

    close_all_popups(page)

    # Проверяем блокирующий виджет "В подземелье" от предыдущей группы
    clear_blocking_widget(page)

    # Проверяем, не на лендинге ли мы уже (после "В подземелье")
    location = detect_location(page)
    if location == "dungeon_landing":
        log("📋 Уже на лендинге данжена — входим")

        # Сначала проверяем, есть ли сразу "Начать бой!" (банда уже готова)
        try:
            buttons = page.query_selector_all("a.go-btn")
            for btn in buttons:
                text = btn.inner_text().strip()
                if "Начать бой" in text:
                    btn.dispatch_event("click")
                    log("⚔️ Начали бой!")
                    antibot_delay(2.0, 1.5)
                    return True
        except:
            pass

        # Если нет "Начать бой", пробуем нажать "Войти"
        enter_clicked = False
        try:
            buttons = page.query_selector_all("a.go-btn")
            for btn in buttons:
                text = btn.inner_text().strip()
                if text == "Войти":
                    btn.dispatch_event("click")
                    enter_clicked = True
                    log("✅ Нажали 'Войти'")
                    break
        except:
            pass

        if enter_clicked:
            time.sleep(3)
            antibot_delay(1.0, 1.5)

            # После "Войти" должна появиться кнопка "Начать бой!"
            try:
                page.wait_for_selector("span.go-btn-in._font-art", timeout=15000)
                buttons = page.query_selector_all("a.go-btn")
                for btn in buttons:
                    text = btn.inner_text().strip()
                    if "Начать бой" in text:
                        btn.dispatch_event("click")
                        log("⚔️ Начали бой!")
                        antibot_delay(2.0, 1.5)
                        return True
            except:
                pass
            print(f"❌ Не удалось нажать 'Начать бой!' после 'Войти'")
            return False
        else:
            print(f"❌ Не удалось найти кнопку на лендинге")
            return False

    log(f"🏰 Начинаем вход в данжен: {dungeon_config['name']}")

    # 1) Кликаем на данжен
    try:
        selector = f'div[title="{dungeon_id}"]'
        if not safe_click(page, selector, timeout=10000):
            print(f"❌ Не удалось кликнуть на данжен")
            return False
        log("✅ Кликнули на данжен")
        time.sleep(2)
        antibot_delay(1.0, 1.0)
    except Exception as e:
        print(f"❌ Не удалось кликнуть на данжен: {e}")
        return False

    # 2) Ждём загрузки попапа данжена
    popup_loaded = False
    try:
        page.wait_for_selector("a.go-btn", timeout=10000)
        time.sleep(1)
        popup_loaded = True
    except:
        log("⚠️ Попап данжена не загрузился")
        # Дебаг: куда нас перенаправило?
        log(f"🔗 URL после клика: {page.url}")
        # Проверяем, не на лендинге ли мы уже
        location = detect_location(page)
        log(f"📍 Локация: {location}")
        if location == "dungeon_landing":
            log("📋 Мы уже на лендинге данжена!")
            # Ищем кнопки "Войти" или "Начать бой"
            try:
                buttons = page.query_selector_all("a.go-btn")
                for btn in buttons:
                    text = btn.inner_text().strip()
                    if "Начать бой" in text:
                        btn.dispatch_event("click")
                        log("⚔️ Начали бой! (с лендинга)")
                        antibot_delay(2.0, 1.5)
                        return True
                    elif text == "Войти":
                        btn.dispatch_event("click")
                        log("✅ Нажали 'Войти' (с лендинга)")
                        popup_loaded = True
                        time.sleep(3)
                        break
            except Exception as e:
                log(f"⚠️ Ошибка на лендинге: {e}")

    # 3) Повышаем сложность (если нужно)
    if dungeon_config.get("need_difficulty"):
        if safe_click(page, DIFFICULTY_SELECTOR, timeout=5000):
            log("⬆️ Повысили сложность")
            time.sleep(1)
            antibot_delay(0.5, 0.5)
        else:
            print(f"⚠️ Не удалось повысить сложность")

    # 4) Кликаем "Войти" - ищем кнопку по тексту
    enter_clicked = False
    try:
        buttons = page.query_selector_all("a.go-btn")
        # Дебаг: показываем какие кнопки есть
        btn_texts = [btn.inner_text().strip() for btn in buttons]
        log(f"🔍 Найдены кнопки: {btn_texts}")

        for btn in buttons:
            text = btn.inner_text().strip()
            if text == "Войти":
                btn.dispatch_event("click")
                enter_clicked = True
                log("✅ Нажали 'Войти'")
                break
            # Иногда кнопка называется "В подземелье"
            elif "подземелье" in text.lower():
                btn.dispatch_event("click")
                enter_clicked = True
                log(f"✅ Нажали '{text}'")
                break
    except Exception as e:
        print(f"⚠️ Ошибка при поиске кнопки 'Войти': {e}")

    if not enter_clicked:
        # Делаем скриншот для дебага
        from utils import save_debug_screenshot
        save_debug_screenshot(page, "no_enter_button")
        print(f"❌ Не удалось нажать 'Войти'")
        return False

    # Ждём перехода на лобби
    time.sleep(3)
    antibot_delay(1.0, 1.5)

    # 4) Кликаем "Начать бой!" - ищем по тексту
    start_clicked = False
    try:
        # Ждём появления кнопки на странице лобби
        page.wait_for_selector("span.go-btn-in._font-art", timeout=15000)

        buttons = page.query_selector_all("a.go-btn")
        for btn in buttons:
            text = btn.inner_text().strip()
            if "Начать бой" in text:
                btn.dispatch_event("click")
                start_clicked = True
                log("⚔️ Начали бой!")
                break
    except Exception as e:
        print(f"⚠️ Ошибка при поиске кнопки 'Начать бой!': {e}")

    if not start_clicked:
        print(f"❌ Не удалось нажать 'Начать бой!'")
        return False

    antibot_delay(4.0, 1.5)

    # Успешный вход — сбрасываем счётчик попыток виджета
    reset_widget_attempts()

    return True


def go_to_next_dungeon(page, current_index, enter_failure_count=0):
    """
    Возвращается в список данженов и открывает следующий доступный.
    Возвращает (new_index, enter_failure_count)
    """
    close_all_popups(page)

    # Если много неудачных попыток — принудительное обновление
    if enter_failure_count >= MAX_ENTER_FAILURES:
        log(f"⚠️ {enter_failure_count} неудачных попыток — принудительное обновление")
        force_refresh(page)
        enter_failure_count = 0

    # 0) Проверяем, не на странице ли завершения данжена (DungeonCompletedPage)
    # Там нужно сначала нажать "Продолжить"
    current_url = page.url.lower()
    if "dungeoncompleted" in current_url:
        log("📋 Страница завершения данжена — нажимаем 'Продолжить'")
        # Ищем кнопку "Продолжить" (не "Продолжить бой")
        buttons = page.query_selector_all("a.go-btn")
        for btn in buttons:
            text = btn.inner_text().strip()
            if text == "Продолжить":
                btn.dispatch_event("click")
                log("✅ Нажали 'Продолжить'")
                time.sleep(3)
                antibot_delay(1.0, 1.0)
                break

    # 1) Возвращаемся в список подземелий
    if safe_click(page, DUNGEONS_BUTTON_SELECTOR, timeout=5000):
        log("🚪 Вернулись в список подземелий")
        time.sleep(2)
        antibot_delay(1.0, 1.0)
    else:
        print("⚠️ Кнопка 'Подземелья' недоступна — переходим напрямую")
        try:
            page.goto(DUNGEONS_URL)
            time.sleep(4)
            antibot_delay(1.0, 1.0)
        except:
            return None, enter_failure_count

    # 2) Проверяем рюкзак
    cleanup_backpack_if_needed(page)

    # 2.5) Проверяем готовый крафт (железо)
    repeat_craft_if_ready(page)

    # 3) Ищем следующий доступный данжен
    next_index = find_next_available_dungeon(page, current_index)

    # Если бой уже начат через виджет — возвращаем текущий индекс
    if next_index == "started_battle":
        log("⚔️ Бой начат через виджет — продолжаем")
        return current_index, 0

    if next_index is None:
        # Все на КД — идём в Адские Игры
        min_cd, min_dungeon = get_min_cooldown_time(page)
        if min_cd and min_cd > 0:
            log(f"🎯 Минимальный КД: {min_dungeon} ({min_cd // 60}м {min_cd % 60}с)")
            fight_in_hell_games(page, min_cd)
            next_index = find_next_available_dungeon(page, current_index)
            # Проверяем снова на started_battle
            if next_index == "started_battle":
                return current_index, 0
        else:
            log("💤 Не удалось получить время КД, ждём 60 секунд...")
            time.sleep(60)
            next_index = find_next_available_dungeon(page, current_index)
            if next_index == "started_battle":
                return current_index, 0

        if next_index is None:
            return None, enter_failure_count

    next_dungeon = DUNGEON_ORDER[next_index]
    next_name = DUNGEONS.get(next_dungeon, {}).get("name", next_dungeon)
    log(f"📍 Переходим к данжену: {next_name}")

    # 4) Входим в данжен
    if enter_dungeon(page, next_dungeon):
        return next_index, 0
    else:
        return None, enter_failure_count + 1
