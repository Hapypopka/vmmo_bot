# ============================================
# VMMO HTML Explorer
# ============================================
# Сохраняет HTML страниц для анализа структуры
# ============================================

import os
import sys

# Добавляем путь к родительской директории
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def save_html(client, name):
    """Сохраняет текущую страницу в файл"""
    path = os.path.join(SCRIPT_DIR, f"html_{name}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(client.current_page)
    print(f"[SAVED] html_{name}.html")


def explore():
    """Исследует структуру сайта"""
    client = VMMOClient()

    print("=" * 50)
    print("VMMO HTML Explorer")
    print("=" * 50)

    if not client.load_cookies():
        return

    if not client.is_logged_in():
        print("[ERR] Not logged in")
        return

    # Сохраняем разные страницы
    pages = [
        ("/dungeons?52", "dungeons"),
        ("/city", "city"),
    ]

    for url, name in pages:
        print(f"\n[*] Loading {url}...")
        client.get(url)
        save_html(client, name)

        # Анализируем ссылки
        soup = client.soup()
        if soup:
            # Все ссылки на данжены
            dungeon_links = soup.select("div[title^='dng:']")
            if dungeon_links:
                print(f"  Dungeon divs: {len(dungeon_links)}")
                for d in dungeon_links[:3]:
                    title = d.get("title", "")
                    print(f"    - {title}")

            # Кнопки
            buttons = soup.select("a.go-btn")
            if buttons:
                print(f"  Go buttons: {len(buttons)}")
                for b in buttons[:5]:
                    href = b.get("href", "")
                    text = b.get_text(strip=True)[:30]
                    print(f"    - '{text}' -> {href}")

    print("\n[DONE] HTML files saved to requests_bot/")


if __name__ == "__main__":
    explore()
