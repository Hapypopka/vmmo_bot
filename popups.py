# ============================================
# VMMO Bot - Popup & Widget Handlers
# ============================================

from config import (
    POPUP_CLOSE_SELECTOR,
    WIDGET_LEAVE_PARTY_SELECTOR,
    REST_BONUS_POPUP_SELECTOR,
    REST_BONUS_CONTINUE_SELECTOR,
    COMBAT_LOOT_SELECTOR,
    DUNGEONS_URL,
)
from utils import antibot_delay, log, safe_click_element, reset_watchdog


def close_achievement_popup(page):
    """
    Закрывает модальное окно "Новое достижение" если оно появилось.
    Возвращает True если попап был закрыт.
    """
    try:
        popup_close = page.query_selector(POPUP_CLOSE_SELECTOR)
        if popup_close:
            safe_click_element(popup_close)
            log("🏆 Закрыли попап достижения")
            antibot_delay(0.5, 0.5)
            return True
    except Exception as e:
        print(f"⚠️ Ошибка при закрытии попапа: {e}")
    return False


def close_party_widget(page):
    """
    Закрывает виджет приглашения в данжен, нажимая "Покинуть банду".
    Срабатывает только если виджет содержит текст о приглашении/ожидании.
    Возвращает True если виджет был закрыт.
    """
    try:
        # Сначала проверяем, есть ли виджет с текстом приглашения
        widget = page.query_selector("div.widget")
        if widget:
            widget_text = widget.inner_text().strip().lower()
            # Только если это виджет приглашения/ожидания
            if "приглашает" in widget_text or "ожидает" in widget_text or "ждёт" in widget_text:
                leave_btn = page.query_selector(WIDGET_LEAVE_PARTY_SELECTOR)
                if leave_btn:
                    safe_click_element(leave_btn)
                    log("👋 Закрыли виджет приглашения (Покинуть банду)")
                    antibot_delay(1.0, 0.5)
                    return True
    except Exception as e:
        print(f"⚠️ Ошибка при закрытии виджета: {e}")
    return False


def handle_party_ready_widget(page):
    """
    Обрабатывает виджет "Банда собрана" - нажимает "В подземелье".
    Возвращает True если виджет был обработан.
    """
    try:
        # Ищем виджет с текстом "Банда собрана"
        widget_desc = page.query_selector("div.widget-description")
        if widget_desc:
            text = widget_desc.inner_text().strip()
            if "Банда собрана" in text:
                # Ищем кнопку "В подземелье"
                buttons = page.query_selector_all("a.go-btn span.go-btn-in")
                for btn in buttons:
                    btn_text = btn.inner_text().strip()
                    if "В подземелье" in btn_text:
                        safe_click_element(btn)
                        log("🏰 Нажали 'В подземелье' (банда собрана)")
                        antibot_delay(2.0, 1.0)
                        return True
    except Exception as e:
        print(f"⚠️ Ошибка при обработке виджета 'Банда собрана': {e}")
    return False


def close_rest_bonus_popup(page):
    """
    Закрывает попап ежедневного бонуса отдыха, нажимая "Продолжить".
    Возвращает True если попап был закрыт.
    """
    try:
        rest_popup = page.query_selector(REST_BONUS_POPUP_SELECTOR)
        if rest_popup:
            continue_btn = page.query_selector(REST_BONUS_CONTINUE_SELECTOR)
            if continue_btn:
                safe_click_element(continue_btn)
                log("🎁 Закрыли попап бонуса отдыха")
                antibot_delay(1.0, 0.5)
                return True
    except Exception as e:
        print(f"⚠️ Ошибка при закрытии попапа бонуса: {e}")
    return False


def close_all_popups(page):
    """Закрывает все известные попапы и виджеты"""
    close_achievement_popup(page)
    close_party_widget(page)
    close_rest_bonus_popup(page)
    handle_party_ready_widget(page)


def collect_loot(page):
    """
    Собирает лут, который появляется во время боя в данженах.
    Кликает на все элементы combat-loot.
    Возвращает количество собранного лута.
    """
    collected = 0
    try:
        loot_items = page.query_selector_all(COMBAT_LOOT_SELECTOR)
        for loot in loot_items:
            if safe_click_element(loot):
                collected += 1
        if collected > 0:
            log(f"💎 Подобрали лут: {collected} шт.")
    except:
        pass  # Не спамим ошибками
    return collected


def check_and_click_start_battle(page):
    """
    Проверяет наличие кнопки "Начать бой" и нажимает её.
    Возвращает True если кнопка была найдена и нажата.
    """
    try:
        buttons = page.query_selector_all("span.go-btn-in, span.go-btn-in._font-art")
        for btn in buttons:
            text = btn.inner_text().strip()
            if "Начать бой" in text:
                safe_click_element(btn)
                log("⚔️ Нажали 'Начать бой'")
                antibot_delay(2.0, 1.0)
                return True
    except Exception as e:
        pass
    return False


def check_and_click_leave_party(page):
    """
    Проверяет наличие кнопки "Покинуть банду" в ВИДЖЕТЕ приглашения и нажимает её.
    НЕ нажимает кнопку в лобби данжена (там она нужна для выхода, но мы не хотим выходить).
    Возвращает True если кнопка была найдена и нажата.
    """
    try:
        # Проверяем ТОЛЬКО кнопку в виджетах (div.widget)
        # Это виджет приглашения от другого игрока
        widget = page.query_selector("div.widget")
        if widget:
            widget_text = widget.inner_text().strip().lower()
            # Только если это виджет приглашения/ожидания от другого игрока
            if "приглашает" in widget_text or "ожидает" in widget_text or "ждёт" in widget_text:
                leave_btn = page.query_selector(WIDGET_LEAVE_PARTY_SELECTOR)
                if leave_btn:
                    safe_click_element(leave_btn)
                    log("👋 Нажали 'Покинуть банду' (виджет приглашения)")
                    antibot_delay(1.5, 1.0)
                    return True
    except Exception as e:
        pass
    return False


def check_shadow_guard_tutorial(page):
    """
    Проверяет, находимся ли мы в туториале Shadow Guard (Пороги Шэдоу Гарда).
    Если видим "Голос Джека" — нужно покинуть банду, т.к. там слишком много врагов.
    Возвращает True если нажали "Покинуть банду".
    """
    try:
        # Проверяем наличие battlefield-lore с текстом Джека
        lore = page.query_selector("div.battlefield-lore-inner, div.lore-inner")
        if lore:
            lore_text = lore.inner_text().strip().lower()
            # Если это туториал Shadow Guard (Голос Джека)
            if "голос джека" in lore_text or "джек" in lore_text:
                log("🎭 Обнаружен туториал Shadow Guard — выходим!")
                # Ищем кнопку "Покинуть банду" на странице боя
                leave_btns = page.query_selector_all("a.go-btn span.go-btn-in")
                for btn in leave_btns:
                    btn_text = btn.inner_text().strip()
                    if "Покинуть банду" in btn_text:
                        safe_click_element(btn)
                        log("👋 Покинули Shadow Guard туториал")
                        antibot_delay(2.0, 1.0)
                        return True
    except Exception as e:
        pass
    return False


def priority_checks(page):
    """
    Приоритетные проверки на каждом шаге цикла.
    Проверяет и нажимает важные кнопки.
    Возвращает True если была нажата какая-либо кнопка.
    """
    # ОТКЛЮЧЕНО: Теперь умираем на боссе вместо выхода
    # # Приоритет 0: Выход из туториала Shadow Guard (Голос Джека)
    # if check_shadow_guard_tutorial(page):
    #     return True

    # Приоритет 1: Начать бой (если мы в лобби данжена)
    if check_and_click_start_battle(page):
        return True

    # Приоритет 2: Покинуть банду (только виджет приглашения от другого игрока)
    if check_and_click_leave_party(page):
        return True

    return False


def emergency_unstuck(page):
    """
    Аварийный выход из застревания.
    Пытается найти и нажать кнопки для выхода из любого состояния.
    Возвращает True если удалось что-то сделать, False если пришлось делать hard reset.
    """
    log("🚨 WATCHDOG: Запуск аварийного выхода из застревания...")

    # 1. Попробовать закрыть попап (крестик)
    try:
        popup_close = page.query_selector(POPUP_CLOSE_SELECTOR)
        if popup_close and popup_close.is_visible():
            safe_click_element(popup_close)
            log("🚨 Закрыли попап (крестик)")
            antibot_delay(1.0, 0.5)
            reset_watchdog()
            return True
    except:
        pass

    # 2. Искать кнопки по тексту (приоритет по порядку)
    button_texts = [
        "Продолжить бой",
        "Продолжить",
        "В подземелье",
        "Начать бой",
        "Закрыть",
        "Выйти",
        "Назад",
    ]

    for text in button_texts:
        try:
            # Ищем в span.go-btn-in (основной тип кнопок)
            buttons = page.query_selector_all("span.go-btn-in, span.go-btn-in._font-art")
            for btn in buttons:
                try:
                    btn_text = btn.inner_text().strip()
                    if text in btn_text and btn.is_visible():
                        safe_click_element(btn)
                        log(f"🚨 Нажали кнопку: '{btn_text}'")
                        antibot_delay(1.5, 0.5)
                        reset_watchdog()
                        return True
                except:
                    continue

            # Ищем в a.go-btn напрямую
            links = page.query_selector_all("a.go-btn")
            for link in links:
                try:
                    link_text = link.inner_text().strip()
                    if text in link_text and link.is_visible():
                        safe_click_element(link)
                        log(f"🚨 Нажали ссылку: '{link_text}'")
                        antibot_delay(1.5, 0.5)
                        reset_watchdog()
                        return True
                except:
                    continue
        except:
            continue

    # 3. Попробовать нажать любую видимую go-btn
    try:
        any_buttons = page.query_selector_all("a.go-btn")
        for btn in any_buttons:
            try:
                if btn.is_visible():
                    btn_text = btn.inner_text().strip()
                    # Пропускаем опасные кнопки
                    if any(skip in btn_text.lower() for skip in ["удалить", "купить", "продать", "отмена"]):
                        continue
                    safe_click_element(btn)
                    log(f"🚨 Нажали любую кнопку: '{btn_text}'")
                    antibot_delay(1.5, 0.5)
                    reset_watchdog()
                    return True
            except:
                continue
    except:
        pass

    # 4. Ничего не помогло — hard reset на /dungeons
    log("🚨 Ничего не помогло — принудительный переход на /dungeons")
    try:
        page.goto(DUNGEONS_URL)
        antibot_delay(3.0, 1.0)
        reset_watchdog()
    except Exception as e:
        log(f"🚨 Ошибка при переходе: {e}")

    return False
