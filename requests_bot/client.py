# ============================================
# VMMO Requests Client
# ============================================
# Экспериментальный клиент на requests для тестирования
# возможности боя без браузера
# ============================================

import requests
import re
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://vmmo.vten.ru"
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class VMMOClient:
    """HTTP клиент для VMMO на requests"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        })
        self.current_page = None  # Последний загруженный HTML
        self.current_url = None

    def load_cookies(self, cookies_path=None):
        """Загружает куки из файла (формат Playwright)"""
        if cookies_path is None:
            cookies_path = os.path.join(SCRIPT_DIR, "cookies.json")

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

    def get(self, url, **kwargs):
        """GET запрос с сохранением страницы"""
        if not url.startswith("http"):
            url = urljoin(BASE_URL, url)

        resp = self.session.get(url, **kwargs)
        self.current_page = resp.text
        self.current_url = resp.url
        return resp

    def post(self, url, **kwargs):
        """POST запрос"""
        if not url.startswith("http"):
            url = urljoin(BASE_URL, url)

        resp = self.session.post(url, **kwargs)
        self.current_page = resp.text
        self.current_url = resp.url
        return resp

    def soup(self):
        """Возвращает BeautifulSoup текущей страницы"""
        if self.current_page:
            return BeautifulSoup(self.current_page, "html.parser")
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

    def login(self, username=None, password=None):
        """
        Авторизация через requests.
        Если username/password не указаны, загружает из settings.json
        """
        # Загружаем креды если не указаны
        if not username or not password:
            settings_path = os.path.join(SCRIPT_DIR, "settings.json")
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
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
        cookies_path = os.path.join(SCRIPT_DIR, "cookies.json")
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
