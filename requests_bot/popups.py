# ============================================
# VMMO Popups & Widgets (requests version)
# ============================================
# Закрытие попапов, сбор лута, обработка виджетов
# ============================================

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://vmmo.vten.ru"
DUNGEONS_URL = f"{BASE_URL}/dungeons?52"


class PopupsClient:
    """Клиент для обработки попапов и виджетов"""

    def __init__(self, client):
        self.client = client

    def close_achievement_popup(self):
        """
        Закрывает попап достижения.
        Возвращает True если попап был закрыт.
        """
        soup = self.client.soup()
        if not soup:
            return False

        # Ищем крестик закрытия попапа
        close_btn = soup.select_one("a.modal-dialog-close")
        if close_btn:
            href = close_btn.get("href")
            if href:
                url = urljoin(self.client.current_url, href)
                self.client.get(url)
                print("[POPUP] Закрыли попап достижения")
                return True
        return False

    def close_party_widget(self):
        """
        Закрывает виджет приглашения в данжен.
        Возвращает True если виджет был закрыт.
        """
        soup = self.client.soup()
        if not soup:
            return False

        widget = soup.select_one("div.widget")
        if not widget:
            return False

        widget_text = widget.get_text().lower()
        if not any(t in widget_text for t in ["приглашает", "ожидает", "ждёт"]):
            return False

        # Ищем кнопку "Покинуть банду"
        leave_btn = soup.select_one('a.go-btn[href*="leaveParty"]')
        if not leave_btn:
            for btn in soup.select("a.go-btn"):
                text = btn.get_text(strip=True)
                if "Покинуть банду" in text:
                    leave_btn = btn
                    break

        if leave_btn:
            href = leave_btn.get("href")
            if href:
                url = urljoin(self.client.current_url, href)
                self.client.get(url)
                print("[POPUP] Закрыли виджет приглашения")
                return True

        return False

    def handle_party_ready_widget(self):
        """
        Обрабатывает виджет "Банда собрана" - нажимает "В подземелье".
        Возвращает True если виджет был обработан.
        """
        soup = self.client.soup()
        if not soup:
            return False

        widget_desc = soup.select_one("div.widget-description")
        if not widget_desc:
            return False

        if "Банда собрана" not in widget_desc.get_text():
            return False

        # Ищем кнопку "В подземелье"
        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if "В подземелье" in text:
                href = btn.get("href")
                if href:
                    url = urljoin(self.client.current_url, href)
                    self.client.get(url)
                    print("[POPUP] Нажали 'В подземелье'")
                    return True

        return False

    def close_rest_bonus_popup(self):
        """
        Закрывает попап бонуса отдыха.
        Возвращает True если попап был закрыт.
        """
        soup = self.client.soup()
        if not soup:
            return False

        rest_popup = soup.select_one("div.rest-bonus-popup, div.daily-bonus-popup")
        if not rest_popup:
            return False

        # Ищем кнопку "Продолжить"
        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if "Продолжить" in text:
                href = btn.get("href")
                if href:
                    url = urljoin(self.client.current_url, href)
                    self.client.get(url)
                    print("[POPUP] Закрыли попап бонуса отдыха")
                    return True

        return False

    def close_all_popups(self):
        """Закрывает все известные попапы"""
        closed = False
        closed |= self.close_achievement_popup()
        closed |= self.close_party_widget()
        closed |= self.close_rest_bonus_popup()
        closed |= self.handle_party_ready_widget()
        return closed

    def collect_loot(self):
        """
        Собирает лут во время боя.
        Возвращает количество собранного.
        """
        soup = self.client.soup()
        if not soup:
            return 0

        collected = 0
        # Лут появляется как a.combat-loot или div.combat-loot
        loot_items = soup.select("a.combat-loot, div.combat-loot a")

        for loot in loot_items:
            href = loot.get("href")
            if href:
                url = urljoin(self.client.current_url, href)
                self.client.get(url)
                collected += 1

        if collected > 0:
            print(f"[LOOT] Подобрали лут: {collected} шт.")

        return collected

    def check_start_battle_button(self):
        """
        Проверяет наличие кнопки "Начать бой" и нажимает её.
        Возвращает True если кнопка была нажата.
        """
        soup = self.client.soup()
        if not soup:
            return False

        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if "Начать бой" in text:
                href = btn.get("href")
                if href:
                    url = urljoin(self.client.current_url, href)
                    self.client.get(url)
                    print("[POPUP] Нажали 'Начать бой'")
                    return True

        return False

    def check_continue_battle_button(self):
        """
        Проверяет наличие кнопки "Продолжить бой" и нажимает её.
        Возвращает True если кнопка была нажата.
        """
        soup = self.client.soup()
        if not soup:
            return False

        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if "Продолжить бой" in text:
                href = btn.get("href")
                if href:
                    url = urljoin(self.client.current_url, href)
                    self.client.get(url)
                    print("[POPUP] Нажали 'Продолжить бой'")
                    return True

        return False

    def priority_checks(self):
        """
        Приоритетные проверки на каждом шаге цикла.
        Возвращает True если была нажата какая-либо кнопка.
        """
        if self.check_start_battle_button():
            return True
        if self.close_party_widget():
            return True
        return False

    def emergency_unstuck(self):
        """
        Аварийный выход из застревания.
        Пробует нажать различные кнопки для выхода.
        Возвращает True если удалось что-то сделать.
        """
        print("[UNSTUCK] Запуск аварийного выхода...")

        soup = self.client.soup()
        if not soup:
            return self._hard_reset()

        # Приоритетные кнопки
        button_texts = [
            "Продолжить бой",
            "Продолжить",
            "В подземелье",
            "Начать бой",
            "Закрыть",
            "Выйти",
            "Назад",
        ]

        # Опасные кнопки которые не нажимаем
        skip_texts = ["удалить", "купить", "продать", "отмена"]

        for target_text in button_texts:
            for btn in soup.select("a.go-btn"):
                text = btn.get_text(strip=True)
                if target_text in text:
                    # Проверяем на опасные
                    if any(skip in text.lower() for skip in skip_texts):
                        continue
                    href = btn.get("href")
                    if href:
                        url = urljoin(self.client.current_url, href)
                        self.client.get(url)
                        print(f"[UNSTUCK] Нажали: '{text}'")
                        return True

        # Попробуем любую безопасную кнопку
        for btn in soup.select("a.go-btn"):
            text = btn.get_text(strip=True)
            if any(skip in text.lower() for skip in skip_texts):
                continue
            href = btn.get("href")
            if href:
                url = urljoin(self.client.current_url, href)
                self.client.get(url)
                print(f"[UNSTUCK] Нажали любую: '{text}'")
                return True

        return self._hard_reset()

    def _hard_reset(self):
        """Принудительный переход на /dungeons"""
        print("[UNSTUCK] Hard reset на /dungeons")
        self.client.get(DUNGEONS_URL)
        return False


def test_popups():
    """Тест модуля попапов"""
    from requests_bot.client import VMMOClient

    print("=" * 50)
    print("VMMO Popups Test")
    print("=" * 50)

    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            return

    popups = PopupsClient(client)

    # Переходим в город
    client.get("/city")
    print("\n[*] Проверяю попапы на странице города...")

    closed = popups.close_all_popups()
    print(f"[RESULT] Закрыто попапов: {closed}")

    # Переходим в данжены
    client.get(DUNGEONS_URL)
    print("\n[*] Проверяю попапы на странице данженов...")

    if popups.check_start_battle_button():
        print("[INFO] Была кнопка 'Начать бой'")
    else:
        print("[INFO] Кнопки 'Начать бой' нет")

    print("\n[OK] Тест завершён")


if __name__ == "__main__":
    test_popups()
