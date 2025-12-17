# ============================================
# Test Login
# ============================================

import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def test_login():
    client = VMMOClient()

    print("=" * 50)
    print("VMMO Login Test")
    print("=" * 50)

    # Загружаем страницу логина
    print("\n[1] Loading /login...")
    resp = client.get("/login")
    print(f"URL: {resp.url}")
    print(f"Status: {resp.status_code}")
    print(f"Page size: {len(client.current_page)} bytes")

    # Сохраняем
    path = os.path.join(SCRIPT_DIR, "html_login.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(client.current_page)
    print(f"[SAVED] html_login.html")

    soup = client.soup()
    if soup:
        # Ищем формы
        forms = soup.find_all("form")
        print(f"\nForms found: {len(forms)}")
        for form in forms:
            form_id = form.get("id", "no-id")
            action = form.get("action", "no-action")
            print(f"  - {form_id}: {action[:80]}")

            # Поля формы
            inputs = form.find_all("input")
            print(f"    Inputs: {[i.get('name') for i in inputs]}")

        # Ищем кнопки авторизации через соцсети
        soc_links = soup.find_all("a", class_="btn-soc")
        print(f"\nSocial login links: {len(soc_links)}")
        for link in soc_links:
            href = link.get("href", "")
            print(f"  - {href[:60]}...")

        # Ищем другие формы/кнопки входа
        login_inputs = soup.find_all("input", {"name": "login"})
        print(f"\nLogin inputs: {len(login_inputs)}")

        # Проверяем есть ли Wicket AJAX форма
        ajax_matches = re.findall(r'Wicket\.Ajax\.ajax\(\{[^}]+loginForm[^}]+\}\)', client.current_page)
        print(f"\nWicket AJAX login forms: {len(ajax_matches)}")
        for match in ajax_matches[:3]:
            print(f"  - {match[:100]}...")


if __name__ == "__main__":
    test_login()
