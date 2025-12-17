# ============================================
# VMMO Bot - Backpack Management
# ============================================

import time
from config import (
    BACKPACK_THRESHOLD,
    BACKPACK_LINK_SELECTOR,
    BACKPACK_COUNT_SELECTOR,
    CONFIRM_BUTTON_SELECTOR,
    DUNGEONS_URL,
)
from utils import antibot_delay, log, safe_click, safe_click_element

# Список предметов, которые НЕЛЬЗЯ выкидывать/продавать/разбирать
PROTECTED_ITEMS = [
    "Железо",
    "Железная Руда",
    "Железный Слиток",
    "Осколок Грёз",
    "Осколок Порядка",
    "Осколок Рассвета",
    "Осколок Ночи",
    "Осколок Тени",
    "Осколок Хаоса",
    "Осколок",  # На всякий случай, если есть просто "Осколок"
    # Ценные предметы
    "Треснутый Кристалл Тикуана",
    # Ивентовые предметы
    "Печать Сталкера I",
    "Печать Сталкера II",
    "Печать Сталкера III",
    "Печать Сталкера",  # На всякий случай без уровня
    # Новогодние ивентовые
    "Ледяной Кристалл",
    "Уголь Эфирного Древа",
]

from popups import close_achievement_popup, close_party_widget


def is_protected_item(item_name):
    """
    Проверяет, является ли предмет защищённым (нельзя продавать/выкидывать).
    """
    if not item_name:
        return False
    return item_name in PROTECTED_ITEMS


def load_auction_blacklist():
    """
    Загружает чёрный список предметов для аукциона.
    Эти предметы не продались (истёк срок лота) и не будут выставляться повторно.
    """
    import json
    import os

    blacklist_file = os.path.join(os.path.dirname(__file__), "auction_blacklist.json")

    try:
        if os.path.exists(blacklist_file):
            with open(blacklist_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        log(f"⚠️ Ошибка чтения чёрного списка: {e}")

    return []


def is_auction_blacklisted(item_name):
    """
    Проверяет, находится ли предмет в чёрном списке аукциона.
    """
    if not item_name:
        return False

    blacklist = load_auction_blacklist()
    return item_name in blacklist


from stats import get_stats


def get_backpack_count(page):
    """
    Получает текущее количество предметов в рюкзаке.
    Парсит текст вида "11/28" → возвращает (current, max_size)
    """
    try:
        count_el = page.query_selector(BACKPACK_COUNT_SELECTOR)
        if count_el:
            text = count_el.inner_text().strip()
            if '/' in text:
                current, max_size = text.split('/')
                return int(current), int(max_size)
    except Exception as e:
        print(f"⚠️ Ошибка при получении счётчика рюкзака: {e}")
    return None, None


def need_cleanup_backpack(page):
    """Проверяет, нужна ли очистка рюкзака"""
    current, max_size = get_backpack_count(page)
    if current is not None:
        log(f"🎒 Рюкзак: {current}/{max_size}")
        return current >= BACKPACK_THRESHOLD
    return False


def open_backpack(page):
    """Открывает рюкзак и ждёт загрузки"""
    if safe_click(page, BACKPACK_LINK_SELECTOR, timeout=5000):
        log("📦 Открыли рюкзак")
        antibot_delay(1.5, 1.0)
        # Ждём появления элементов рюкзака
        try:
            page.wait_for_selector("div.p10", timeout=5000)
        except:
            pass
        return True
    else:
        print(f"❌ Не удалось открыть рюкзак")
        return False


def find_button_by_text(page, button_text, selector="a.go-btn"):
    """
    Ищет кнопку с заданным текстом.
    Возвращает элемент или None если не найдена.
    """
    try:
        buttons = page.query_selector_all(selector)
        for btn in buttons:
            text = btn.inner_text().strip()
            if text == button_text:
                return btn
    except Exception as e:
        print(f"⚠️ Ошибка при поиске кнопки '{button_text}': {e}")
    return None


def find_auction_button(page):
    """Ищет кнопку "На аукцион"."""
    return find_button_by_text(page, "На аукцион")


def is_item_green(item_element):
    """
    Проверяет, является ли предмет зелёным (iGood).
    item_element — это div.p10 или подобный контейнер предмета.
    """
    try:
        name_link = item_element.query_selector("span.e-name a")
        if name_link:
            classes = name_link.get_attribute("class") or ""
            return "iGood" in classes
    except:
        pass
    return False


def get_item_name(item_element):
    """
    Получает название предмета из элемента.
    Возвращает строку с названием или None.
    """
    try:
        name_el = item_element.query_selector("span.e-name a")
        if name_el:
            return name_el.inner_text().strip()
    except:
        pass
    return None


def find_item_with_auction_button(page, skip_items=None):
    """
    Ищет предмет с кнопкой "На аукцион".
    skip_items — список названий предметов, которые нужно пропустить (для разборки).
    Автоматически пропускает защищённые предметы (железо, руда).
    Предметы из чёрного списка аукциона разбираются вместо продажи.
    Возвращает (item_element, auction_button, is_green, item_name) или (None, None, False, None).
    """
    if skip_items is None:
        skip_items = []

    try:
        items = page.query_selector_all("div.p10")
        for item in items:
            # Получаем название предмета
            item_name = get_item_name(item)

            # Пропускаем предметы из списка skip
            if item_name and item_name in skip_items:
                continue

            # Пропускаем защищённые предметы (железо, руда)
            if is_protected_item(item_name):
                continue

            # Предметы из чёрного списка аукциона (не продались) — разбираем
            if is_auction_blacklisted(item_name):
                log(f"🚫 '{item_name}' в чёрном списке — разбираем")
                if disassemble_single_item(page, item):
                    log(f"🔧 Разобрали '{item_name}'")
                else:
                    log(f"⚠️ Не удалось разобрать '{item_name}'")
                continue

            buttons = item.query_selector_all("a.go-btn")
            for btn in buttons:
                text = btn.inner_text().strip()
                # Проверяем что текст содержит "На аукцион" (может быть внутри span)
                if "На аукцион" in text:
                    is_green = is_item_green(item)
                    return item, btn, is_green, item_name
    except Exception as e:
        print(f"⚠️ Ошибка при поиске предмета с аукционом: {e}")
    return None, None, False, None


def find_disassemble_button_in_item(item_element):
    """
    Ищет кнопку "Разобрать" внутри элемента предмета.
    """
    try:
        buttons = item_element.query_selector_all("a.go-btn")
        for btn in buttons:
            text = btn.inner_text().strip()
            if text == "Разобрать":
                return btn
    except:
        pass
    return None


def find_item_by_name(page, item_name):
    """
    Ищет предмет по названию в рюкзаке.
    Возвращает элемент предмета или None.
    """
    try:
        items = page.query_selector_all("div.p10")
        for item in items:
            name = get_item_name(item)
            if name and name == item_name:
                return item
    except:
        pass
    return None


def disassemble_item_by_name(page, item_name):
    """
    Разбирает предмет по названию.
    Возвращает True если успешно.
    """
    item = find_item_by_name(page, item_name)
    if not item:
        log(f"⚠️ Предмет '{item_name}' не найден для разборки")
        return False

    return disassemble_single_item(page, item)


def find_drop_button_in_item(item_element):
    """
    Ищет кнопку "Выкинуть" внутри элемента предмета.
    """
    try:
        buttons = item_element.query_selector_all("a.go-btn")
        for btn in buttons:
            text = btn.inner_text().strip()
            if text == "Выкинуть":
                return btn
    except:
        pass
    return None


def drop_single_item(page, item_element):
    """
    Выкидывает один конкретный предмет.
    Возвращает True если успешно.
    """
    drop_btn = find_drop_button_in_item(item_element)
    if not drop_btn:
        return False

    if not safe_click_element(drop_btn):
        return False

    log("🗑️ Нажали 'Выкинуть'")

    # Ждём загрузки страницы подтверждения
    try:
        page.wait_for_selector("span.go-btn-in", timeout=5000)
    except:
        pass
    antibot_delay(1.0, 0.5)

    # Подтверждаем выброс — ищем кнопку "Да, точно"
    try:
        confirm_buttons = page.query_selector_all("span.go-btn-in")
        for btn in confirm_buttons:
            text = btn.inner_text().strip()
            if "Да, точно" in text:
                if safe_click_element(btn):
                    log("✅ Подтвердили выброс")
                    antibot_delay(1.5, 0.5)
                    return True
                break
    except Exception as e:
        print(f"⚠️ Ошибка при подтверждении выброса: {e}")

    return False


def drop_item_by_name(page, item_name):
    """
    Выбрасывает предмет по названию.
    Возвращает True если успешно.
    """
    item = find_item_by_name(page, item_name)
    if not item:
        log(f"⚠️ Предмет '{item_name}' не найден для выброса")
        return False

    return drop_single_item(page, item)


def disassemble_or_drop_item(page, item_name):
    """
    Пытается разобрать предмет. Если не получается — выкидывает.
    После выкидывания возвращается в рюкзак.
    НЕ трогает защищённые предметы (железо, руда).
    Возвращает True если успешно.
    """
    # Защита: не трогаем железо и руду
    if is_protected_item(item_name):
        log(f"🛡️ Предмет '{item_name}' защищён — пропускаем")
        return False

    item = find_item_by_name(page, item_name)
    if not item:
        log(f"⚠️ Предмет '{item_name}' не найден")
        return False

    # Сначала пробуем разобрать
    if disassemble_single_item(page, item):
        return True

    # Если не получилось разобрать — выкидываем
    log(f"🗑️ Предмет '{item_name}' нельзя разобрать — выкидываем")
    item = find_item_by_name(page, item_name)
    if item and drop_single_item(page, item):
        # После выкидывания нужно вернуться в рюкзак
        open_backpack(page)
        return True

    return False


def find_disassemble_button(page):
    """Ищет кнопку "Разобрать"."""
    return find_button_by_text(page, "Разобрать")


def parse_item_count(element):
    """
    Извлекает количество предметов из элемента.
    Ищет span.e-count с текстом типа " x2" или "x10".
    Возвращает число или 1 если не найдено.
    """
    try:
        count_el = element.query_selector("span.e-count")
        if count_el:
            text = count_el.inner_text().strip()
            # Убираем 'x' или 'х' и пробелы
            text = text.lower().replace('x', '').replace('х', '').strip()
            if text.isdigit():
                return int(text)
    except Exception:
        pass
    return 1


def get_my_item_count(page):
    """
    Получает количество нашего товара на странице аукциона.
    Наш товар находится в div.panel-inner-2.
    """
    try:
        my_item = page.query_selector("div.panel-inner-2")
        if my_item:
            return parse_item_count(my_item)
    except Exception:
        pass
    return 1


def get_competitor_min_price_per_unit(page):
    """
    Получает минимальную цену ЗА ЕДИНИЦУ товара из списка конкурентов.
    Возвращает (gold, silver, count) или (0, 0, 1) если не найдено.
    gold и silver — цена за весь лот, count — количество в лоте.
    """
    try:
        # Ищем первый элемент списка конкурентов (самая низкая цена)
        first_item = page.query_selector("div.list-el.first")
        if not first_item:
            first_item = page.query_selector("div.list-el")

        if not first_item:
            log("⚠️ Не найден список конкурентов")
            return 0, 0, 1

        # Получаем количество у конкурента
        comp_count = parse_item_count(first_item)

        # Ищем кнопку "выкупить" с ценой
        buyout_btn = first_item.query_selector("a.go-btn._auction")
        if not buyout_btn:
            log("⚠️ Не найдена кнопка выкупа у конкурента")
            return 0, 0, 1

        gold = 0
        silver = 0

        # Проверяем наличие золота
        gold_icon = buyout_btn.query_selector("span.i12-money_gold")
        if gold_icon:
            parent = gold_icon.evaluate_handle("el => el.parentElement")
            price_spans = parent.query_selector_all("span")
            for span in price_spans:
                text = span.inner_text().strip()
                if text.isdigit():
                    gold = int(text)
                    break

        # Проверяем наличие серебра
        silver_icon = buyout_btn.query_selector("span.i12-money_silver")
        if silver_icon:
            parent = silver_icon.evaluate_handle("el => el.parentElement")
            price_spans = parent.query_selector_all("span")
            for span in price_spans:
                text = span.inner_text().strip()
                if text.isdigit():
                    silver = int(text)
                    break

        log(f"💰 Конкурент: {gold}з {silver}с за x{comp_count}")
        return gold, silver, comp_count

    except Exception as e:
        print(f"⚠️ Ошибка при получении цены конкурента: {e}")
        return 0, 0, 1


def set_auction_price(page, gold, silver):
    """
    Устанавливает цену в поля аукциона (начальная цена и выкуп).
    """
    try:
        # Начальная цена (bid)
        bid_gold = page.query_selector("input[name='bidGold']")
        bid_silver = page.query_selector("input[name='bidSilver']")

        # Стоимость выкупа (buyout)
        buyout_gold = page.query_selector("input[name='buyoutGold']")
        buyout_silver = page.query_selector("input[name='buyoutSilver']")

        if bid_gold and bid_silver and buyout_gold and buyout_silver:
            # Очищаем и заполняем поля
            bid_gold.fill(str(gold))
            bid_silver.fill(str(silver))
            buyout_gold.fill(str(gold))
            buyout_silver.fill(str(silver))
            log(f"💰 Установлена цена: {gold}з {silver}с")
            return True
        else:
            log("⚠️ Не найдены поля для ввода цены")
            return False

    except Exception as e:
        print(f"⚠️ Ошибка при установке цены: {e}")
        return False


def calculate_undercut_price(gold, silver):
    """
    Вычисляет цену на 1 серебро меньше.
    Возвращает (new_gold, new_silver).
    """
    # Переводим всё в серебро
    total_silver = gold * 100 + silver

    # Уменьшаем на 1 серебро (минимум 1 серебро)
    total_silver = max(1, total_silver - 1)

    # Обратно в золото и серебро
    new_gold = total_silver // 100
    new_silver = total_silver % 100

    return new_gold, new_silver


def has_low_price_warning(page):
    """
    Проверяет наличие предупреждения о низкой цене.
    Возвращает True если есть предупреждение.
    """
    try:
        warning = page.query_selector("span.feedbackPanelERROR")
        if warning:
            text = warning.inner_text().strip()
            if "ниже рыночной" in text.lower():
                return True
    except:
        pass
    return False


def try_create_lot(page, gold, silver):
    """
    Пытается создать лот. Если появляется предупреждение о низкой цене,
    возвращает "low_price" — предмет нужно разобрать.
    Возвращает:
        "success" — лот создан
        "low_price" — цена слишком низкая, нужно разобрать
        "error" — другая ошибка
    """
    set_auction_price(page, gold, silver)
    antibot_delay(0.3, 0.2)

    create_lot_btn = page.query_selector("input.go-btn[value='Создать лот']")
    if not create_lot_btn:
        print("⚠️ Не нашли кнопку 'Создать лот'")
        return "error"

    safe_click_element(create_lot_btn)
    antibot_delay(0.8, 0.3)

    # Проверяем предупреждение о низкой цене
    if has_low_price_warning(page):
        log("⚠️ Цена слишком низкая — предмет будет разобран")
        return "low_price"
    else:
        # Лот создан успешно
        log("✅ Лот создан!")
        return "success"


def disassemble_single_item(page, item_element):
    """
    Разбирает один конкретный предмет.
    Возвращает True если успешно.
    """
    disassemble_btn = find_disassemble_button_in_item(item_element)
    if not disassemble_btn:
        return False

    if not safe_click_element(disassemble_btn):
        return False

    log("🔧 Нажали 'Разобрать' (зелёный предмет)")
    antibot_delay(1.0, 0.5)

    try:
        confirm_buttons = page.query_selector_all(CONFIRM_BUTTON_SELECTOR)
        for btn in confirm_buttons:
            text = btn.inner_text().strip()
            if "Да, точно" in text:
                if safe_click_element(btn):
                    log("✅ Подтвердили разборку")
                    antibot_delay(1.0, 0.5)
                    return True
                break
    except Exception as e:
        print(f"⚠️ Ошибка при подтверждении: {e}")

    return False


def sell_on_auction(page):
    """
    Выставляет все предметы с кнопкой "На аукцион".
    Зелёные предметы (iGood) разбираются вместо аукциона.
    Если цена слишком низкая — предмет добавляется в список для разборки.
    Цикл: На аукцион → анализ цен конкурентов → установка цены -1с → Создать лот → повторить
    Возвращает количество выставленных предметов.
    """
    auction_count = 0
    disassembled_green = 0
    items_to_disassemble = []  # Список названий предметов для разборки (низкая цена)

    while True:
        item, auction_btn, is_green, item_name = find_item_with_auction_button(page, skip_items=items_to_disassemble)
        if not item or not auction_btn:
            break

        # Если предмет зелёный — пробуем разобрать
        if is_green:
            if disassemble_single_item(page, item):
                disassembled_green += 1
                continue
            # Если не удалось разобрать — выставляем на аукцион (ниже)

        if not safe_click_element(auction_btn):
            print(f"⚠️ Ошибка при клике на 'На аукцион'")
            break
        log(f"💰 Нажали 'На аукцион' ({item_name})")

        # Ждём загрузки страницы аукциона (появления списка конкурентов или формы)
        try:
            page.wait_for_selector("div.list-el, input[name='bidGold']", timeout=10000)
            log("✅ Страница аукциона загружена")
        except Exception:
            log("⚠️ Страница аукциона не загрузилась — пробуем продолжить")

        antibot_delay(1.0, 0.5)

        # Получаем наше количество
        my_count = get_my_item_count(page)

        # Получаем цену конкурента (цена за весь лот и количество)
        comp_gold, comp_silver, comp_count = get_competitor_min_price_per_unit(page)

        if comp_gold > 0 or comp_silver > 0:
            # Переводим в серебро и считаем цену за 1 штуку
            comp_total_silver = comp_gold * 100 + comp_silver
            price_per_unit = comp_total_silver // comp_count  # цена за 1 штуку

            # Наша цена = (цена_за_штуку * наше_кол-во) - 1 серебро
            our_total_silver = (price_per_unit * my_count) - 1
            our_total_silver = max(1, our_total_silver)  # минимум 1 серебро

            # Обратно в золото и серебро
            new_gold = our_total_silver // 100
            new_silver = our_total_silver % 100

            log(f"📉 Конкурент: {comp_gold}з {comp_silver}с за x{comp_count} → {price_per_unit}с/шт")
            log(f"📉 Наш товар: x{my_count} → ставим {new_gold}з {new_silver}с")
        else:
            log("⚠️ Конкуренты не найдены — используем минимальную цену")
            new_gold = 0
            new_silver = 5  # Минимальная цена (было 10с — слишком много для непопулярных предметов)

        # Пробуем создать лот
        result = try_create_lot(page, new_gold, new_silver)

        if result == "success":
            auction_count += 1
            antibot_delay(1.0, 0.5)

            if not open_backpack(page):
                break
            antibot_delay(0.5, 0.5)

        elif result == "low_price":
            # Цена слишком низкая — добавляем в список для разборки
            if item_name:
                items_to_disassemble.append(item_name)
                log(f"📋 '{item_name}' добавлен в список для разборки")

            # Возвращаемся в рюкзак
            if not open_backpack(page):
                break
            antibot_delay(0.5, 0.5)

        else:
            # Ошибка
            break

    # Разбираем/выбрасываем предметы с низкой ценой
    if items_to_disassemble:
        log(f"🔧 Утилизируем {len(items_to_disassemble)} предметов с низкой ценой...")
        for item_name in items_to_disassemble:
            if disassemble_or_drop_item(page, item_name):
                disassembled_green += 1
                antibot_delay(0.5, 0.3)

    log(f"💰 Выставлено на аукцион: {auction_count}")
    if disassembled_green > 0:
        log(f"🔧 Разобрано предметов: {disassembled_green}")
        get_stats().items_disassembled(disassembled_green)
    if auction_count > 0:
        get_stats().items_auctioned(auction_count)
    return auction_count


def open_bonus_items(page):
    """
    Открывает все бонусы в рюкзаке (Бонус подземелий, Бонус Роста защиты и т.д.).
    Ищет предметы со словом "Бонус" в названии и нажимает "Открыть".
    Возвращает количество открытых бонусов.
    """
    opened_count = 0

    while True:
        # Ищем все предметы в рюкзаке
        items = page.query_selector_all("div.p10")
        found_bonus = False

        for item in items:
            try:
                # Проверяем название предмета
                name_el = item.query_selector("span.e-name a")
                if not name_el:
                    continue

                item_name = name_el.inner_text().strip()

                # Если это бонус
                if "Бонус" in item_name:
                    # Ищем кнопку "Открыть" внутри этого предмета
                    open_btn = item.query_selector("a.go-btn._night._single._rack")
                    if open_btn:
                        btn_text = open_btn.inner_text().strip()
                        if btn_text == "Открыть":
                            if safe_click_element(open_btn):
                                log(f"🎁 Открыли: {item_name}")
                                opened_count += 1
                                antibot_delay(1.5, 0.5)
                                found_bonus = True
                                break  # После клика DOM обновляется, начинаем заново
            except Exception:
                continue

        if not found_bonus:
            break

    if opened_count > 0:
        log(f"🎁 Открыто бонусов: {opened_count}")
    return opened_count


def disassemble_items(page):
    """
    Разбирает все предметы с кнопкой "Разобрать".
    Цикл: Разобрать → Да, точно → повторить
    """
    disassembled_count = 0

    while True:
        disassemble_btn = find_disassemble_button(page)
        if not disassemble_btn:
            break

        if not safe_click_element(disassemble_btn):
            print(f"⚠️ Ошибка при клике на 'Разобрать'")
            break
        log("🔧 Нажали 'Разобрать'")
        antibot_delay(1.0, 0.5)

        try:
            confirm_buttons = page.query_selector_all(CONFIRM_BUTTON_SELECTOR)
            confirmed = False
            for btn in confirm_buttons:
                text = btn.inner_text().strip()
                if "Да, точно" in text:
                    if safe_click_element(btn):
                        log("✅ Подтвердили разборку")
                        disassembled_count += 1
                        antibot_delay(1.0, 0.5)
                        confirmed = True
                    break

            if not confirmed:
                print("⚠️ Не нашли кнопку 'Да, точно'")
                break

        except Exception as e:
            print(f"⚠️ Ошибка при подтверждении: {e}")
            break

        antibot_delay(0.5, 0.5)

    log(f"🎒 Разобрано предметов: {disassembled_count}")
    if disassembled_count > 0:
        get_stats().items_disassembled(disassembled_count)
    return disassembled_count


def drop_green_unusable_items(page):
    """
    Выкидывает зелёные предметы без кнопок "На аукцион" или "Разобрать".
    Это предметы, которые нельзя ни продать, ни разобрать (типа quest items).
    Пропускает защищённые предметы (железо, руда, осколки).
    Возвращает количество выброшенных предметов.
    """
    dropped_count = 0

    while True:
        items = page.query_selector_all("div.p10")
        found = False

        for item in items:
            try:
                # Проверяем, зелёный ли предмет
                if not is_item_green(item):
                    continue

                # Получаем название
                item_name = get_item_name(item)

                # Пропускаем защищённые
                if is_protected_item(item_name):
                    continue

                # Проверяем наличие кнопок "На аукцион" и "Разобрать"
                buttons = item.query_selector_all("a.go-btn")
                has_auction = False
                has_disassemble = False
                has_drop = False

                for btn in buttons:
                    text = btn.inner_text().strip()
                    if "На аукцион" in text:
                        has_auction = True
                    elif text == "Разобрать":
                        has_disassemble = True
                    elif text == "Выкинуть":
                        has_drop = True

                # Если нет ни аукциона, ни разборки, но есть "Выкинуть" — выкидываем
                if not has_auction and not has_disassemble and has_drop:
                    log(f"🗑️ Выбрасываем зелёный предмет без использования: {item_name}")
                    if drop_single_item(page, item):
                        dropped_count += 1
                        found = True
                        # После выброса нужно вернуться в рюкзак
                        if not open_backpack(page):
                            return dropped_count
                        antibot_delay(0.5, 0.3)
                        break  # DOM изменился, начинаем заново
            except Exception as e:
                log(f"⚠️ Ошибка при проверке предмета: {e}")
                continue

        if not found:
            break

    if dropped_count > 0:
        log(f"🗑️ Выброшено бесполезных предметов: {dropped_count}")
    return dropped_count


def get_current_backpack_page(page):
    """
    Определяет текущую страницу рюкзака.
    Ищет активную страницу (span.page вместо a.page).
    Возвращает номер страницы или 1 если не найдено.
    """
    try:
        # Активная страница — это span.page (не ссылка)
        active_page = page.query_selector("span.page")
        if active_page:
            text = active_page.inner_text().strip()
            if text.isdigit():
                return int(text)
    except Exception as e:
        log(f"⚠️ Ошибка при определении текущей страницы: {e}")
    return 1


def go_to_next_backpack_page(page, current_page):
    """
    Переходит на следующую страницу рюкзака.
    current_page: номер текущей страницы
    Возвращает True если переход успешен.
    """
    next_page = current_page + 1
    try:
        page_links = page.query_selector_all("a.page")
        for link in page_links:
            title = link.get_attribute("title")
            # Ищем именно следующую страницу
            if title and f"Перейти на страницу {next_page}" in title:
                if safe_click_element(link):
                    log(f"📄 Переход на страницу {next_page} рюкзака")
                    antibot_delay(1.5, 0.5)
                    return True
    except Exception as e:
        log(f"⚠️ Ошибка при переходе на страницу {next_page}: {e}")
    return False


def cleanup_backpack_if_needed(page):
    """
    Проверяет рюкзак и очищает при необходимости.
    Приоритет: 1) Аукцион, 2) Разборка
    Вызывать перед входом в данжи.
    Возвращает True если была выполнена очистка.
    """
    if not need_cleanup_backpack(page):
        return False

    log("🎒 Рюкзак почти полон — очищаем...")

    # Закрываем попапы перед открытием рюкзака
    close_achievement_popup(page)
    close_party_widget(page)

    if not open_backpack(page):
        return False

    # Обрабатываем все страницы рюкзака (максимум 3)
    max_pages = 3

    for page_num in range(1, max_pages + 1):
        if page_num > 1:
            log(f"📄 Обрабатываем страницу {page_num} рюкзака")

        # Приоритет 0: Открываем бонусы (Бонус подземелий и т.д.)
        open_bonus_items(page)

        # Приоритет 1: Выставляем на аукцион
        sell_on_auction(page)

        # Приоритет 2: Разбираем оставшееся
        disassemble_items(page)

        # Приоритет 3: Выбрасываем зелёные предметы без использования
        drop_green_unusable_items(page)

        # Пробуем перейти на следующую страницу (если она есть)
        if page_num < max_pages:
            if not go_to_next_backpack_page(page, page_num):
                # Следующей страницы нет — выходим
                break

    log("✅ Рюкзак очищен!")

    # Возвращаемся в подземелья
    try:
        page.goto(DUNGEONS_URL)
        time.sleep(3)
        antibot_delay(1.0, 1.0)
        log("🏰 Вернулись в список подземелий")
    except Exception as e:
        print(f"❌ Не удалось вернуться в подземелья: {e}")

    # Проверяем готовый крафт (после очистки рюкзака)
    repeat_craft_if_ready(page)

    return True


def check_craft_ready(page):
    """
    Проверяет, есть ли готовый крафт на странице.
    Ищет блок info-box с текстом "Готово" И кнопкой "Повторить".
    Возвращает элемент кнопки "Повторить" или None.
    """
    try:
        info_boxes = page.query_selector_all("div.info-box")
        for box in info_boxes:
            # Проверяем есть ли текст "Готово" в боксе
            box_text = box.inner_text()
            if "Готово" in box_text:
                # Ищем кнопку "Повторить"
                buttons = box.query_selector_all("a.go-btn")
                has_repeat_btn = False
                for btn in buttons:
                    btn_text = btn.inner_text().strip()
                    if "Повторить" in btn_text:
                        has_repeat_btn = True
                        return btn

                # Готово есть, но кнопки "Повторить" нет — пропускаем
                if not has_repeat_btn:
                    log("⚒️ Крафт готов, но кнопки 'Повторить' нет — пропускаем")
                    return None
    except Exception as e:
        print(f"⚠️ Ошибка при проверке крафта: {e}")
    return None


def repeat_craft_if_ready(page):
    """
    Если крафт готов — нажимает "Повторить".
    Вызывать на странице города перед входом в данжены.
    Возвращает True если крафт был перезапущен.
    """
    repeat_btn = check_craft_ready(page)
    if not repeat_btn:
        return False

    log("⚒️ Крафт готов! Нажимаем 'Повторить'...")

    if safe_click_element(repeat_btn):
        log("✅ Крафт перезапущен!")
        antibot_delay(1.5, 0.5)
        return True
    else:
        log("⚠️ Не удалось нажать 'Повторить'")
        return False
