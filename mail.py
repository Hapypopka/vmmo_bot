# ============================================
# VMMO Bot - Mail Management
# ============================================

import time
from config import DUNGEONS_URL
from utils import antibot_delay, log, safe_click, safe_click_element
from backpack import need_cleanup_backpack, cleanup_backpack_if_needed


def has_mail_notification(page):
    """
    Проверяет, есть ли непрочитанное письмо.
    Ищет <span class="navigator _mail" title="Письмо"></span>
    Возвращает True если есть письма.
    """
    try:
        mail_icon = page.query_selector("span.navigator._mail")
        if mail_icon:
            log("📧 Обнаружено новое письмо")
            return True
    except Exception as e:
        log(f"⚠️ Ошибка при проверке почты: {e}")
    return False


def open_profile(page):
    """
    Открывает профиль игрока.
    Ищет ссылку с классом main-menu-link._profile._18
    Возвращает True если успешно.
    """
    try:
        # Ищем ссылку "Профиль"
        profile_link = page.query_selector("a.main-menu-link._profile._18")
        if not profile_link:
            log("⚠️ Ссылка на профиль не найдена")
            return False

        if safe_click_element(profile_link):
            log("👤 Открыли профиль")
            time.sleep(3)  # Ждём загрузки страницы профиля
            antibot_delay(2.0, 1.0)
            return True
    except Exception as e:
        log(f"⚠️ Ошибка при открытии профиля: {e}")
    return False


def open_mailbox(page):
    """
    Открывает почтовый ящик из профиля.
    Ищет div.side-bar-item-c с текстом "Почта"
    Возвращает True если успешно.
    """
    try:
        # Ищем все элементы сайдбара
        sidebar_items = page.query_selector_all("div.side-bar-item-c")

        for item in sidebar_items:
            try:
                # Проверяем текст элемента
                text = item.inner_text()
                if "Почта" in text:
                    # Нашли нужный элемент — кликаем через dispatch_event
                    log("📧 Нашли кнопку почты, кликаем...")
                    item.dispatch_event("click")
                    time.sleep(2)  # Ждём навигации

                    # Проверяем, перешли ли на страницу почты
                    current_url = page.url.lower()
                    log(f"🔗 URL после клика: {current_url}")

                    if "/message/list" in current_url:
                        log("📬 Открыли почтовый ящик")
                        time.sleep(2)  # Ждём загрузки списка сообщений
                        antibot_delay(2.0, 1.0)
                        return True
                    else:
                        # Клик не сработал — делаем прямой переход
                        log("⚠️ Клик не сработал, делаем прямой переход...")
                        page.goto("https://vmmo.vten.ru/message/list")
                        time.sleep(3)
                        antibot_delay(2.0, 1.0)
                        log("📬 Открыли почтовый ящик (через goto)")
                        return True

            except Exception as e2:
                log(f"⚠️ Ошибка при клике на почту: {e2}")
                continue

        log("⚠️ Кнопка почты не найдена в сайдбаре")
        return False
    except Exception as e:
        log(f"⚠️ Ошибка при открытии почты: {e}")
    return False


def find_active_messages(page):
    """
    Ищет все активные (непрочитанные) сообщения.
    Активные = без класса c-verygray
    Возвращает список элементов <a class="task-section _label brass">
    """
    try:
        # Ждём появления сообщений на странице
        try:
            page.wait_for_selector("a.task-section._label.brass", timeout=5000)
        except:
            log("⚠️ Сообщения не загрузились за 5 секунд")

        messages = page.query_selector_all("a.task-section._label.brass")
        active_messages = []

        for msg in messages:
            # Проверяем, что нет класса c-verygray
            class_attr = msg.get_attribute("class")
            if class_attr and "c-verygray" not in class_attr:
                active_messages.append(msg)

        log(f"📧 Найдено активных сообщений: {len(active_messages)}")
        return active_messages
    except Exception as e:
        log(f"⚠️ Ошибка при поиске сообщений: {e}")
    return []


def collect_message_items(page):
    """
    Забирает предметы из текущего открытого сообщения.
    Нажимает на кнопку "Забрать и удалить сообщение".
    Обрабатывает попап "В твоем рюкзаке нет места".
    Возвращает True если успешно, "backpack_full" если рюкзак полон.
    """
    try:
        # Ищем кнопку "Забрать и удалить сообщение"
        buttons = page.query_selector_all("a.btn.nav-btn")
        collect_btn = None

        for btn in buttons:
            text = btn.inner_text().strip()
            if "Забрать и удалить" in text:
                collect_btn = btn
                break

        if not collect_btn:
            log("⚠️ Кнопка 'Забрать и удалить' не найдена")
            return False

        # Кликаем на кнопку
        if not safe_click_element(collect_btn):
            return False

        log("📦 Нажали 'Забрать и удалить сообщение'")
        antibot_delay(1.5, 0.5)

        # Проверяем, не появился ли попап о полном рюкзаке
        try:
            # Ждём либо попап, либо переход на другую страницу
            time.sleep(2)

            # Проверяем попап "В твоем рюкзаке нет места"
            popup = page.query_selector("div.notice-rich3")
            if popup:
                popup_text = popup.inner_text()
                if "рюкзаке нет места" in popup_text:
                    log("⚠️ Рюкзак полон — нужна очистка")
                    return "backpack_full"

            # Проверяем счётчик рюкзака
            count_el = page.query_selector("span.sp_rack_count")
            if count_el:
                text = count_el.inner_text().strip()
                if "28/28" in text:
                    log("⚠️ Рюкзак полон (28/28)")
                    return "backpack_full"

            log("✅ Предметы забраны из сообщения")
            return True

        except Exception as e:
            log(f"⚠️ Ошибка при проверке результата: {e}")
            return False

    except Exception as e:
        log(f"⚠️ Ошибка при заборе предметов: {e}")
    return False


def process_mailbox(page):
    """
    Обрабатывает все активные сообщения в почтовом ящике.
    Забирает предметы из каждого сообщения.
    Если рюкзак полон — очищает его и продолжает.
    Возвращает количество обработанных сообщений.
    """
    processed_count = 0
    max_messages = 20  # Защита от бесконечного цикла

    while processed_count < max_messages:
        # Открываем почтовый ящик (возвращаемся к списку после каждого сообщения)
        if processed_count > 0:
            # Возвращаемся на страницу почты
            try:
                page.goto("https://vmmo.vten.ru/message/list")
                time.sleep(2)
                antibot_delay(1.0, 0.5)
            except Exception as e:
                log(f"⚠️ Не удалось вернуться в почту: {e}")
                break

        # Ищем активные сообщения
        active_messages = find_active_messages(page)
        if not active_messages:
            log("✅ Нет активных сообщений")
            break

        # Берём первое активное сообщение
        first_message = active_messages[0]

        # Получаем текст сообщения для лога
        try:
            msg_text = first_message.inner_text().strip()
            # Обрезаем длинный текст
            if len(msg_text) > 60:
                msg_text = msg_text[:60] + "..."
            log(f"📧 Обрабатываем: {msg_text}")
        except:
            pass

        # Кликаем на сообщение
        if not safe_click_element(first_message):
            log("⚠️ Не удалось открыть сообщение")
            break

        antibot_delay(2.0, 1.0)

        # Забираем предметы
        result = collect_message_items(page)

        if result == "backpack_full":
            # Рюкзак полон — очищаем
            log("🎒 Очищаем рюкзак перед продолжением...")
            cleanup_backpack_if_needed(page)

            # Возвращаемся на страницу почты и открываем сообщение
            try:
                page.goto("https://vmmo.vten.ru/message/list")
                time.sleep(2)
                antibot_delay(1.0, 0.5)
            except Exception as e:
                log(f"⚠️ Не удалось вернуться в почту: {e}")
                break

            # Снова ищем и открываем первое активное сообщение
            active_messages = find_active_messages(page)
            if not active_messages:
                break

            if not safe_click_element(active_messages[0]):
                break

            antibot_delay(2.0, 1.0)

            # Пробуем забрать ещё раз
            result = collect_message_items(page)
            if result == "backpack_full":
                log("⚠️ Рюкзак всё ещё полон после очистки")
                break

        if result:
            processed_count += 1
        else:
            # Не удалось забрать — пропускаем это сообщение
            log("⚠️ Пропускаем сообщение")
            break

        antibot_delay(1.0, 0.5)

    log(f"📧 Обработано сообщений: {processed_count}")
    return processed_count


def check_and_collect_mail(page):
    """
    Главная функция: проверяет почту и забирает предметы из писем.
    Вызывать после очистки рюкзака в main loop.
    Возвращает True если были обработаны письма.
    """
    # Проверяем наличие уведомления о письме
    if not has_mail_notification(page):
        return False

    log("📬 Начинаем обработку почты...")

    # Сразу переходим на страницу почты (клики не работают)
    try:
        page.goto("https://vmmo.vten.ru/message/list")
        time.sleep(3)
        antibot_delay(2.0, 1.0)
        log("📬 Открыли почтовый ящик")
    except Exception as e:
        log(f"⚠️ Не удалось открыть почту: {e}")
        return False

    # Обрабатываем все сообщения
    processed = process_mailbox(page)

    # Возвращаемся в подземелья
    try:
        page.goto(DUNGEONS_URL)
        time.sleep(3)
        antibot_delay(1.0, 1.0)
        log("🏰 Вернулись в подземелья после обработки почты")
    except Exception as e:
        log(f"⚠️ Ошибка при возврате в подземелья: {e}")

    return processed > 0
