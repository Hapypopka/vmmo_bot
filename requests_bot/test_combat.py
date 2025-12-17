# ============================================
# Test Combat Page
# ============================================
# Пробуем загрузить страницу боя и найти кнопку атаки
# ============================================

import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def test_combat():
    client = VMMOClient()

    print("=" * 50)
    print("VMMO Combat Test")
    print("=" * 50)

    if not client.load_cookies():
        return

    # Загружаем Адские Игры
    print("\n[*] Loading /basin/combat (Hell Games)...")
    resp = client.get("/basin/combat")
    print(f"Final URL: {resp.url}")
    print(f"Status: {resp.status_code}")

    # Сохраняем
    path = os.path.join(SCRIPT_DIR, "html_hell_games.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(client.current_page)
    print(f"[SAVED] html_hell_games.html ({len(client.current_page)} bytes)")

    soup = client.soup()
    if soup:
        # Ищем источники (sources)
        sources = soup.select("a.source-link")
        print(f"\nSources found: {len(sources)}")
        for src in sources[:5]:
            classes = src.get("class", [])
            href = src.get("href", "")
            side = "light" if "_side-light" in classes else "dark" if "_side-dark" in classes else "unknown"
            current = "_current" in classes
            print(f"  - {side}{' (current)' if current else ''}: {href[:60]}...")

        # Ищем юниты
        units = soup.select("div.unit")
        print(f"\nUnits found: {len(units)}")
        for unit in units[:5]:
            classes = " ".join(unit.get("class", []))
            pos_match = re.search(r'_unit-pos-(\d+)', classes)
            pos = pos_match.group(1) if pos_match else "?"
            name_el = unit.select_one(".unit-name")
            name = name_el.get_text(strip=True) if name_el else "Unknown"
            print(f"  - pos-{pos}: {name}")

        # Ищем кнопки
        buttons = soup.select("a.go-btn")
        print(f"\nGo buttons: {len(buttons)}")
        for btn in buttons[:5]:
            text = btn.get_text(strip=True)[:30]
            href = btn.get("href", "")[:60]
            print(f"  - '{text}': {href}")

        # Кнопка атаки
        attack = soup.find(id="ptx_combat_rich2_attack_link")
        if attack:
            print("\n[!] Attack button found!")
            href = attack.get("href", "")
            print(f"  href: {href}")
        else:
            print("\n[INFO] No attack button - not in combat")

    return client


if __name__ == "__main__":
    test_combat()
