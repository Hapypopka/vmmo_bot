# ============================================
# Test Dungeons Loading via API
# ============================================

import os
import sys
import re
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def test_dungeons():
    client = VMMOClient()

    print("=" * 50)
    print("VMMO Dungeons API Test")
    print("=" * 50)

    # Авторизуемся
    client.load_cookies()
    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            return

    # 1. Загружаем страницу данженов
    print("\n[1] Loading /dungeons?52...")
    resp = client.get("/dungeons?52")
    print(f"URL: {resp.url}")

    # 2. Извлекаем pageId
    page_id_match = re.search(r'window\.ptxPageId\s*=\s*(\d+)', client.current_page)
    if page_id_match:
        page_id = page_id_match.group(1)
        print(f"[OK] Found pageId: {page_id}")
    else:
        print("[ERR] pageId not found")
        return

    # 3. Ищем API URLs (apiSectionsUrl, apiSectionUrl, apiLinkUrl)
    api_sections_match = re.search(r"apiSectionsUrl:\s*'([^']+)'", client.current_page)
    api_section_match = re.search(r"apiSectionUrl:\s*'([^']+)'", client.current_page)
    api_link_match = re.search(r"apiLinkUrl:\s*'([^']+)'", client.current_page)

    if api_sections_match:
        api_sections_url = api_sections_match.group(1)
        print(f"[OK] apiSectionsUrl: {api_sections_url}")
    else:
        print("[ERR] apiSectionsUrl not found")
        return

    if api_section_match:
        api_section_url = api_section_match.group(1)
        print(f"[OK] apiSectionUrl: {api_section_url}")

    # 4. Запрашиваем список секций (табов с данженами)
    print("\n[2] Fetching sections...")
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": resp.url,
    }

    sections_resp = client.session.get(api_sections_url, headers=headers)
    print(f"Status: {sections_resp.status_code}")
    print(f"Content-Type: {sections_resp.headers.get('Content-Type')}")

    # Сохраняем
    path = os.path.join(SCRIPT_DIR, "api_sections.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(sections_resp.text)
    print(f"[SAVED] api_sections.json")

    # Парсим JSON
    try:
        sections_data = sections_resp.json()
        print(f"\n[OK] Got JSON response!")

        # Структура: {status, player, sections, bar}
        sections = sections_data.get("sections", [])
        print(f"Sections found: {len(sections)}")
        for s in sections:
            lvls = s.get("lvls", [])
            lvl_str = f"lvl {lvls[0]}-{lvls[1]}" if lvls else ""
            print(f"  - {s.get('id')}: {lvl_str} {s.get('name', '')}")

        # 5. Запрашиваем данжены для tab2 (lvl 1-29)
        if api_section_match:
            print("\n[3] Fetching dungeons for section_id=tab2...")
            section_url = f"{api_section_url}&section_id=tab2"
            dungeons_resp = client.session.get(section_url, headers=headers)
            print(f"Status: {dungeons_resp.status_code}")

            # Сохраняем
            path = os.path.join(SCRIPT_DIR, "api_dungeons.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write(dungeons_resp.text)
            print(f"[SAVED] api_dungeons.json")

            try:
                dungeons_data = dungeons_resp.json()
                # Структура: {status, section: {dungeons: [...]}}
                section_info = dungeons_data.get("section", {})
                dungeons = section_info.get("dungeons", [])
                print(f"\n[OK] Dungeons found: {len(dungeons)}")
                for d in dungeons:
                    name = d.get("name", "?")
                    dng_id = d.get("id", "?")
                    cooldown = d.get("cooldown", 0)
                    cd_str = f" [CD: {cooldown // 1000}s]" if cooldown else " [READY]"
                    print(f"  - {dng_id}: {name}{cd_str}")

                # 6. Пробуем войти в первый доступный данжен
                if api_link_match:
                    api_link_url = api_link_match.group(1)
                    print(f"\n[OK] apiLinkUrl: {api_link_url}")

                    # Ищем данжен без КД
                    for d in dungeons:
                        if not d.get("cooldown"):
                            dng_id = d.get("id")
                            dng_name = d.get("name", "").replace("<br>", " ")
                            print(f"\n[4] Trying to enter: {dng_name} ({dng_id})")

                            # Формируем URL (параметр link_id, не dungeon_id!)
                            enter_url = f"{api_link_url}&link_id={dng_id}"
                            print(f"URL: {enter_url}")

                            enter_resp = client.session.get(enter_url, headers=headers)
                            print(f"Status: {enter_resp.status_code}")
                            print(f"Content-Type: {enter_resp.headers.get('Content-Type')}")

                            # Сохраняем
                            path = os.path.join(SCRIPT_DIR, "api_enter.txt")
                            with open(path, "w", encoding="utf-8") as f:
                                f.write(enter_resp.text)
                            print(f"[SAVED] api_enter.txt ({len(enter_resp.text)} bytes)")

                            # Анализируем ответ
                            if enter_resp.headers.get('Content-Type', '').startswith('application/json'):
                                try:
                                    enter_data = enter_resp.json()
                                    print(f"JSON Response: {json.dumps(enter_data, indent=2)[:500]}")

                                    # Если получили redirect - переходим на landing page
                                    if enter_data.get("status") == "redirect" and enter_data.get("url"):
                                        landing_url = enter_data["url"]

                                        # Добавляем /normal для корректной работы
                                        if not landing_url.endswith("/normal"):
                                            landing_url = landing_url + "/normal"

                                        print(f"\n[5] Following redirect to landing: {landing_url}")

                                        landing_resp = client.get(landing_url)
                                        print(f"Status: {landing_resp.status_code}")
                                        print(f"Final URL: {landing_resp.url}")

                                        # Сохраняем landing page
                                        path = os.path.join(SCRIPT_DIR, "html_landing.html")
                                        with open(path, "w", encoding="utf-8") as f:
                                            f.write(client.current_page)
                                        print(f"[SAVED] html_landing.html ({len(client.current_page)} bytes)")

                                        # Ищем кнопку входа в данжен (ILinkListener)
                                        enter_btn = re.search(r'href=["\']([^"\']*ILinkListener[^"\']*enterLinksPanel[^"\']*)["\']', client.current_page)
                                        if enter_btn:
                                            enter_url = enter_btn.group(1)
                                            print(f"[OK] Found enter button: {enter_url}")

                                            # Кликаем кнопку входа
                                            print(f"\n[6] Clicking enter button...")
                                            enter_btn_resp = client.get(enter_url)
                                            print(f"Status: {enter_btn_resp.status_code}")
                                            print(f"Final URL: {enter_btn_resp.url}")

                                            # Сохраняем страницу лобби
                                            path = os.path.join(SCRIPT_DIR, "html_lobby.html")
                                            with open(path, "w", encoding="utf-8") as f:
                                                f.write(client.current_page)
                                            print(f"[SAVED] html_lobby.html ({len(client.current_page)} bytes)")

                                            # Проверяем, попали ли в лобби или бой
                                            if "/combat" in enter_btn_resp.url:
                                                print("[OK] Entered combat directly!")
                                            elif "/standby" in enter_btn_resp.url or "/step/" in enter_btn_resp.url or "/lobby" in enter_btn_resp.url:
                                                print("[OK] Entered lobby/standby!")

                                                # Ищем кнопку "Начать бой" (ppAction=combat или linkStartCombat)
                                                start_url = None

                                                # Вариант 1: ppAction=combat (standby page)
                                                start_btn = re.search(r'href=["\']([^"\']*ppAction=combat[^"\']*)["\']', client.current_page)
                                                if start_btn:
                                                    start_url = start_btn.group(1).replace("&amp;", "&")
                                                    print(f"[OK] Found start button (ppAction): {start_url}")

                                                # Вариант 2: Wicket AJAX linkStartCombat (lobby page)
                                                if not start_url:
                                                    wicket_start = re.search(r'"u":"([^"]*linkStartCombat[^"]*)"', client.current_page)
                                                    if wicket_start:
                                                        start_url = wicket_start.group(1)
                                                        print(f"[OK] Found start button (Wicket AJAX): {start_url}")

                                                if start_url:
                                                    # Кликаем "Начать бой"
                                                    print(f"\n[7] Starting combat...")

                                                    # Используем Wicket AJAX headers
                                                    wicket_headers = {
                                                        "Wicket-Ajax": "true",
                                                        "Wicket-Ajax-BaseURL": enter_btn_resp.url.split("?")[0].replace("https://vmmo.vten.ru", ""),
                                                        "X-Requested-With": "XMLHttpRequest",
                                                        "Accept": "*/*",
                                                    }
                                                    combat_resp = client.session.get(start_url, headers=wicket_headers)
                                                    print(f"Status: {combat_resp.status_code}")

                                                    # Проверяем тип ответа
                                                    ct = combat_resp.headers.get("Content-Type", "")
                                                    print(f"Content-Type: {ct}")

                                                    if "xml" in ct:
                                                        # Wicket AJAX возвращает XML
                                                        print(f"[OK] Got Wicket AJAX response")

                                                        # Сохраняем AJAX response
                                                        path = os.path.join(SCRIPT_DIR, "ajax_start_combat.xml")
                                                        with open(path, "w", encoding="utf-8") as f:
                                                            f.write(combat_resp.text)
                                                        print(f"[SAVED] ajax_start_combat.xml ({len(combat_resp.text)} bytes)")

                                                        redirect_match = re.search(r'<redirect>([^<]+)</redirect>', combat_resp.text)
                                                        if redirect_match:
                                                            redirect_url = redirect_match.group(1)
                                                            print(f"[OK] Redirect to: {redirect_url}")

                                                            # Переходим на страницу боя
                                                            final_resp = client.get(redirect_url)
                                                            print(f"Final URL: {final_resp.url}")

                                                            # Сохраняем страницу боя
                                                            path = os.path.join(SCRIPT_DIR, "html_combat.html")
                                                            with open(path, "w", encoding="utf-8") as f:
                                                                f.write(client.current_page)
                                                            print(f"[SAVED] html_combat.html ({len(client.current_page)} bytes)")

                                                            if "/combat" in final_resp.url:
                                                                print("[OK] COMBAT STARTED!")

                                                                # Ищем кнопку атаки
                                                                attack_match = re.search(r'Wicket\.Ajax\.ajax\(\{[^}]*"c":"[^"]*attack[^"]*"[^}]*"u":"([^"]+)"', client.current_page, re.IGNORECASE)
                                                                if attack_match:
                                                                    print(f"[OK] Found attack URL: {attack_match.group(1)[:80]}...")
                                                        else:
                                                            # Нет redirect - ищем URL загрузки контента
                                                            load_url_match = re.search(r"Loading content for .*?'([^']+)'", combat_resp.text)
                                                            if load_url_match:
                                                                load_url = load_url_match.group(1)
                                                                print(f"[OK] Content loading URL: {load_url}")

                                                                # Загружаем контент
                                                                content_resp = client.get(load_url)
                                                                print(f"Content URL status: {content_resp.status_code}")
                                                                print(f"Content URL: {content_resp.url}")

                                                                if "/combat" in content_resp.url:
                                                                    print("[OK] COMBAT STARTED!")

                                                                    # Сохраняем страницу боя
                                                                    path = os.path.join(SCRIPT_DIR, "html_combat.html")
                                                                    with open(path, "w", encoding="utf-8") as f:
                                                                        f.write(client.current_page)
                                                                    print(f"[SAVED] html_combat.html ({len(client.current_page)} bytes)")

                                                                    # Ищем URL атаки
                                                                    attack_match = re.search(
                                                                        r'"c":"ptx_combat_rich2_attack_link"[^}]*"u":"([^"]+)"',
                                                                        client.current_page
                                                                    )
                                                                    if attack_match:
                                                                        attack_url = attack_match.group(1)
                                                                        print(f"\n[8] Found attack URL: {attack_url[:80]}...")

                                                                        # Делаем тестовую атаку
                                                                        print("\n[9] Performing test attack...")
                                                                        attack_headers = {
                                                                            "Wicket-Ajax": "true",
                                                                            "Wicket-Ajax-BaseURL": content_resp.url.split("?")[0].replace("https://vmmo.vten.ru", ""),
                                                                            "X-Requested-With": "XMLHttpRequest",
                                                                            "Accept": "*/*",
                                                                        }
                                                                        attack_resp = client.session.get(attack_url, headers=attack_headers)
                                                                        print(f"Attack status: {attack_resp.status_code}")
                                                                        print(f"Attack Content-Type: {attack_resp.headers.get('Content-Type')}")

                                                                        # Сохраняем ответ атаки
                                                                        path = os.path.join(SCRIPT_DIR, "ajax_attack.xml")
                                                                        with open(path, "w", encoding="utf-8") as f:
                                                                            f.write(attack_resp.text)
                                                                        print(f"[SAVED] ajax_attack.xml ({len(attack_resp.text)} bytes)")

                                                                        # Проверяем результат
                                                                        if attack_resp.status_code == 200:
                                                                            print("[OK] ATTACK SUCCESSFUL!")
                                                                    else:
                                                                        print("[WARN] Attack URL not found in combat page")
                                                            else:
                                                                print(f"[?] No redirect/load URL in AJAX response")
                                                    else:
                                                        # Прямой редирект
                                                        print(f"Final URL: {combat_resp.url}")
                                                        client.current_page = combat_resp.text
                                                else:
                                                    print("[WARN] Start button not found")
                                            else:
                                                print(f"[?] Unknown page type: {enter_btn_resp.url}")

                                            # Показываем превью
                                            import re as regex
                                            text = regex.sub(r'<style[^>]*>.*?</style>', '', client.current_page, flags=re.DOTALL)
                                            text = regex.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
                                            text = regex.sub(r'<[^>]+>', ' ', text)
                                            text = regex.sub(r'\s+', ' ', text).strip()
                                            print(f"\n[PREVIEW] Page snippet:\n{text[:600]}")
                                        else:
                                            print("[WARN] Enter button not found")
                                except Exception as e:
                                    print(f"[ERR] {e}")
                            else:
                                print(f"Response preview: {enter_resp.text[:300]}")

                            break
                    else:
                        print("\n[WARN] No available dungeons (all on CD)")

            except json.JSONDecodeError as e:
                print(f"[ERR] JSON decode error: {e}")
                print(f"Response: {dungeons_resp.text[:300]}")

    except json.JSONDecodeError as e:
        print(f"[ERR] Not JSON: {e}")
        print(f"Response: {sections_resp.text[:500]}")


if __name__ == "__main__":
    test_dungeons()
