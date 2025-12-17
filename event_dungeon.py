# ============================================
# VMMO Bot - Event Dungeon (Сталкер Адского Кладбища)
# ============================================

import time
from config import CITY_URL, BASE_URL
from utils import antibot_delay, log, safe_click

# URLs
BACKPACK_URL = f"{BASE_URL}/user/rack"

# Селекторы ивента
EVENT_WIDGET_SELECTOR = 'a.city-menu-l-link[href*="HellStalker"]'
EVENT_DUNGEON_SELECTOR = 'a.event-map-widget[href*="EventCemetery"]'

# Селекторы предметов
STALKER_SEAL_SELECTOR = 'a.iSuperior[href*="item"]:has-text("Печать Сталкера")'
TIKUAN_CRYSTAL_SELECTOR = 'a.iGood[href*="item"]:has-text("Треснутый Кристалл Тикуана")'


def equip_item(page, selector, item_name):
    """
    Заходит в рюкзак и надевает предмет по селектору.
    Возвращает True если предмет надет или уже был надет.
    """
    try:
        # Переходим в рюкзак
        page.goto(BACKPACK_URL, wait_until="domcontentloaded")
        time.sleep(3)
        antibot_delay(1.0, 0.5)

        # Ищем предмет в рюкзаке
        item_link = page.query_selector(selector)
        if not item_link:
            log(f"ℹ️ {item_name} не найден в рюкзаке (возможно уже надет)")
            return True  # Продолжаем — может уже надет

        # Нажимаем на предмет чтобы открыть меню
        item_link.click()
        log(f"🔮 Нашли {item_name} — открываем меню")
        time.sleep(2)
        antibot_delay(0.5, 0.3)

        # Ищем кнопку "Надеть"
        wear_btn = page.query_selector('a.go-btn[data-on-click-sound="ui stranger-dressup"]')
        if not wear_btn:
            # Попробуем найти по тексту
            buttons = page.query_selector_all("a.go-btn")
            for btn in buttons:
                text = btn.inner_text().strip()
                if text == "Надеть":
                    wear_btn = btn
                    break

        if wear_btn:
            wear_btn.click()
            log(f"✅ Надели {item_name}!")
            time.sleep(2)
            antibot_delay(1.0, 0.5)
            return True
        else:
            log(f"⚠️ Кнопка 'Надеть' не найдена для {item_name}")
            return True  # Продолжаем — может уже надет

    except Exception as e:
        log(f"⚠️ Ошибка надевания {item_name}: {e}")
        return True  # Продолжаем в любом случае


def equip_stalker_seal(page):
    """Надевает Печать Сталкера для ивента."""
    return equip_item(page, STALKER_SEAL_SELECTOR, "Печать Сталкера")


def equip_tikuan_crystal(page):
    """Надевает Треснутый Кристалл Тикуана для обычных данженов."""
    return equip_item(page, TIKUAN_CRYSTAL_SELECTOR, "Кристалл Тикуана")


def check_event_available(page):
    """
    Проверяет, доступен ли ивент "Сталкер Адского Кладбища".
    Возвращает True если виджет ивента есть на странице города.
    """
    try:
        # Переходим в город
        page.goto(CITY_URL, wait_until="domcontentloaded")
        time.sleep(3)
        antibot_delay(1.0, 0.5)

        # Ищем виджет ивента
        event_widget = page.query_selector(EVENT_WIDGET_SELECTOR)
        if event_widget:
            # Проверяем таймер — если есть, ивент активен
            timer = event_widget.query_selector(".city-menu-timer")
            if timer:
                timer_text = timer.inner_text().strip()
                log(f"🎃 Ивент 'Сталкер' доступен! Осталось: {timer_text}")
                return True

        return False
    except Exception as e:
        log(f"⚠️ Ошибка проверки ивента: {e}")
        return False


def enter_event_dungeon(page):
    """
    Входит в ивентовое подземелье "Перевал Мертвецов".
    Возвращает True если успешно вошли в бой.
    """
    try:
        # 1) Переходим в город (если ещё не там)
        if "city" not in page.url:
            page.goto(CITY_URL, wait_until="domcontentloaded")
            time.sleep(3)
            antibot_delay(1.0, 0.5)

        # 2) Нажимаем на виджет ивента
        event_widget = page.query_selector(EVENT_WIDGET_SELECTOR)
        if not event_widget:
            log("⚠️ Виджет ивента не найден")
            return False

        event_widget.click()
        log("🎃 Нажали на виджет ивента 'Сталкер'")
        time.sleep(3)
        antibot_delay(1.0, 0.5)

        # 3) Нажимаем на "Перевал Мертвецов"
        dungeon_btn = page.query_selector(EVENT_DUNGEON_SELECTOR)
        if not dungeon_btn:
            log("⚠️ Кнопка 'Перевал Мертвецов' не найдена")
            return False

        dungeon_btn.click()
        log("🏰 Нажали на 'Перевал Мертвецов'")
        time.sleep(3)
        antibot_delay(1.0, 0.5)

        # 3.5) Проверяем КД — ищем текст "Ты сможешь войти через"
        page_text = page.inner_text("body")
        if "Ты сможешь войти через" in page_text:
            # Пробуем извлечь время КД
            import re
            cd_match = re.search(r"войти через\s+(.+?)\.", page_text)
            cd_time = cd_match.group(1) if cd_match else "неизвестно"
            log(f"⏳ Ивент на КД: {cd_time}")
            return "cooldown"  # Специальное значение для КД

        # 4) Нажимаем "Войти"
        enter_clicked = False
        try:
            page.wait_for_selector("a.go-btn", timeout=10000)
            buttons = page.query_selector_all("a.go-btn")
            for btn in buttons:
                text = btn.inner_text().strip()
                if text == "Войти":
                    btn.dispatch_event("click")
                    enter_clicked = True
                    log("✅ Нажали 'Войти' (ивент)")
                    break
        except:
            pass

        if not enter_clicked:
            log("⚠️ Кнопка 'Войти' не найдена в ивенте")
            return False

        time.sleep(3)
        antibot_delay(1.0, 0.5)

        # 5) Нажимаем "Начать бой!"
        start_clicked = False
        try:
            page.wait_for_selector("span.go-btn-in._font-art", timeout=15000)
            buttons = page.query_selector_all("a.go-btn")
            for btn in buttons:
                text = btn.inner_text().strip()
                if "Начать бой" in text:
                    btn.dispatch_event("click")
                    start_clicked = True
                    log("⚔️ Начали бой! (ивент)")
                    break
        except:
            pass

        if not start_clicked:
            log("⚠️ Кнопка 'Начать бой' не найдена в ивенте")
            return False

        antibot_delay(4.0, 1.5)
        return True

    except Exception as e:
        log(f"❌ Ошибка входа в ивент: {e}")
        return False


def check_event_dungeon_cooldown(page):
    """
    Проверяет кулдаун ивентового данжена.
    Возвращает (on_cooldown: bool, cd_time: str или None)
    """
    try:
        # Переходим в город
        if "city" not in page.url:
            page.goto(CITY_URL, wait_until="domcontentloaded")
            time.sleep(3)

        # Нажимаем на виджет ивента
        event_widget = page.query_selector(EVENT_WIDGET_SELECTOR)
        if not event_widget:
            return True, "ивент не найден"

        event_widget.click()
        time.sleep(3)

        # Нажимаем на данжен
        dungeon_btn = page.query_selector(EVENT_DUNGEON_SELECTOR)
        if not dungeon_btn:
            return True, "данжен не найден"

        dungeon_btn.click()
        time.sleep(3)

        # Проверяем — есть ли кнопка "Войти" или показывает КД
        buttons = page.query_selector_all("a.go-btn")
        for btn in buttons:
            text = btn.inner_text().strip()
            if text == "Войти":
                return False, None  # Нет КД, можно входить

        # Ищем таймер КД на странице
        cd_element = page.query_selector(".cooldown-timer, .cd-timer, [class*='cooldown']")
        if cd_element:
            cd_text = cd_element.inner_text().strip()
            return True, cd_text

        return True, "КД"

    except Exception as e:
        log(f"⚠️ Ошибка проверки КД ивента: {e}")
        return True, "ошибка"


def try_event_dungeon(page):
    """
    Пробует войти в ивентовое подземелье, если оно доступно и не на КД.
    Возвращает:
        "entered" — если успешно вошли в бой
        "on_cooldown" — если ивент на КД (также надевает Кристалл Тикуана)
        "not_available" — если ивент не доступен
        "error" — если ошибка
    """
    try:
        # Проверяем доступность ивента
        if not check_event_available(page):
            return "not_available"

        # Надеваем Печать Сталкера перед входом
        equip_stalker_seal(page)

        # Пробуем войти
        result = enter_event_dungeon(page)

        if result == True:
            return "entered"
        elif result == "cooldown":
            # Ивент на КД — надеваем Кристалл Тикуана для обычных данженов
            log("🔄 Ивент на КД — надеваем Кристалл Тикуана")
            equip_tikuan_crystal(page)
            return "on_cooldown"
        else:
            return "on_cooldown"  # Другая ошибка

    except Exception as e:
        log(f"❌ Ошибка ивента: {e}")
        return "error"
