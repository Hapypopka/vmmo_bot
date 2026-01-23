# ============================================
# VMMO Mail Module (requests version)
# ============================================
# Сбор предметов и денег из почты
# ============================================

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://vmmo.vten.ru"

# Игнорируемые отправители (сообщения остаются непрочитанными)
IGNORED_SENDERS = [
    "Администрация",
]


class MailClient:
    """Клиент для работы с почтой"""

    def __init__(self, client):
        """
        Args:
            client: VMMOClient instance
        """
        self.client = client
        self.collected_gold = 0
        self.collected_silver = 0
        self.messages_processed = 0

    def has_mail_notification(self):
        """Проверяет наличие уведомления о почте"""
        soup = self.client.soup()
        if not soup:
            return False

        # Ищем значок почты с уведомлением
        mail_icon = soup.select_one("span.navigator._mail")
        if mail_icon:
            # Проверяем title или класс уведомления
            title = mail_icon.get("title", "")
            if "Письмо" in title or "письм" in title.lower():
                return True
        return False

    def open_mailbox(self):
        """Открывает почту"""
        resp = self.client.get("/message/list")
        return resp.status_code == 200

    def find_active_messages(self):
        """
        Находит активные (непрочитанные) письма.
        Игнорирует письма от отправителей из IGNORED_SENDERS.

        Returns:
            list: Список словарей с информацией о письмах
        """
        soup = self.client.soup()
        if not soup:
            return []

        messages = []
        # Ищем все письма
        for link in soup.select("a.task-section._label.brass"):
            # Пропускаем прочитанные (с классом c-verygray)
            classes = link.get("class", [])
            if "c-verygray" in classes:
                continue

            href = link.get("href")
            if not href:
                continue

            # Проверяем отправителя - первый span содержит имя
            sender_span = link.select_one("span")
            if sender_span:
                sender = sender_span.get_text(strip=True)
                # Пропускаем игнорируемых отправителей
                if sender in IGNORED_SENDERS:
                    print(f"[MAIL] Пропускаю письмо от '{sender}'")
                    continue

            # Получаем текст письма
            text = link.get_text(strip=True)
            messages.append({
                "text": text,
                "url": urljoin(BASE_URL, href),
            })

        return messages

    def parse_mail_money(self):
        """
        Парсит деньги из текущего открытого письма.

        Returns:
            tuple: (gold, silver)
        """
        soup = self.client.soup()
        if not soup:
            return 0, 0

        gold = 0
        silver = 0

        # Ищем блок с деньгами
        for div in soup.select("div.p2"):
            text = div.get_text()
            if "Деньги:" not in text:
                continue

            # Золото
            gold_span = div.select_one("span.i12-money_gold, span.i12.i12-money_gold")
            if gold_span:
                # Число может быть в соседнем span или в родителе
                parent = gold_span.parent
                if parent:
                    match = re.search(r'(\d[\d\s]*)', parent.get_text())
                    if match:
                        gold = int(match.group(1).replace(" ", ""))

            # Серебро
            silver_span = div.select_one("span.i12-money_silver, span.i12.i12-money_silver")
            if silver_span:
                parent = silver_span.parent
                if parent:
                    match = re.search(r'(\d[\d\s]*)', parent.get_text())
                    if match:
                        silver = int(match.group(1).replace(" ", ""))

        return gold, silver

    def check_backpack_full(self):
        """
        Проверяет, полон ли рюкзак.

        Returns:
            bool: True если рюкзак полон
        """
        soup = self.client.soup()
        if not soup:
            return False

        # Проверяем попап о переполнении
        notice = soup.select_one("div.notice-rich3")
        if notice:
            text = notice.get_text()
            if "рюкзаке нет места" in text or "нет места" in text.lower():
                return True

        # Проверяем счетчик рюкзака (28/28)
        counter = soup.select_one("span.sp_rack_count")
        if counter:
            text = counter.get_text(strip=True)
            match = re.match(r'(\d+)/(\d+)', text)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                if current >= total:
                    return True

        return False

    def collect_message_items(self):
        """
        Забирает предметы из текущего открытого письма.

        Returns:
            str: "success", "backpack_full", или "error"
        """
        soup = self.client.soup()
        if not soup:
            return "error"

        # Ищем кнопку "Забрать и удалить"
        collect_btn = None
        for btn in soup.select("a.btn.nav-btn"):
            text = btn.get_text()
            if "Забрать" in text and "удалить" in text.lower():
                collect_btn = btn
                break

        if not collect_btn:
            # Может просто кнопка удаления без предметов
            for btn in soup.select("a.btn.nav-btn"):
                text = btn.get_text()
                if "Удалить" in text:
                    collect_btn = btn
                    break

        if not collect_btn:
            print("[MAIL] Кнопка сбора не найдена")
            return "error"

        href = collect_btn.get("href")
        if not href:
            return "error"

        # Кликаем кнопку
        url = urljoin(self.client.current_url, href)
        self.client.get(url)

        # Проверяем результат
        if self.check_backpack_full():
            return "backpack_full"

        return "success"

    def extract_expired_item_name(self, msg_text):
        """
        Извлекает название предмета из сообщения об истекшем лоте.

        Args:
            msg_text: Текст сообщения

        Returns:
            str or None: Название предмета
        """
        match = re.search(r'истёк\.\s*\(([^)]+)\)', msg_text)
        if match:
            return match.group(1)
        return None

    def process_mailbox(self, on_backpack_full=None):
        """
        Обрабатывает все письма в почте.
        Игнорирует письма от IGNORED_SENDERS.

        Args:
            on_backpack_full: Callback при переполнении рюкзака

        Returns:
            dict: Статистика {messages, gold, silver, expired_items}
        """
        stats = {
            "messages": 0,
            "gold": 0,
            "silver": 0,
            "expired_items": [],
        }

        if not self.open_mailbox():
            print("[MAIL] Не удалось открыть почту")
            return stats

        max_iterations = 50  # Защита от бесконечного цикла

        for _ in range(max_iterations):
            messages = self.find_active_messages()
            if not messages:
                break

            # Берём первое письмо
            msg = messages[0]
            print(f"[MAIL] Открываю: {msg['text'][:50]}...")

            # Проверяем истекший лот
            if "Срок твоего лота истёк" in msg["text"]:
                item_name = self.extract_expired_item_name(msg["text"])
                if item_name:
                    stats["expired_items"].append(item_name)
                    print(f"[MAIL] Истекший лот: {item_name}")

            # Открываем письмо
            self.client.get(msg["url"])

            # Парсим деньги
            gold, silver = self.parse_mail_money()
            if gold or silver:
                stats["gold"] += gold
                stats["silver"] += silver
                print(f"[MAIL] Деньги: {gold}g {silver}s")

            # Забираем предметы
            result = self.collect_message_items()

            if result == "backpack_full":
                print("[MAIL] Рюкзак полон!")
                if on_backpack_full:
                    # Вызываем callback для очистки рюкзака
                    on_backpack_full()
                    # После очистки снова открываем почту и продолжаем
                    self.open_mailbox()
                    continue
                else:
                    break

            elif result == "success":
                stats["messages"] += 1
                # После сбора нас редиректит обратно в список, продолжаем

            else:
                print(f"[MAIL] Ошибка сбора письма")
                # Пробуем вернуться в список
                self.open_mailbox()

        self.collected_gold += stats["gold"]
        self.collected_silver += stats["silver"]
        self.messages_processed += stats["messages"]

        if stats["messages"] > 0:
            print(f"[MAIL] Готово: {stats['messages']} писем, {stats['gold']}g {stats['silver']}s")
        return stats

    def check_and_collect(self, on_backpack_full=None):
        """
        Основная функция - проверяет почту и собирает всё.

        Args:
            on_backpack_full: Callback при переполнении рюкзака

        Returns:
            dict: Статистика сбора
        """
        return self.process_mailbox(on_backpack_full)


def test_mail(client):
    """Тест модуля почты"""
    print("=" * 50)
    print("VMMO Mail Test")
    print("=" * 50)

    mail = MailClient(client)

    # Проверяем уведомление
    client.get("/city")
    has_mail = mail.has_mail_notification()
    print(f"[*] Есть уведомление о почте: {has_mail}")

    # Открываем почту
    print("\n[*] Открываю почту...")
    if mail.open_mailbox():
        messages = mail.find_active_messages()
        print(f"[*] Найдено активных писем: {len(messages)}")

        for msg in messages[:5]:  # Первые 5
            print(f"  - {msg['text'][:60]}...")

        # Собираем
        if messages:
            print("\n[*] Собираю письма...")
            stats = mail.check_and_collect()
            print(f"\n[RESULT] Собрано:")
            print(f"  Писем: {stats['messages']}")
            print(f"  Золото: {stats['gold']}")
            print(f"  Серебро: {stats['silver']}")
            if stats['expired_items']:
                print(f"  Истекшие лоты: {stats['expired_items']}")
    else:
        print("[ERR] Не удалось открыть почту")


if __name__ == "__main__":
    from .client import VMMOClient

    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            exit(1)

    test_mail(client)
