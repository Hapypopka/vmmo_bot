# ============================================
# Test AJAX endpoints
# ============================================

import os
import sys
import re
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def test_ajax():
    client = VMMOClient()

    print("=" * 50)
    print("VMMO AJAX Test")
    print("=" * 50)

    if not client.load_cookies():
        return

    # 1. Загружаем страницу данженов
    print("\n[1] Loading /dungeons?52...")
    resp = client.get("/dungeons?52")
    print(f"URL: {resp.url}")

    # Извлекаем pageId из URL
    # URL формат: dungeons?X где X это pageId
    page_id_match = re.search(r'\?(\d+)', resp.url)
    if page_id_match:
        page_id = page_id_match.group(1)
        print(f"Page ID: {page_id}")

    # 2. Ищем AJAX URL для подгрузки данженов
    # В HTML: "u":"https://vmmo.vten.ru/dungeons?2-1.IBehaviorListener.0-blockDungeonsNew-lnkPreloader"
    match = re.search(r'"u":"([^"]+IBehaviorListener[^"]+blockDungeonsNew[^"]+)"', client.current_page)
    if match:
        ajax_url = match.group(1)
        print(f"\n[2] Found AJAX URL: {ajax_url}")

        # 3. Делаем AJAX запрос с правильными заголовками
        print("\n[3] Making AJAX request...")
        headers = {
            "Wicket-Ajax": "true",
            "Wicket-Ajax-BaseURL": f"dungeons?{page_id}",
            "Wicket-FocusedElementId": "id1",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml, text/xml, */*; q=0.01",
            "Referer": resp.url,
        }
        resp2 = client.session.get(ajax_url, headers=headers)
        print(f"Status: {resp2.status_code}")
        print(f"Content-Type: {resp2.headers.get('Content-Type')}")
        print(f"Response length: {len(resp2.text)}")

        # Сохраняем ответ
        path = os.path.join(SCRIPT_DIR, "ajax_dungeons.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(resp2.text)
        print(f"[SAVED] ajax_dungeons.xml")

        # Ищем данжены в ответе
        if "dng:" in resp2.text or "map-item" in resp2.text or "Sanctuary" in resp2.text:
            print("\n[OK] Dungeon data found in response!")

            # Извлекаем данжены
            dungeon_matches = re.findall(r'title="(dng:[^"]+)"', resp2.text)
            if dungeon_matches:
                print(f"\nFound {len(dungeon_matches)} dungeons:")
                for d in dungeon_matches:
                    print(f"  - {d}")
        else:
            print("\n[WARN] No dungeon data in response")
            # Показываем начало ответа
            print(f"Response preview: {resp2.text[:500]}")

    else:
        print("[ERR] AJAX URL not found")

    # Попробуем другой подход - прямой URL на лендинг данжена
    print("\n" + "=" * 50)
    print("[4] Trying direct dungeon landing page...")

    # Святилище Накрила
    resp3 = client.get("/dungeon/dSanctuary")
    print(f"URL: {resp3.url}")
    print(f"Status: {resp3.status_code}")

    # Сохраняем
    path = os.path.join(SCRIPT_DIR, "html_dungeon_landing.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(client.current_page)
    print(f"[SAVED] html_dungeon_landing.html ({len(client.current_page)} bytes)")

    # Ищем кнопку входа
    soup = client.soup()
    if soup:
        enter_buttons = soup.find_all("a", class_="go-btn")
        print(f"\nGo buttons found: {len(enter_buttons)}")
        for btn in enter_buttons[:5]:
            text = btn.get_text(strip=True)
            href = btn.get("href", "")
            print(f"  - '{text}' -> {href[:80]}...")


if __name__ == "__main__":
    test_ajax()
