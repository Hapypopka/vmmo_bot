# ============================================
# VMMO Requests Client
# ============================================
# HTTP клиент для VMMO на requests
# + WebSocket для сбора лута
# ============================================

import requests
import re
import json
import os
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

from requests_bot.config import (
    BASE_URL, SCRIPT_DIR, SETTINGS_FILE, DEFAULT_HEADERS, AJAX_HEADERS
)
import requests_bot.config as config  # Для динамического доступа к COOKIES_FILE

# Максимум попыток при обновлении сервера
SERVER_UPDATE_MAX_RETRIES = 30
SERVER_UPDATE_RETRY_DELAY = 10  # секунд

class VMMOClient:
    """HTTP клиент для VMMO на requests"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.current_page = None  # Последний загруженный HTML
        self.current_url = None
        self.base_url = BASE_URL  # Для использования в других модулях


    def load_cookies(self, cookies_path=None):
        """Загружает куки из файла (формат Playwright)"""
        if cookies_path is None:
            cookies_path = config.COOKIES_FILE  # Динамически берём из config

        print(f"[CLIENT] Loading cookies from: {cookies_path}")

        try:
            with open(cookies_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            # Конвертируем из Playwright формата в requests
            for cookie in cookies:
                # Пропускаем куки для других доменов (yandex и т.п.)
                domain = cookie.get("domain", "")
                if "vmmo" not in domain and "vten" not in domain:
                    continue

                self.session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=domain.lstrip("."),
                    path=cookie.get("path", "/"),
                )
            print(f"[OK] Loaded {len(self.session.cookies)} cookies")
            return True
        except FileNotFoundError:
            print("[INFO] No cookies file found")
            return False
        except Exception as e:
            print(f"[ERR] Load cookies error")
            return False

    def get(self, url, max_retries=3, **kwargs):
        """GET запрос с сохранением страницы и автоматическим retry"""
        if not url:
            print("[ERR] GET called with empty URL")
            return None
        if not url.startswith("http"):
            url = urljoin(BASE_URL, url)

        # Устанавливаем таймаут по умолчанию
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 30

        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, **kwargs)
                self.current_page = resp.text
                self.current_url = resp.url

                # Проверяем страницу "обновление сервера"
                resp = self._handle_server_update(resp, url, **kwargs)
                return resp

            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 sec
                    print(f"[CLIENT] GET {url[:50]}... failed ({e.__class__.__name__}), retry in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    print(f"[ERR] GET {url[:50]}... failed after {max_retries} attempts: {e}")
                    raise

        return None

    def _handle_server_update(self, resp, original_url, method="get", **kwargs):
        """Обрабатывает страницу 'Идет обновление сервера'"""
        for retry in range(SERVER_UPDATE_MAX_RETRIES):
            if not self._is_server_update_page():
                return resp

            if retry == 0:
                print("[CLIENT] Сервер на обновлении, ждём...")

            print(f"[CLIENT] Обновление сервера... попытка {retry + 1}/{SERVER_UPDATE_MAX_RETRIES}")
            time.sleep(SERVER_UPDATE_RETRY_DELAY)

            # Обновляем страницу (GET или POST)
            if method == "post":
                resp = self.session.post(original_url, **kwargs)
            else:
                resp = self.session.get(original_url, **kwargs)
            self.current_page = resp.text
            self.current_url = resp.url

        print("[CLIENT] Сервер всё ещё на обновлении после всех попыток")
        return resp

    def _is_server_update_page(self):
        """Проверяет является ли текущая страница 'обновление сервера'"""
        if not self.current_page:
            return False
        return "Идет обновление сервера" in self.current_page or "Идёт обновление сервера" in self.current_page

    def is_server_updating(self):
        """Публичный метод для проверки обновления сервера"""
        return self._is_server_update_page()

    def wait_for_server(self, check_url=None, max_wait_minutes=10):
        """
        Ожидает окончания обновления сервера.

        Args:
            check_url: URL для проверки (если None - перезагружает текущую страницу)
            max_wait_minutes: максимальное время ожидания в минутах

        Returns:
            bool: True если сервер доступен, False если таймаут
        """
        if not self._is_server_update_page():
            return True

        url = check_url or self.current_url or BASE_URL
        max_attempts = max_wait_minutes * 6  # проверка каждые 10 секунд

        print(f"[CLIENT] Сервер на обновлении, ждём до {max_wait_minutes} минут...")

        for attempt in range(max_attempts):
            time.sleep(10)
            try:
                self.session.get(url, timeout=10)
                self.current_page = self.session.get(url).text
                if not self._is_server_update_page():
                    print(f"[CLIENT] Сервер доступен после {(attempt + 1) * 10} секунд")
                    return True
            except Exception:
                pass

            if (attempt + 1) % 6 == 0:  # каждую минуту
                print(f"[CLIENT] Обновление сервера... {(attempt + 1) // 6} мин")

        print(f"[CLIENT] Таймаут ожидания сервера ({max_wait_minutes} мин)")
        return False

    def post(self, url, max_retries=3, **kwargs):
        """POST запрос с обработкой обновления сервера и автоматическим retry"""
        if not url:
            print("[ERR] POST called with empty URL")
            return None
        if not url.startswith("http"):
            url = urljoin(BASE_URL, url)

        # Устанавливаем таймаут по умолчанию
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 30

        for attempt in range(max_retries):
            try:
                resp = self.session.post(url, **kwargs)
                self.current_page = resp.text
                self.current_url = resp.url

                # Обработка обновления сервера (как в GET)
                if self._is_server_update_page():
                    resp = self._handle_server_update(url, method="post", **kwargs)

                return resp

            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 sec
                    print(f"[CLIENT] POST {url[:50]}... failed ({e.__class__.__name__}), retry in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    print(f"[ERR] POST {url[:50]}... failed after {max_retries} attempts: {e}")
                    raise

        return None

    def soup(self):
        """Возвращает BeautifulSoup текущей страницы"""
        if self.current_page:
            return BeautifulSoup(self.current_page, "html.parser")
        return None

    def ajax_get(self, url, base_url=None, **kwargs):
        """
        AJAX GET запрос с заголовками Wicket.

        Args:
            url: URL для запроса
            base_url: Wicket-Ajax-BaseURL (по умолчанию извлекается из URL)

        Returns:
            Response object
        """
        if not url:
            print("[ERR] ajax_get called with empty URL")
            return None
        if not url.startswith("http"):
            url = urljoin(BASE_URL, url)

        # Определяем base_url из path
        if base_url is None:
            parsed = urlparse(url)
            path = parsed.path.lstrip("/")
            base_url = path if path else "city"

        headers = dict(AJAX_HEADERS)
        headers["Wicket-Ajax-BaseURL"] = base_url

        resp = self.session.get(url, headers=headers, **kwargs)
        # Для AJAX не обновляем current_page целиком
        return resp

    def ajax_post(self, url, base_url=None, **kwargs):
        """
        AJAX POST запрос с заголовками Wicket.

        Args:
            url: URL для запроса
            base_url: Wicket-Ajax-BaseURL (по умолчанию извлекается из URL)

        Returns:
            Response object
        """
        if not url:
            print("[ERR] ajax_post called with empty URL")
            return None
        if not url.startswith("http"):
            url = urljoin(BASE_URL, url)

        # Определяем base_url из path
        if base_url is None:
            parsed = urlparse(url)
            path = parsed.path.lstrip("/")
            base_url = path if path else "city"

        headers = dict(AJAX_HEADERS)
        headers["Wicket-Ajax-BaseURL"] = base_url

        resp = self.session.post(url, headers=headers, **kwargs)
        return resp

    def get_page_id(self):
        """
        Извлекает pageId из текущей страницы.

        Returns:
            int or None: pageId
        """
        if not self.current_page:
            return None

        # Ищем window.ptxPageId = N
        match = re.search(r'window\.ptxPageId\s*=\s*(\d+)', self.current_page)
        if match:
            return int(match.group(1))

        # Альтернативно из URL: ?123
        if self.current_url:
            match = re.search(r'\?(\d+)', self.current_url)
            if match:
                return int(match.group(1))

        return None

    def is_logged_in(self):
        """Проверяет авторизацию"""
        resp = self.get("/city")
        # Проверяем URL и наличие формы логина
        if "login" in resp.url.lower() or "accessDenied" in resp.url:
            return False
        if "loginForm" in self.current_page:
            return False
        return True

    def check_auth_from_page(self, html: str = None) -> bool:
        """
        Проверяет авторизацию по содержимому страницы.
        Не делает дополнительных запросов.

        Args:
            html: HTML страницы (если None - использует current_page)

        Returns:
            bool: True если авторизован
        """
        if html is None:
            html = self.current_page
        if not html:
            return False

        # Проверяем JS переменные
        if "ptxIsERLogged = false" in html:
            return False
        if "ptxUserLogin = ''" in html or 'ptxUserLogin = ""' in html:
            return False
        if "loginForm" in html:
            return False

        return True

    def ensure_logged_in(self) -> bool:
        """
        Проверяет авторизацию и перелогинивается если нужно.

        Returns:
            bool: True если авторизован (или успешно перелогинился)
        """
        # Быстрая проверка по текущей странице
        if self.current_page and self.check_auth_from_page():
            return True

        # Полная проверка
        if self.is_logged_in():
            return True

        # Нужен перелогин
        print("[WARN] Session expired, re-logging...")
        try:
            from requests_bot.config import get_credentials
            username, password = get_credentials()
            if self.login(username, password):
                print("[OK] Re-login successful")
                return True
        except Exception as e:
            print(f"[ERR] Re-login failed: {e}")

        return False

    def is_dead(self) -> bool:
        """
        Проверяет, мёртв ли персонаж (на кладбище).

        Returns:
            bool: True если на странице /graveyard
        """
        if self.current_url and "/graveyard" in self.current_url:
            return True
        return False

    def leave_graveyard(self) -> bool:
        """
        Уходит с кладбища через город (для гарантированного воскрешения).

        Returns:
            bool: True если успешно ушли с кладбища
        """
        if not self.is_dead():
            return True  # Не на кладбище

        print("[GRAVEYARD] Персонаж умер! Ухожу через город...")

        # Сначала в город — там точно воскреснет
        self.get("/city")

        # Потом в подземелья
        self.get("/dungeons?52")

        # Проверяем что ушли
        if self.is_dead():
            print("[GRAVEYARD] Не удалось уйти с кладбища")
            return False

        print("[GRAVEYARD] Воскрешён, продолжаем работу")
        return True

    def login(self, username=None, password=None):
        """
        Авторизация через requests.
        Если username/password не указаны, загружает из профиля или settings.json
        """
        # Загружаем креды если не указаны
        if not username or not password:
            # Сначала пробуем из профиля
            try:
                from requests_bot.config import get_credentials
                profile_user, profile_pass = get_credentials()
                if profile_user and profile_pass:
                    username = profile_user
                    password = profile_pass
            except Exception:
                pass

            # Фоллбэк на settings.json
            if not username or not password:
                try:
                    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                        settings = json.load(f)
                        username = settings.get("login")
                        password = settings.get("password")
                except Exception as e:
                    print(f"[ERR] Cannot load settings: {e}")
                    return False

        if not username or not password:
            print("[ERR] No credentials found")
            return False

        print(f"[*] Logging in as {username}...")

        # 1. Загружаем страницу логина
        resp = self.get("/login")
        print(f"[*] Login page: {resp.url}")

        soup = self.soup()
        if not soup:
            print("[ERR] Cannot parse login page")
            return False

        # 2. Ищем форму - может быть с разными ID
        form = soup.find("form", id="loginForm")
        if not form:
            # Ищем форму с action содержащим login/entrance
            for f in soup.find_all("form"):
                action = f.get("action", "")
                if "login" in action or "entrance" in action:
                    form = f
                    break
        if not form:
            # Может уже залогинены
            if self.is_logged_in():
                print("[OK] Already logged in")
                return True
            print("[ERR] Login form not found")
            return False

        # Получаем action URL
        action = form.get("action", "")
        if not action:
            print("[ERR] Form action not found")
            return False

        # Собираем данные формы
        form_data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

        # Заполняем логин/пароль
        form_data["login"] = username
        form_data["password"] = password

        print(f"[*] Submitting to {action}")

        # 3. Отправляем форму
        resp = self.post(action, data=form_data)
        print(f"[*] Response URL: {resp.url}")

        # 4. Проверяем успешность
        if self.is_logged_in():
            print("[OK] Login successful!")
            # Сохраняем куки
            self._save_cookies()
            return True
        else:
            print("[ERR] Login failed")
            # Проверяем ошибку
            soup = self.soup()
            if soup:
                error = soup.find("span", class_="feedbackPanelERROR")
                if error:
                    print(f"[ERR] Server says: {error.get_text(strip=True)}")
            return False

    def _save_cookies(self):
        """Сохраняет куки в файл (формат Playwright)"""
        cookies_path = config.COOKIES_FILE
        cookies = []

        for cookie in self.session.cookies:
            cookies.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires if cookie.expires else -1,
                "httpOnly": True,  # По умолчанию
                "secure": cookie.secure,
                "sameSite": "None",
            })

        try:
            with open(cookies_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            print(f"[OK] Cookies saved ({len(cookies)} items)")
        except Exception as e:
            print(f"[WARN] Cannot save cookies: {e}")

    def repair_equipment(self):
        """
        Проверяет и ремонтирует снаряжение, если нужно.
        Использует Vue API для получения данных профиля и выполнения ремонта.

        Returns:
            bool: True если ремонт выполнен, False если не нужен или ошибка
        """
        # Переходим на страницу профиля
        resp = self.get(f"{BASE_URL}/user")
        if not resp:
            return False

        html = self.current_page

        # Ищем apiGetUrl в HTML - это Vue API endpoint для получения данных профиля
        api_get_match = re.search(r"apiGetUrl:\s*'([^']+)'", html)
        api_link_match = re.search(r"apiLinkUrl:\s*'([^']+)'", html)

        if not api_get_match or not api_link_match:
            return self._repair_equipment_legacy()

        api_get_url = api_get_match.group(1)
        api_link_url = api_link_match.group(1)

        # Запрашиваем JSON с данными профиля
        headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        }

        try:
            resp = self.session.get(api_get_url, headers=headers)
            if resp.status_code != 200:
                return False

            data = resp.json()
        except Exception:
            return False

        # Извлекаем данные о ремонте
        profile = data.get("profile", {})
        mannequin = profile.get("mannequin", {})
        repair_info = mannequin.get("repair", {})

        percent = repair_info.get("percent", 100)
        link_id = repair_info.get("link_id")

        if percent >= 100:
            return False

        if not link_id:
            return False

        print(f"[REPAIR] Прочность {percent}%, выполняю ремонт...")

        # Выполняем ремонт через apiLinkUrl
        repair_url = f"{api_link_url}&link_id={link_id}"

        try:
            resp = self.session.get(repair_url, headers=headers)
            if resp.status_code == 200:
                print("[REPAIR] Ремонт выполнен!")
                return True
            return False
        except Exception:
            return False

    def _repair_equipment_legacy(self):
        """Старый метод ремонта через HTML парсинг (фолбек)."""
        soup = self.soup()
        if not soup:
            return False

        # Ищем блок ремонта
        repair_div = soup.select_one("div.repair-c.mannequin-repair")
        if not repair_div:
            return False

        # Получаем процент прочности
        percent_span = repair_div.select_one("span.repair-percent")
        if not percent_span:
            return False

        percent_text = percent_span.get_text(strip=True)  # "85%"
        try:
            percent = int(percent_text.replace("%", ""))
        except ValueError:
            return False

        if percent >= 100:
            return False

        # Legacy метод не реализован
        return False

    def find_wicket_link(self, element_id=None, href_contains=None, text_contains=None):
        """
        Находит Wicket callback URL в HTML.

        Wicket генерирует ссылки вида:
        - href="?0-1.IBehaviorListener.0-attackLink"
        - onclick="...Wicket.Ajax.get({u:'./combat?0-1.IBehaviorListener.0-attackLink'})..."

        Args:
            element_id: ID элемента (например "ptx_combat_rich2_attack_link")
            href_contains: Подстрока в href
            text_contains: Текст ссылки

        Returns:
            Полный URL для запроса или None
        """
        soup = self.soup()
        if not soup:
            return None

        element = None

        # Поиск по ID
        if element_id:
            element = soup.find(id=element_id)

        # Поиск по href
        elif href_contains:
            element = soup.find("a", href=lambda h: h and href_contains in h)

        # Поиск по тексту
        elif text_contains:
            element = soup.find("a", string=lambda s: s and text_contains.lower() in s.lower())
            if not element:
                # Поиск в span внутри ссылки
                for a in soup.find_all("a"):
                    if a.get_text(strip=True).lower().find(text_contains.lower()) >= 0:
                        element = a
                        break

        if not element:
            return None

        # Извлекаем URL
        href = element.get("href")
        if href:
            # Относительный URL
            if href.startswith("?") or href.startswith("./"):
                return urljoin(self.current_url, href)
            elif href.startswith("/"):
                return urljoin(BASE_URL, href)
            else:
                return href

        # Проверяем onclick для AJAX
        onclick = element.get("onclick", "")
        match = re.search(r"u:'([^']+)'", onclick)
        if match:
            return urljoin(self.current_url, match.group(1))

        return None

    def find_all_wicket_links(self):
        """
        Находит все Wicket ссылки на странице.
        Возвращает словарь {описание: url}
        """
        soup = self.soup()
        if not soup:
            return {}

        links = {}

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True)[:50]  # Первые 50 символов

            # Ищем Wicket паттерны
            if "IBehaviorListener" in href or "ILinkListener" in href:
                key = text if text else a.get("id", href[:30])
                links[key] = urljoin(self.current_url, href)

        return links

    def get_page_info(self):
        """Возвращает информацию о текущей странице"""
        soup = self.soup()
        if not soup:
            return {"error": "No page loaded"}

        info = {
            "url": self.current_url,
            "title": soup.title.string if soup.title else None,
        }

        # Проверяем бой
        attack_link = soup.find(id="ptx_combat_rich2_attack_link")
        info["in_battle"] = attack_link is not None

        if attack_link:
            info["attack_url"] = self.find_wicket_link(element_id="ptx_combat_rich2_attack_link")

        # Юниты
        units = []
        for pos in range(21, 26):
            unit = soup.select_one(f".unit._unit-pos-{pos}")
            if unit:
                name_el = unit.select_one(".unit-name")
                units.append({
                    "pos": pos,
                    "name": name_el.get_text(strip=True) if name_el else "Unknown"
                })
        info["units"] = units

        # Скиллы
        skills = []
        for pos in range(1, 6):
            skill = soup.select_one(f".wrap-skill-link._skill-pos-{pos}")
            if skill:
                timer = skill.select_one(".time-counter")
                timer_text = timer.get_text(strip=True) if timer else ""
                ready = not timer_text or timer_text == "00:00"

                skill_link = skill.select_one("a.skill-link")
                skills.append({
                    "pos": pos,
                    "ready": ready,
                    "cooldown": timer_text if not ready else None,
                    "url": self.find_wicket_link(href_contains=f"skill-pos-{pos}") if skill_link else None
                })
        info["skills"] = skills

        return info


def test_client():
    """Тест клиента"""
    client = VMMOClient()

    print("=" * 50)
    print("VMMO Requests Client Test")
    print("=" * 50)

    # Пробуем загрузить куки
    client.load_cookies()

    # Проверяем авторизацию
    print("\n[*] Проверяем авторизацию...")
    if client.is_logged_in():
        print("[OK] Авторизация OK (cookies)")
    else:
        print("[WARN] Cookies expired, trying login...")
        if not client.login():
            print("[ERR] Login failed")
            return

    # Загружаем список данженов
    print("\n[*] Загружаем /dungeons...")
    client.get("/dungeons?52")
    print(f"URL: {client.current_url}")

    # Ищем все Wicket ссылки
    print("\n[LINKS] Wicket ссылки на странице:")
    links = client.find_all_wicket_links()
    for name, url in list(links.items())[:10]:  # Первые 10
        print(f"  - {name}: {url}")

    if len(links) > 10:
        print(f"  ... и ещё {len(links) - 10}")

    # Информация о странице
    print("\n[INFO] Информация о странице:")
    info = client.get_page_info()
    print(f"  URL: {info.get('url')}")
    print(f"  В бою: {info.get('in_battle')}")
    print(f"  Юниты: {len(info.get('units', []))}")

    return client


if __name__ == "__main__":
    test_client()
