from playwright.sync_api import sync_playwright
import json
import os
import sys
import argparse

# Путь к папке скрипта
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.json")


def load_credentials():
    """Загружает логин и пароль из settings.json"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
                return settings.get("login"), settings.get("password")
        except:
            pass
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chromium", action="store_true", help="Использовать Chromium")
    parser.add_argument("--headless", action="store_true", help="Без GUI")
    args = parser.parse_args()

    # Загружаем креды из settings.json
    login, password = load_credentials()
    if not login or not password:
        print("❌ Креды не найдены в settings.json (login/password)")
        return

    with sync_playwright() as p:
        # Chromium для сервера, Firefox для Windows
        if args.chromium:
            browser = p.chromium.launch(headless=args.headless)
        else:
            browser = p.firefox.launch(headless=args.headless)

        context = browser.new_context()
        page = context.new_page()

        page.goto("https://vmmo.vten.ru/login")

        page.fill('input[name="login"]', login)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')

        # Ждём редиректа после логина (не networkidle — он зависает)
        try:
            page.wait_for_url("**/user/**", timeout=15000)
        except:
            pass

        # Дополнительная пауза для загрузки кук
        import time
        time.sleep(3)

        cookies = context.cookies()

        cookies_path = os.path.join(SCRIPT_DIR, "cookies.json")
        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        print(f"Куки сохранены → {cookies_path}")

        # Закрываем браузер
        browser.close()

if __name__ == "__main__":
    main()
