# ============================================
# VMMO Pets Module (requests version)
# ============================================
# Воскрешение питомцев после смерти
# ============================================

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://m.vten.ru"


class PetClient:
    """Клиент для работы с питомцами"""

    def __init__(self, client):
        """
        Args:
            client: VMMOClient instance
        """
        self.client = client
        self.pets_resurrected = 0

    def get_user_id(self):
        """
        Получает ID пользователя из текущей страницы.

        Returns:
            str or None: ID пользователя
        """
        html = self.client.current_page
        if not html:
            return None

        # Ищем ptxUserId в JavaScript
        match = re.search(r"ptxUserId\s*=\s*['\"](\d+)['\"]", html)
        if match:
            return match.group(1)

        # Альтернатива - ищем в URL профиля
        match = re.search(r"/user/(\d+)", html)
        if match:
            return match.group(1)

        return None

    def open_pets_page(self):
        """
        Открывает страницу питомцев.

        Returns:
            bool: True если успешно
        """
        user_id = self.get_user_id()
        if not user_id:
            # Пробуем загрузить любую страницу для получения user_id
            self.client.get("/city")
            user_id = self.get_user_id()

        if not user_id:
            print("[PETS] Не удалось получить ID пользователя")
            return False

        resp = self.client.get(f"/user/pets/{user_id}")
        return resp.status_code == 200

    def find_resurrect_button(self):
        """
        Ищет кнопку воскрешения активного питомца.

        Returns:
            str or None: URL кнопки воскрешения
        """
        soup = self.client.soup()
        if not soup:
            return None

        # Ищем кнопку "Оживить" с aliveLink
        for link in soup.select("a.btn.nav-btn"):
            href = link.get("href", "")
            text = link.get_text()

            if "aliveBlock-aliveLink" in href and "Оживить" in text:
                return urljoin(BASE_URL, href)

        return None

    def is_pet_dead(self):
        """
        Проверяет, мёртв ли активный питомец.

        Returns:
            bool: True если питомец мёртв
        """
        if not self.open_pets_page():
            return False

        return self.find_resurrect_button() is not None

    def resurrect_pet(self):
        """
        Воскрешает активного питомца.

        Returns:
            bool: True если успешно воскресили
        """
        if not self.open_pets_page():
            print("[PETS] Не удалось открыть страницу питомцев")
            return False

        resurrect_url = self.find_resurrect_button()
        if not resurrect_url:
            # Питомец жив
            return False

        print("[PETS] Питомец мёртв, воскрешаю...")
        resp = self.client.get(resurrect_url)

        if resp.status_code == 200:
            # Проверяем что кнопки больше нет
            new_resurrect_url = self.find_resurrect_button()
            if new_resurrect_url is None:
                print("[PETS] Питомец воскрешён!")
                self.pets_resurrected += 1
                return True
            else:
                print("[PETS] Не удалось воскресить питомца")
                return False

        print(f"[PETS] Ошибка воскрешения: {resp.status_code}")
        return False

    def check_and_resurrect(self):
        """
        Проверяет и воскрешает питомца если нужно.

        Returns:
            bool: True если питомец был воскрешён
        """
        if not self.open_pets_page():
            return False

        resurrect_url = self.find_resurrect_button()
        if resurrect_url:
            return self.resurrect_pet()

        return False


def test_pets(client):
    """Тест модуля питомцев"""
    print("=" * 50)
    print("VMMO Pets Test")
    print("=" * 50)

    pets = PetClient(client)

    # Получаем user_id
    client.get("/city")
    user_id = pets.get_user_id()
    print(f"[*] User ID: {user_id}")

    # Проверяем питомца
    print("\n[*] Проверяю питомца...")
    if pets.is_pet_dead():
        print("[*] Питомец мёртв!")
        print("[*] Воскрешаю...")
        if pets.resurrect_pet():
            print("[*] Питомец воскрешён!")
        else:
            print("[*] Не удалось воскресить")
    else:
        print("[*] Питомец жив")


if __name__ == "__main__":
    from .client import VMMOClient

    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            exit(1)

    test_pets(client)
