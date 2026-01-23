# ============================================
# VMMO Character Creator
# ============================================
# Автоматическое создание персонажа
#
# Полный поток создания:
# 1. Главная -> "Начать игру" -> /training/battle (лоадер)
# 2. Извлекаем функцию ppt() и аргумент из HTML
# 3. Выполняем ppt(arg) через node.js -> получаем ppKey
# 4. Вызываем ppAction=go&ppKey=... -> получаем urlStart
# 5. Вызываем urlStart + параметры -> персонаж создан -> таверна
# ============================================
#
# Параметры URL для создания персонажа:
# - ppAction=select - действие создания
# - sex=m/f - пол (m=мужской, f=женский)
# - side=1/2 - сторона (1=свет, 2=тьма)
# - type=1/2/3 - класс (1=Маг, 2=Монах, 3=Воин)
#
# Пример: /user/customize?ppAction=select&sex=m&side=1&type=1
# ============================================

import re
import subprocess
from bs4 import BeautifulSoup

from requests_bot.client import VMMOClient
from requests_bot.config import BASE_URL


# Классы персонажей
# type=1 -> Маг, type=2 -> Монах, type=3 -> Воин
CHARACTER_CLASSES = {
    "Маг": 1,
    "Монах": 2,
    "Воин": 3,
}

# Стороны
SIDES = {
    "свет": 1,
    "тьма": 2,
}

# Пол
GENDERS = {
    "м": "m",
    "ж": "f",
    "male": "m",
    "female": "f",
}


class CharacterCreator:
    """Автоматическое создание нового персонажа"""

    def __init__(self, client: VMMOClient = None):
        self.client = client or VMMOClient()

    def create_character(
        self,
        target_class: str = "Маг",
        gender: str = "м",
        side: str = "свет",
        run_tutorial: bool = True
    ) -> bool:
        """
        Создаёт нового персонажа выбранного класса.

        Args:
            target_class: Название класса ("Маг", "Монах", "Воин")
            gender: Пол ("м"/"ж" или "male"/"female")
            side: Сторона ("свет"/"тьма")
            run_tutorial: Запустить туториал после создания

        Returns:
            bool: True если персонаж успешно создан
        """
        print(f"[CREATE] Создание персонажа: {target_class}, пол={gender}, сторона={side}")

        self._character_already_created = False

        # Шаг 1: Переходим на главную страницу
        if not self._go_to_landing():
            return False

        # Шаг 2: Нажимаем "Начать игру"
        if not self._click_start_game():
            return False

        # Шаг 3: Создаём персонажа (только если ещё не создан)
        if not self._character_already_created:
            if not self._create_with_params(target_class, gender, side):
                return False
            print(f"[CREATE] Персонаж {target_class} успешно создан!")
        else:
            print(f"[CREATE] Персонаж уже был создан ранее, пропускаем создание")

        # Шаг 4: Проходим туториал если нужно
        if run_tutorial:
            print("[CREATE] Запускаю туториал...")
            try:
                from requests_bot.tutorial import TutorialRunner
                tutorial = TutorialRunner(self.client)
                tutorial.run_tutorial()
            except Exception as e:
                print(f"[CREATE] Ошибка туториала: {e}")
                import traceback
                traceback.print_exc()
                # Туториал опционален, продолжаем

        return True

    def _go_to_landing(self) -> bool:
        """Переходит на главную страницу"""
        print("[CREATE] Шаг 1: Переход на главную страницу...")

        resp = self.client.get(BASE_URL)
        if not resp:
            print("[CREATE] Ошибка загрузки главной страницы")
            return False

        print(f"[CREATE] URL: {self.client.current_url}")

        # Проверяем что мы на странице входа/регистрации
        if "/entrance" not in self.client.current_url and "m.vten.ru" not in self.client.current_url:
            print(f"[CREATE] Неожиданный URL: {self.client.current_url}")
            # Всё равно пробуем продолжить

        return True

    def _click_start_game(self) -> bool:
        """Нажимает кнопку 'Начать игру'"""
        print("[CREATE] Шаг 2: Нажимаем 'Начать игру'...")

        html = self.client.current_page
        if not html:
            print("[CREATE] Страница не загружена")
            return False

        # Ищем ссылку "Начать игру" с классом landing-btn-start
        soup = BeautifulSoup(html, "html.parser")

        # Вариант 1: Ищем по классу (может быть в списке классов)
        start_btn = None
        for a in soup.find_all("a", href=True):
            classes = a.get("class", [])
            href = a.get("href", "")
            if "landing-btn-start" in classes or "entrance/start" in href:
                start_btn = a
                break

        # Вариант 2: Ищем по тексту
        if not start_btn:
            start_btn = soup.find("a", string=lambda s: s and "Начать игру" in s)

        if not start_btn:
            print("[CREATE] Кнопка 'Начать игру' не найдена")
            # Выводим все ссылки для дебага
            print("[CREATE] Доступные ссылки:")
            for a in soup.find_all("a", href=True)[:10]:
                print(f"  - {a.get('class', [])}: {a.get('href', '')[:60]}")
            return False

        href = start_btn.get("href")
        if not href:
            print("[CREATE] У кнопки нет href")
            return False

        print(f"[CREATE] Найдена кнопка: {href[:80]}...")

        # Переходим по ссылке
        resp = self.client.get(href)
        if not resp:
            print("[CREATE] Ошибка перехода по ссылке")
            return False

        print(f"[CREATE] Перешли на: {self.client.current_url}")

        new_html = self.client.current_page or ""

        # ВАЖНО: URL может быть /training/battle, но контент - страница выбора класса!
        # Проверяем по КОНТЕНТУ, а не по URL!

        # Проверяем наличие Vue компонента customize или urlStart - это страница ВЫБОРА класса
        if "Ptx.Shadows.Tutor.urlStart" in new_html or "customize.js" in new_html or "customize.css" in new_html:
            print("[CREATE] Успешно перешли на страницу выбора класса (определено по контенту)")
            self._character_already_created = False
            return True

        # Проверяем URL /customize
        if "/customize" in self.client.current_url:
            print("[CREATE] URL указывает на страницу выбора класса")
            self._character_already_created = False
            return True

        # Если есть признаки Таверны - персонаж УЖЕ создан
        if "Ptx.Shadows.Ui.Tavern" in new_html or "tavern.js" in new_html or "Таверна" in new_html:
            print("[CREATE] Персонаж уже создан! Находимся в Таверне (определено по контенту)")
            self._character_already_created = True
            return True

        # Проверяем URL /tavern
        if "/tavern" in self.client.current_url:
            print("[CREATE] Персонаж уже создан! URL указывает на Таверну")
            self._character_already_created = True
            return True

        print("[CREATE] Неизвестная страница после нажатия 'Начать игру'")
        self._character_already_created = False
        return True  # Пробуем продолжить

    def _create_with_params(self, target_class: str, gender: str, side: str) -> bool:
        """
        Создаёт персонажа через полный поток с динамическим ppKey.

        Поток:
        1. Извлекаем функцию ppt() и аргумент из HTML
        2. Выполняем ppt через node.js -> получаем ppKey
        3. Вызываем ppAction=go&ppKey=... -> получаем urlStart
        4. Вызываем urlStart + параметры -> персонаж создан
        """
        print(f"[CREATE] Шаг 3: Создание персонажа с параметрами...")

        # Получаем числовые значения
        class_type = CHARACTER_CLASSES.get(target_class)
        if not class_type:
            print(f"[CREATE] Неизвестный класс: {target_class}")
            print(f"[CREATE] Доступные классы: {list(CHARACTER_CLASSES.keys())}")
            return False

        gender_param = GENDERS.get(gender.lower(), "m")
        side_param = SIDES.get(side.lower(), 1)

        html = self.client.current_page or ""

        # Шаг 3.1: Проверяем - может urlStart уже есть?
        url_start_match = re.search(r"Ptx\.Shadows\.Tutor\.urlStart\s*=\s*'([^']+)'", html)
        if url_start_match:
            url_start = url_start_match.group(1)
            print(f"[CREATE] urlStart уже есть: {url_start}")
        else:
            # Шаг 3.2: Нужно пройти через ppAction=go чтобы получить urlStart
            print("[CREATE] urlStart не найден, нужно пройти через ppAction=go...")
            url_start = self._get_url_start_via_ppkey(html)
            if not url_start:
                return False

        # Шаг 3.3: Создаём персонажа
        create_url = f"{url_start}&sex={gender_param}&side={side_param}&type={class_type}"
        print(f"[CREATE] URL создания: {create_url}")

        # Заголовки как в SPA
        headers = {
            'Accept': 'text/html',
            'ptxSPA': 'true',
            'Referer': self.client.current_url or f"{BASE_URL}/training/battle",
        }

        resp = self.client.session.get(create_url, headers=headers)
        if not resp:
            print("[CREATE] Ошибка запроса создания персонажа")
            return False

        # Обновляем состояние клиента
        self.client.current_page = resp.text
        self.client.current_url = str(resp.url)

        print(f"[CREATE] Ответ URL: {self.client.current_url}")

        # Проверяем результат
        return self._check_creation_result()

    def _get_url_start_via_ppkey(self, html: str) -> str | None:
        """
        Получает urlStart через ppAction=go с динамическим ppKey.

        Функция ppt() генерируется сервером с разными константами
        для каждой сессии, поэтому нужно выполнять её через node.js.
        """
        # Ищем функцию ppt и аргумент
        ppt_match = re.search(r'(function ppt\(key\)\s*\{[^}]+\})', html)
        arg_match = re.search(r'\+ ppt\(([^)]+)\)', html)

        if not ppt_match or not arg_match:
            print("[CREATE] Функция ppt или аргумент не найдены в HTML")
            return None

        ppt_func = ppt_match.group(1)
        ppt_arg = arg_match.group(1)

        # Убираем console.log из функции
        ppt_func = re.sub(r"console\.log\([^)]+\);", '', ppt_func)

        print(f"[CREATE] Аргумент ppt: {ppt_arg}")

        # Выполняем через node.js
        js_code = f'{ppt_func}\nconsole.log(ppt({ppt_arg}));'

        try:
            result = subprocess.run(
                ['node', '-e', js_code],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                print(f"[CREATE] Node.js ошибка: {result.stderr}")
                return None

            ppkey = result.stdout.strip()
            print(f"[CREATE] Вычисленный ppKey: {ppkey}")

        except FileNotFoundError:
            print("[CREATE] Node.js не найден! Установите Node.js для создания персонажей.")
            return None
        except subprocess.TimeoutExpired:
            print("[CREATE] Таймаут выполнения node.js")
            return None

        # Вызываем ppAction=go с ppKey
        proceed_url = f"{BASE_URL}/training/battle?ppAction=go&ppKey={ppkey}"
        print(f"[CREATE] URL ppAction=go: {proceed_url}")

        headers = {
            'Accept': 'text/html',
            'ptxSPA': 'true',
            'Referer': self.client.current_url or f"{BASE_URL}/training/battle",
        }

        resp = self.client.session.get(proceed_url, headers=headers)
        if not resp:
            print("[CREATE] Ошибка запроса ppAction=go")
            return None

        self.client.current_page = resp.text
        self.client.current_url = str(resp.url)

        print(f"[CREATE] После ppAction=go URL: {self.client.current_url}")

        # Теперь ищем urlStart
        url_start_match = re.search(
            r"Ptx\.Shadows\.Tutor\.urlStart\s*=\s*'([^']+)'",
            self.client.current_page
        )

        if url_start_match:
            url_start = url_start_match.group(1)
            print(f"[CREATE] urlStart получен: {url_start}")
            return url_start

        # Проверяем ошибки
        if "404" in str(self.client.current_url):
            print("[CREATE] Ошибка 404 - неверный ppKey?")
        elif "accessDenied" in self.client.current_page:
            print("[CREATE] accessDenied")

        print("[CREATE] urlStart не найден после ppAction=go")
        return None

    def _check_creation_result(self) -> bool:
        """Проверяет успешность создания персонажа"""
        url = self.client.current_url or ""
        html = self.client.current_page or ""

        # ВАЖНО: Проверяем по КОНТЕНТУ, не по URL!
        # После создания персонажа мы попадаем в ТАВЕРНУ, не в бой!

        # Проверяем признаки Таверны - персонаж создан!
        if "Ptx.Shadows.Ui.Tavern" in html or "tavern.js" in html:
            print("[CREATE] В Таверне - персонаж создан! (определено по контенту)")
            return True

        # Также проверяем title страницы
        if "Таверна" in html:
            print("[CREATE] В Таверне - персонаж создан! (по title)")
            return True

        # Запасной вариант - проверяем URL /tavern
        if "/tavern" in url:
            print("[CREATE] URL указывает на Таверну - персонаж создан!")
            return True

        if "/city" in url:
            print("[CREATE] Попали в город - персонаж создан!")
            return True

        # Проверяем ошибки
        soup = BeautifulSoup(html, "html.parser")
        error = soup.find("span", class_="feedbackPanelERROR")
        if error:
            error_text = error.get_text(strip=True)
            print(f"[CREATE] Ошибка сервера: {error_text}")
            return False

        # Если есть customize.js/css - всё ещё на странице выбора
        if "customize.js" in html or "Ptx.Shadows.Tutor.urlStart" in html:
            print("[CREATE] Всё ещё на странице выбора класса (определено по контенту)")
            return False

        print(f"[CREATE] Неопределённый результат, URL: {url}")
        # Возвращаем True если нет явных ошибок
        return True

    def get_current_class(self) -> str | None:
        """Получает название текущего выбранного класса со страницы"""
        html = self.client.current_page
        if not html:
            return None

        # Ищем span с классом customize-roleName
        soup = BeautifulSoup(html, "html.parser")
        role_name = soup.find("span", class_="customize-roleName")

        if role_name:
            return role_name.get_text(strip=True)

        # Альтернативный поиск через regex
        match = re.search(r'customize-roleName[^>]*>([^<]+)<', html)
        if match:
            return match.group(1).strip()

        return None


def test_character_creator():
    """Тест создания персонажа"""
    print("=" * 50)
    print("VMMO Character Creator Test")
    print("=" * 50)

    creator = CharacterCreator()

    # Тест: Создаём мага (мужчина, сторона света)
    success = creator.create_character(
        target_class="Маг",
        gender="м",
        side="свет"
    )

    if success:
        print("\n[OK] Персонаж создан успешно!")
    else:
        print("\n[FAIL] Ошибка создания персонажа")

    return success


if __name__ == "__main__":
    test_character_creator()
