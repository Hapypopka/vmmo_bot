# ============================================
# VMMO Tutorial Runner
# ============================================
# Автоматическое прохождение туториала
# После создания персонажа нужно:
# 1. Пойти в таверну
# 2. Взять квест
# 3. Пройти бой (через combat.py)
# 4. Вернуться и сдать квест
# ============================================

import re
import time
import requests
from bs4 import BeautifulSoup


# Дефолтный URL (используется если клиент не передан)
# ВАЖНО: Для туториала нового персонажа используем m.vten.ru т.к.
# создание персонажа происходит там и куки привязаны к этому домену
DEFAULT_BASE_URL = "https://m.vten.ru"


class TutorialRunner:
    """
    Прохождение туториала для нового персонажа.

    Флоу:
    1. Переход в таверну
    2. Получение списка квестов
    3. Принятие туториального квеста
    4. Прохождение боя
    5. Возврат в таверну
    6. Сдача квеста
    """

    # Туториальные квесты
    TUTORIAL_QUESTS = [
        "new_tuturial1_quests_1_1",  # Скромная просьба - первый бой
        "new_tuturial2_quests_1_1",  # Своевременная помощь - использовать скилл
        "new_tuturial1_quests_1_2",  # Основы экипировки - надеть броню
    ]

    def __init__(self, client):
        """
        Args:
            client: VMMOClient или requests.Session
        """
        # Поддерживаем оба варианта: VMMOClient и requests.Session
        if hasattr(client, 'session'):
            # Это VMMOClient - используем его base_url
            self.session = client.session
            self.client = client
            # Берём base_url из клиента если есть
            self.base_url = getattr(client, 'base_url', None) or DEFAULT_BASE_URL
        else:
            # Это requests.Session напрямую
            self.session = client
            self.client = None
            self.base_url = DEFAULT_BASE_URL

        self.current_page = None
        self.jsessionid = self.session.cookies.get("JSESSIONID", "")

    def _get(self, url: str, spa: bool = True) -> requests.Response | None:
        """Делает GET запрос с нужными заголовками"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        if spa:
            headers['Accept'] = 'text/json, application/json'
            headers['ptxAPI'] = 'true'
        # НЕ ставим ptxspa для обычных запросов - иначе получаем кэш

        try:
            resp = self.session.get(url, headers=headers)
            if resp.status_code == 200:
                self.current_page = resp.text
                return resp
        except Exception as e:
            print(f"[TUTORIAL] Ошибка запроса: {e}")
        return None

    # Маппинг квестов на данжены и требования
    # quest_id -> (dungeon_id, use_skill)
    # ВАЖНО: ID данженов отличаются от ID квестов!
    # Квест new_tuturial1_quests_1_1 -> данжен d_new_tuturial_quests_1_1
    # Квест new_tuturial2_quests_1_1 -> данжен d_new_tuturial_quests_1_5
    QUEST_CONFIG = {
        "new_tuturial1_quests_1_1": ("new_tuturial_quests_1_1", False),  # Просто бой
        "new_tuturial2_quests_1_1": ("new_tuturial_quests_1_5", True),   # Использовать скилл "Гром и Молния"
        "new_tuturial1_quests_1_2": ("equip_item", False),               # Надеть броню (специальное действие)
    }

    # Квесты требующие специальных действий (не бой)
    SPECIAL_QUESTS = {
        "new_tuturial1_quests_1_2": "equip_item",  # Надеть броню из рюкзака
    }

    def run_tutorial(self) -> bool:
        """
        Запускает полное прохождение туториала.

        После создания персонажа мы сразу в ТАВЕРНЕ!
        Флоу:
        1. Идём в таверну (на случай если мы где-то ещё)
        2. Цикл по туториальным квестам:
           - Берём квест
           - Проходим бой (для 2го квеста используем скилл)
           - Сдаём квест
        """
        print("[TUTORIAL] Начинаю прохождение туториала...")

        # Шаг 1: Идём в таверну
        if not self._go_to_tavern():
            print("[TUTORIAL] Ошибка перехода в таверну")
            return False

        # Шаг 3: Проходим все туториальные квесты
        next_quest_id = None  # ID следующего квеста из ответа сервера

        for i, quest_id in enumerate(self.TUTORIAL_QUESTS):
            # Используем ID из ответа сервера если есть
            actual_quest_id = next_quest_id if next_quest_id else quest_id
            print(f"\n[TUTORIAL] === Квест {i+1}/{len(self.TUTORIAL_QUESTS)}: {actual_quest_id} ===")

            # Парсим API endpoints (нужно каждый раз после возврата в таверну)
            api_urls = self._parse_tavern_api()
            if not api_urls:
                print("[TUTORIAL] Не удалось получить API таверны")
                # Если таверна пустая - возможно туториал уже пройден
                return True

            # Проверяем - специальный квест или обычный бой
            # Сначала проверяем по actual_quest_id, потом по quest_id из списка
            is_special = actual_quest_id in self.SPECIAL_QUESTS or quest_id in self.SPECIAL_QUESTS
            action = self.SPECIAL_QUESTS.get(actual_quest_id) or self.SPECIAL_QUESTS.get(quest_id)

            # Берём квест
            # ВАЖНО: next_quest_id из API - это только информация о следующем квесте,
            # квест НЕ автоматически принят! Нужно всегда вызывать Accept.
            # Исключение: обычные боевые квесты иногда принимаются автоматически.
            if is_special or not next_quest_id:
                # Специальные квесты ВСЕГДА требуют Accept
                if not self._accept_quest(api_urls, actual_quest_id):
                    print(f"[TUTORIAL] Не удалось принять квест {actual_quest_id}")
                    continue  # Пробуем следующий
            else:
                print(f"[TUTORIAL] Квест {actual_quest_id} возможно уже выдан")

            if is_special:
                # Специальный квест (не бой)
                if action == "equip_item":
                    if not self._equip_item():
                        print(f"[TUTORIAL] Ошибка экипировки для квеста {actual_quest_id}")
                        return False
                elif action == "upgrade_amulet":
                    if not self._upgrade_amulet():
                        print(f"[TUTORIAL] Ошибка улучшения амулета для квеста {actual_quest_id}")
                        return False
                else:
                    print(f"[TUTORIAL] Неизвестное действие: {action}")
                    return False
            else:
                # Обычный квест с боем
                dungeon_id, use_skill = self.QUEST_CONFIG.get(actual_quest_id, (None, False))
                if not dungeon_id:
                    dungeon_id, use_skill = self.QUEST_CONFIG.get(quest_id, (None, False))
                if not dungeon_id:
                    # Фоллбек: убираем цифру после tuturial
                    dungeon_id = actual_quest_id.replace("tuturial1", "tuturial").replace("tuturial2", "tuturial")
                    dungeon_id = dungeon_id.replace("_1_1", "_1_1").replace("_1_2", "_1_2")

                # Проходим бой
                if not self._complete_combat(dungeon_id, use_skill=use_skill):
                    print(f"[TUTORIAL] Ошибка боя для квеста {actual_quest_id}")
                    return False

            # Сдаём квест и получаем ID следующего квеста
            next_quest_id = self._complete_quest_with_next(actual_quest_id)
            if next_quest_id is None:
                print(f"[TUTORIAL] Не удалось сдать квест {actual_quest_id}")
                # Продолжаем - может следующий получится
                next_quest_id = None

            time.sleep(1)  # Пауза между квестами

        print("\n[TUTORIAL] Все туториальные квесты пройдены!")
        return True

    def _equip_item(self) -> bool:
        """
        Надевает предмет из рюкзака для квеста "Основы экипировки".

        Флоу:
        1. Переходим в рюкзак /user/rack
        2. Ищем кнопку "Надеть" (wearLink)
        3. Нажимаем на неё
        4. Идём в таверну с параметром quest=...&take=false
        5. В ответе будет модалка с ppAction=take_quest_reward&ppKey=...
        6. Нажимаем - квест сдан
        """
        print("[TUTORIAL] Надеваю предмет из рюкзака...")

        # Шаг 1: Переходим в рюкзак
        rack_url = f"{self.base_url}/user/rack"
        resp = self._get(rack_url, spa=False)
        if not resp:
            print("[TUTORIAL] Ошибка загрузки рюкзака")
            return False

        print(f"[TUTORIAL] Рюкзак загружен: {resp.url}")

        # Шаг 2: Ищем кнопку "Надеть" (wearLink)
        wear_link = None
        wear_pattern = r'href="([^"]*wearLink[^"]*)"'
        match = re.search(wear_pattern, self.current_page or "")
        if match:
            wear_link = match.group(1).replace("&amp;", "&")
            print(f"[TUTORIAL] Найден wearLink: {wear_link[:80]}...")

        if not wear_link:
            print("[TUTORIAL] Кнопка 'Надеть' не найдена в рюкзаке")
            with open("debug_rack.html", "w", encoding="utf-8") as f:
                f.write(self.current_page or "")
            return False

        # Шаг 3: Нажимаем "Надеть"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html',
            'ptxSPA': 'true',
            'Referer': str(resp.url),
        }

        wear_resp = self.session.get(wear_link, headers=headers)
        print(f"[TUTORIAL] Экипировка: статус {wear_resp.status_code}")

        if wear_resp.status_code != 200:
            print("[TUTORIAL] Ошибка экипировки")
            return False

        self.current_page = wear_resp.text
        print("[TUTORIAL] Предмет успешно надет!")

        # Шаг 4: Идём в таверну и сдаём квест через apiQuestCompleteUrl
        print("[TUTORIAL] Иду в таверну для сдачи квеста...")
        time.sleep(0.5)

        quest_id = "new_tuturial1_quests_1_2"
        tavern_url = f"{self.base_url}/tavern"
        tavern_resp = self._get(tavern_url, spa=False)

        if not tavern_resp:
            print("[TUTORIAL] Ошибка загрузки таверны")
            return False

        # Сохраняем для отладки
        with open("debug_tavern_after_equip.html", "w", encoding="utf-8") as f:
            f.write(self.current_page or "")

        # Шаг 5: Парсим API URLs
        api_urls = self._parse_tavern_api()
        if not api_urls:
            print("[TUTORIAL] API таверны не найден")
            return False

        api_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/json',
            'ptxAPI': 'true',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': str(tavern_resp.url),
        }

        # Шаг 6: Получаем данные таверны через apiFullUrl чтобы проверить статус квеста
        full_url = api_urls.get('full')
        if not full_url:
            # Парсим apiFullUrl если не был в _parse_tavern_api
            full_match = re.search(r"apiFullUrl\s*=\s*'([^']+)'", self.current_page or "")
            if full_match:
                full_url = full_match.group(1)

        if full_url:
            print(f"[TUTORIAL] Получаю данные таверны: {full_url[:60]}...")
            full_resp = self.session.get(full_url, headers=api_headers)
            print(f"[TUTORIAL] apiFullUrl ответ: {full_resp.status_code}")

            if full_resp.status_code == 200:
                try:
                    tavern_data = full_resp.json()
                    # Ищем наш квест в данных
                    quest_status = None
                    quests = tavern_data.get('quests', [])
                    for section in quests:
                        for quest in section.get('content', []):
                            if quest.get('id') == quest_id:
                                quest_status = quest.get('status')
                                progress = quest.get('progress', {})
                                print(f"[TUTORIAL] Квест {quest_id}: status={quest_status}, progress={progress}")
                                break
                        if quest_status:
                            break

                    if quest_status != 'complete':
                        print(f"[TUTORIAL] Квест не выполнен! Статус: {quest_status}")
                        print("[TUTORIAL] Возможно предмет не надет корректно")
                        # Сохраняем данные для отладки
                        with open("debug_tavern_data.json", "w", encoding="utf-8") as f:
                            import json
                            json.dump(tavern_data, f, ensure_ascii=False, indent=2)
                        return False
                except Exception as e:
                    print(f"[TUTORIAL] Ошибка парсинга данных таверны: {e}")

        # Шаг 7: View + Complete
        if 'view' in api_urls:
            view_url = f"{api_urls['view']}&quest_id={quest_id}"
            print(f"[TUTORIAL] View квест: {view_url[:70]}...")
            view_resp = self.session.get(view_url, headers=api_headers)
            print(f"[TUTORIAL] View ответ: {view_resp.status_code}")
            time.sleep(0.3)

        if 'complete' in api_urls:
            complete_url = f"{api_urls['complete']}&quest_id={quest_id}"
            print(f"[TUTORIAL] Complete квест: {complete_url[:70]}...")

            complete_resp = self.session.get(complete_url, headers=api_headers)
            print(f"[TUTORIAL] Complete ответ: {complete_resp.status_code}")

            if complete_resp.status_code == 200:
                try:
                    data = complete_resp.json()
                    print(f"[TUTORIAL] Complete data: {data}")
                    status = data.get('status', '').upper()
                    if status == 'OK':
                        print("[TUTORIAL] Квест экипировки сдан!")
                        return True
                except Exception as e:
                    print(f"[TUTORIAL] Ошибка парсинга: {e}")

        print("[TUTORIAL] Не удалось сдать квест")
        return False

    def _upgrade_amulet(self) -> bool:
        """
        Улучшает амулет для квеста.

        Флоу:
        1. Переходим в профиль /city
        2. Переходим в амулеты (ищем ссылку или /user/amulets)
        3. Ищем первый амулет и его ID
        4. Переходим на страницу улучшения /amulet/upgrade/{id}
        5. Нажимаем "Улучшить бесплатно" (upgradeLink)
        """
        print("[TUTORIAL] Улучшаю амулет...")

        # Шаг 1: Переходим в профиль
        city_url = f"{self.base_url}/city"
        resp = self._get(city_url, spa=False)
        if not resp:
            print("[TUTORIAL] Ошибка загрузки профиля")
            return False

        print(f"[TUTORIAL] Профиль загружен: {resp.url}")

        # Шаг 2: Ищем ссылку на амулеты или ID первого амулета
        # Паттерн: /amulet/upgrade/537421071 или amuletUrl
        amulet_id = None

        # Ищем прямую ссылку на улучшение амулета
        amulet_match = re.search(r'/amulet/upgrade/(\d+)', self.current_page or "")
        if amulet_match:
            amulet_id = amulet_match.group(1)
            print(f"[TUTORIAL] Найден ID амулета: {amulet_id}")

        if not amulet_id:
            # Ищем через страницу амулетов
            amulets_url = f"{self.base_url}/user/amulets"
            resp2 = self._get(amulets_url, spa=False)
            if resp2:
                amulet_match = re.search(r'/amulet/upgrade/(\d+)', self.current_page or "")
                if amulet_match:
                    amulet_id = amulet_match.group(1)
                    print(f"[TUTORIAL] Найден ID амулета на странице амулетов: {amulet_id}")

        if not amulet_id:
            print("[TUTORIAL] ID амулета не найден")
            return False

        # Шаг 3: Переходим на страницу улучшения
        upgrade_page_url = f"{self.base_url}/amulet/upgrade/{amulet_id}"
        resp3 = self._get(upgrade_page_url, spa=False)
        if not resp3:
            print("[TUTORIAL] Ошибка загрузки страницы улучшения")
            return False

        print(f"[TUTORIAL] Страница улучшения: {resp3.url}")

        # Шаг 4: Ищем URL кнопки "Улучшить бесплатно"
        # Паттерн из curl: ?{pageId}-1.ILinkListener-amuletUpgradePanel-upgradeBlock-upgradeLink&uk={timestamp}
        upgrade_link = None

        # Ищем в Wicket.Ajax.ajax
        upgrade_pattern = r'"u":"([^"]*upgradeLink[^"]*)"'
        match = re.search(upgrade_pattern, self.current_page or "")
        if match:
            upgrade_link = match.group(1)
            print(f"[TUTORIAL] Найден upgradeLink в Ajax: {upgrade_link[:60]}...")

        if not upgrade_link:
            # Ищем прямую ссылку в href (с полным URL)
            # Пример: href="https://m.vten.ru/amulet/upgrade/537430938?45-2.ILinkListener-amuletUpgradePanel-upgradeBlock-upgradeLink&amp;uk=..."
            link_pattern = rf'href="(https?://[^"]*amulet/upgrade/{amulet_id}\?[^"]*upgradeLink[^"]*)"'
            match2 = re.search(link_pattern, self.current_page or "")
            if match2:
                upgrade_link = match2.group(1)
                # Декодируем HTML entities (&amp; -> &)
                upgrade_link = upgrade_link.replace("&amp;", "&")
                print(f"[TUTORIAL] Найден upgradeLink в href: {upgrade_link[:80]}...")

        if not upgrade_link:
            # Парсим page_id и строим URL вручную
            page_id_match = re.search(r'ptxPageId\s*=\s*(\d+)', self.current_page or "")
            if page_id_match:
                page_id = page_id_match.group(1)
                uk = int(time.time() * 1000)
                upgrade_link = f"{self.base_url}/amulet/upgrade/{amulet_id}?{page_id}-1.ILinkListener-amuletUpgradePanel-upgradeBlock-upgradeLink&uk={uk}"
                print(f"[TUTORIAL] Сгенерирован upgradeLink: {upgrade_link[:60]}...")

        if not upgrade_link:
            print("[TUTORIAL] URL улучшения не найден")
            return False

        # Шаг 5: Нажимаем "Улучшить бесплатно"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html',
            'ptxSPA': 'true',
            'Referer': str(resp3.url),
        }

        upgrade_resp = self.session.get(upgrade_link, headers=headers)
        print(f"[TUTORIAL] Улучшение: статус {upgrade_resp.status_code}")

        if upgrade_resp.status_code == 200:
            self.current_page = upgrade_resp.text

            # Сохраняем HTML для отладки
            with open("debug_upgrade_result.html", "w", encoding="utf-8") as f:
                f.write(upgrade_resp.text)
            print("[TUTORIAL] HTML сохранён в debug_upgrade_result.html")

            # Проверяем что амулет улучшен (уровень 2 или выше)
            if "2 ур" in upgrade_resp.text or "3 ур" in upgrade_resp.text:
                print("[TUTORIAL] Амулет успешно улучшен до 2+ уровня!")
            else:
                print("[TUTORIAL] Амулет улучшен (статус 200)")

            # Шаг 6: Возвращаемся в таверну для сдачи квеста
            time.sleep(0.5)
            if not self._go_to_tavern():
                print("[TUTORIAL] Не удалось вернуться в таверну после улучшения")
                # Не критично - продолжаем

            return True

        print("[TUTORIAL] Ошибка улучшения амулета")
        return False

    def _go_to_tavern(self) -> bool:
        """Переходит в таверну"""
        print("[TUTORIAL] Перехожу в таверну...")

        # Проверяем - может клиент уже на странице таверны?
        if self.client and self.client.current_page:
            client_page = self.client.current_page
            print(f"[TUTORIAL] Клиент имеет страницу, длина: {len(client_page)}")

            # Проверяем признаки таверны
            has_tavern_ui = "Ptx.Shadows.Ui.Tavern" in client_page
            has_api_url = "apiQuestViewUrl" in client_page
            has_tavern_title = "Таверна" in client_page
            print(f"[TUTORIAL] Признаки таверны: UI={has_tavern_ui}, API={has_api_url}, Title={has_tavern_title}")

            if has_tavern_ui or has_api_url or has_tavern_title:
                print("[TUTORIAL] Клиент уже в таверне, используем его страницу")
                self.current_page = client_page
                return True

        # Переходим в таверну без random параметра (Wicket не любит)
        tavern_url = f"{self.base_url}/tavern"
        resp = self._get(tavern_url, spa=False)

        if not resp:
            print("[TUTORIAL] Ошибка загрузки таверны")
            return False

        print(f"[TUTORIAL] URL ответа: {resp.url}")
        print(f"[TUTORIAL] Статус: {resp.status_code}")

        # Проверяем ptxPageUrl в ответе
        page_url_match = re.search(r"ptxPageUrl\s*=\s*'([^']+)'", self.current_page or "")
        if page_url_match:
            actual_page = page_url_match.group(1)
            print(f"[TUTORIAL] Фактическая страница: {actual_page}")

            # Если сервер отдаёт другую страницу - это проблема с Wicket state
            # Попробуем сделать "чистый" запрос без редиректов
            if "tavern" not in actual_page.lower():
                print("[TUTORIAL] Сервер вернул не таверну, пробую через главную...")

                # Идём через главную страницу чтобы сбросить Wicket state
                home_resp = self.session.get(f"{self.base_url}/", headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html',
                })

                if home_resp.status_code == 200:
                    # Ищем ссылку на таверну
                    tavern_link = re.search(r'href="([^"]*tavern[^"]*)"', home_resp.text)
                    if tavern_link:
                        tavern_url = tavern_link.group(1)
                        if not tavern_url.startswith("http"):
                            tavern_url = f"{self.base_url}{tavern_url}"
                        print(f"[TUTORIAL] Найдена ссылка на таверну: {tavern_url}")
                        resp = self._get(tavern_url, spa=False)

        # Сохраняем для отладки
        with open("tavern_debug.html", "w", encoding="utf-8") as f:
            f.write(self.current_page or "")

        if resp and ("tavern" in resp.url.lower() or "apiQuestViewUrl" in (self.current_page or "")):
            print("[TUTORIAL] Успешно попали в таверну")
            return True

        if resp and resp.status_code == 200:
            print("[TUTORIAL] Получили 200, проверяем контент...")
            return True

        print(f"[TUTORIAL] Неожиданный URL: {resp.url if resp else 'None'}")
        return False

    def _parse_tavern_api(self) -> dict | None:
        """Парсит API endpoints таверны из HTML"""
        if not self.current_page:
            print("[TUTORIAL] current_page пустая!")
            return None

        api_urls = {}

        # Паттерны для API URLs
        patterns = {
            'view': r"apiQuestViewUrl\s*=\s*'([^']+)'",
            'accept': r"apiQuestAcceptUrl\s*=\s*'([^']+)'",
            'complete': r"apiQuestCompleteUrl\s*=\s*'([^']+)'",
            'quests': r"apiQuestsUrl\s*=\s*'([^']+)'",
            'full': r"apiFullUrl\s*=\s*'([^']+)'",
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, self.current_page)
            if match:
                api_urls[key] = match.group(1)
                print(f"[TUTORIAL] API {key}: {api_urls[key][:60]}...")

        if not api_urls:
            # Отладка: ищем любые IEndpointBehaviorListener
            endpoints = re.findall(r'IEndpointBehaviorListener\.\d+-\w+', self.current_page)
            if endpoints:
                print(f"[TUTORIAL] Найдены endpoints: {endpoints[:5]}")
            else:
                print("[TUTORIAL] Endpoints не найдены в HTML")
                # Показываем часть HTML для отладки
                print(f"[TUTORIAL] HTML длина: {len(self.current_page)}")
                if "ptxPageUrl" in self.current_page:
                    match = re.search(r"ptxPageUrl\s*=\s*'([^']+)'", self.current_page)
                    if match:
                        print(f"[TUTORIAL] ptxPageUrl: {match.group(1)}")

        return api_urls if api_urls else None

    def _accept_quest(self, api_urls: dict, quest_id: str) -> bool:
        """Принимает квест"""
        print(f"[TUTORIAL] Принимаю квест: {quest_id}")

        # Сначала просматриваем квест
        view_url = api_urls.get('view')
        if view_url:
            view_url = f"{view_url}&quest_id={quest_id}"
            self._get(view_url, spa=True)
            time.sleep(0.5)

        # Принимаем квест
        accept_url = api_urls.get('accept')
        if not accept_url:
            print("[TUTORIAL] URL принятия квеста не найден")
            return False

        accept_url = f"{accept_url}&quest_id={quest_id}"
        resp = self._get(accept_url, spa=True)

        if resp:
            print(f"[TUTORIAL] Квест принят, ответ: {resp.status_code}")
            return True

        return False

    def _complete_combat(self, quest_id: str = "new_tuturial_quests_1_1", use_skill: bool = False) -> bool:
        """
        Проходит бой туториального квеста.

        Args:
            quest_id: ID данжена (без префикса d_)
            use_skill: Если True - использовать скилл в бою (для 2го туториального квеста)

        Использует простой боевой цикл:
        1. Загрузить страницу боя
        2. Найти URL атаки (и скилла если нужно)
        3. Выполнить AJAX-атаку/скилл
        4. Перезагрузить страницу (чтобы получить актуальный HTML)
        5. Собрать лут через refresher
        6. Повторять пока не победим или нет врагов
        """
        print(f"[TUTORIAL] Начинаю бой... (use_skill={use_skill})")

        time.sleep(0.5)

        # Формируем URL данжена для туториального квеста
        dungeon_url = f"{self.base_url}/dungeon/combat/d_{quest_id}?1=normal"
        print(f"[TUTORIAL] URL данжена: {dungeon_url}")

        # Загружаем страницу боя
        resp = self.session.get(dungeon_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })

        if resp.status_code != 200:
            print(f"[TUTORIAL] Ошибка загрузки: {resp.status_code}")
            return False

        combat_url = str(resp.url)
        self.current_page = resp.text
        print(f"[TUTORIAL] URL боя: {combat_url}")

        # Извлекаем page ID из URL (нужен для Wicket-Ajax-BaseURL и refresher)
        page_id = ""
        page_match = re.search(r'\?(\d+)', combat_url)
        if page_match:
            page_id = page_match.group(1)

        # Извлекаем lootTakeUrl для сбора лута
        loot_take_url = None
        loot_match = re.search(r"lootTakeUrl\s*=\s*['\"]([^'\"]+)['\"]", self.current_page)
        if loot_match:
            loot_take_url = loot_match.group(1)
            print(f"[TUTORIAL] Loot URL найден")

        # Формируем refresher URL для сбора лута
        # Формат: dungeon/combat/XXX?{pageId}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher&1=normal
        combat_base = combat_url.split("?")[0]
        refresher_url = f"{combat_base}?{page_id}-1.IBehaviorListener.0-combatPanel-container-battlefield-refresher&1=normal"

        collected_loot = set()  # Уже собранный лут
        skill_used = False  # Флаг использования скилла

        # Боевой цикл
        max_attacks = 50
        attacks = 0
        ATTACK_CD = 0.6
        SKILL_CD = 2.0  # GCD после скилла

        # Базовые заголовки для AJAX
        base_path = combat_url.split("?")[0].replace(self.base_url, "").lstrip("/")
        ajax_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            "Wicket-Ajax": "true",
            "Wicket-Ajax-BaseURL": f"{base_path}?{page_id}" if page_id else base_path,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml, text/xml, */*; q=0.01",
            "Referer": combat_url,
        }

        while attacks < max_attacks:
            # Проверяем победу - кнопка "Продолжить" или модалка результата
            if self._check_combat_victory():
                print(f"[TUTORIAL] Победа! Атак: {attacks}")
                # Финальный сбор лута
                self._collect_loot(refresher_url, loot_take_url, collected_loot)
                return True

            # Проверяем наличие врагов (позиции 21-25)
            if not self._has_enemies():
                print(f"[TUTORIAL] Все враги убиты! Атак: {attacks}")
                # Финальный сбор лута
                self._collect_loot(refresher_url, loot_take_url, collected_loot)
                # Туториальный данжен автоматически завершается - ждём 5 сек для надёжности
                print("[TUTORIAL] Ожидаю завершение боя...")
                time.sleep(5)
                return True

            # Если нужно использовать скилл и ещё не использовали
            if use_skill and not skill_used:
                skill_url = self._find_skill_url()
                if skill_url:
                    print(f"[TUTORIAL] Использую скилл! URL: {skill_url[:80]}...")
                    skill_headers = ajax_headers.copy()
                    skill_headers["Wicket-FocusedElementId"] = "ptx_combat_rich2_skill_link_1"
                    skill_resp = self.session.get(skill_url, headers=skill_headers)
                    if skill_resp.status_code == 200:
                        skill_used = True
                        print(f"[TUTORIAL] Скилл использован!")
                        time.sleep(SKILL_CD)
                        # Перезагружаем страницу
                        page_resp = self.session.get(combat_url, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        })
                        if page_resp.status_code == 200:
                            self.current_page = page_resp.text
                        continue
                    else:
                        print(f"[TUTORIAL] Ошибка скилла: {skill_resp.status_code}")
                else:
                    # Скилл не найден - сохраняем HTML для отладки
                    if attacks == 0:
                        print(f"[TUTORIAL] WARN: Скилл не найден в HTML!")
                        with open("debug_combat_no_skill.html", "w", encoding="utf-8") as f:
                            f.write(self.current_page or "")

            # Ищем URL атаки
            attack_url = self._find_attack_url()
            if not attack_url:
                print(f"[TUTORIAL] URL атаки не найден, атак: {attacks}")
                # Может бой закончился
                if attacks > 0:
                    self._collect_loot(refresher_url, loot_take_url, collected_loot)
                    return True
                return False

            # Делаем AJAX-атаку
            attack_headers = ajax_headers.copy()
            attack_headers["Wicket-FocusedElementId"] = "ptx_combat_rich2_attack_link"

            attack_resp = self.session.get(attack_url, headers=attack_headers)

            if attack_resp.status_code == 200:
                attacks += 1
                if attacks % 5 == 0 or attacks == 1:
                    print(f"[TUTORIAL] Атака #{attacks}")

                # Ждём GCD
                time.sleep(ATTACK_CD)

                # Собираем лут каждые 3 атаки
                if attacks % 3 == 0:
                    self._collect_loot(refresher_url, loot_take_url, collected_loot)

                # Перезагружаем страницу для получения актуального HTML
                page_resp = self.session.get(combat_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                })
                if page_resp.status_code == 200:
                    self.current_page = page_resp.text
            else:
                print(f"[TUTORIAL] Ошибка атаки: {attack_resp.status_code}")
                break

        print(f"[TUTORIAL] Достигнут лимит атак: {max_attacks}")
        self._collect_loot(refresher_url, loot_take_url, collected_loot)
        return True

    def _check_combat_victory(self) -> bool:
        """Проверяет победу в бою"""
        if not self.current_page:
            return False

        # Кнопка "Продолжить" появляется после победы
        if "btn-rich3-content" in self.current_page:
            soup = BeautifulSoup(self.current_page, "html.parser")
            for btn in soup.select(".btn-rich3-content"):
                if "Продолжить" in btn.get_text():
                    return True

        # Модалка результата боя
        if "combat-result" in self.current_page:
            return True

        return False

    def _click_continue(self, combat_url: str, page_id: str) -> bool:
        """
        Ждёт появления кнопки 'Продолжить' и нажимает её.
        После убийства врагов нужно подождать пока сервер обработает победу.
        """
        print("[TUTORIAL] Ожидаю кнопку 'Продолжить'...")

        max_attempts = 15  # Максимум 15 попыток по 1 сек = 15 секунд
        base_path = combat_url.split("?")[0].replace(self.base_url, "").lstrip("/")

        for attempt in range(max_attempts):
            # Перезагружаем страницу
            resp = self.session.get(combat_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            })

            if resp.status_code != 200:
                print(f"[TUTORIAL] Ошибка перезагрузки: {resp.status_code}")
                time.sleep(1)
                continue

            self.current_page = resp.text

            # Ищем URL для кнопки "Продолжить"
            # Паттерн: Wicket.Ajax.ajax({"c":"..._proceed_link","u":"..."})
            proceed_pattern = r'"c":"[^"]*proceed[^"]*"[^}]*"u":"([^"]+)"'
            match = re.search(proceed_pattern, self.current_page, re.IGNORECASE)

            if not match:
                # Альтернативный паттерн
                proceed_pattern2 = r'Wicket\.Ajax\.ajax\(\{[^}]*"u":"([^"]+)"[^}]*\}[^)]*\)[^<]*Продолжить'
                match = re.search(proceed_pattern2, self.current_page)

            if not match:
                # Ищем в HTML ссылку с классом btn-rich3
                soup = BeautifulSoup(self.current_page, "html.parser")
                for btn in soup.select("a.btn-rich3, a.btn-rich3-content, .btn-rich3 a, a[id*=proceed]"):
                    text = btn.get_text()
                    if "Продолжить" in text or "продолжить" in text.lower():
                        onclick = btn.get("onclick", "")
                        href = btn.get("href", "")
                        if onclick:
                            url_match = re.search(r'"u":"([^"]+)"', onclick)
                            if url_match:
                                proceed_url = url_match.group(1)
                                print(f"[TUTORIAL] Найден URL в onclick (попытка {attempt+1}): {proceed_url[:50]}...")
                                self.session.get(proceed_url, headers={
                                    'User-Agent': 'Mozilla/5.0',
                                    'Wicket-Ajax': 'true',
                                    'X-Requested-With': 'XMLHttpRequest',
                                })
                                print("[TUTORIAL] Бой завершён!")
                                return True
                        if href and href != "#":
                            print(f"[TUTORIAL] Найден href (попытка {attempt+1}): {href[:50]}...")
                            if not href.startswith("http"):
                                href = f"{self.base_url}{href}"
                            self.session.get(href)
                            print("[TUTORIAL] Бой завершён!")
                            return True

            if match:
                proceed_url = match.group(1)
                print(f"[TUTORIAL] URL 'Продолжить' (попытка {attempt+1}): {proceed_url[:50]}...")

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Wicket-Ajax': 'true',
                    'Wicket-Ajax-BaseURL': f"{base_path}?{page_id}" if page_id else base_path,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/xml, text/xml, */*; q=0.01',
                    'Referer': combat_url,
                }

                resp = self.session.get(proceed_url, headers=headers)
                print(f"[TUTORIAL] Ответ 'Продолжить': {resp.status_code}")
                print("[TUTORIAL] Бой завершён!")
                return True

            # Не нашли кнопку - ждём и пробуем снова
            if attempt < max_attempts - 1:
                print(f"[TUTORIAL] Кнопка не найдена, жду... (попытка {attempt+1}/{max_attempts})")
                time.sleep(1)

        print("[TUTORIAL] Кнопка 'Продолжить' не появилась после 15 секунд")
        # Пробуем просто перейти в таверну - может бой уже завершён
        return True

    def _has_enemies(self) -> bool:
        """Проверяет есть ли живые враги (позиции 21-25)"""
        if not self.current_page:
            return False

        soup = BeautifulSoup(self.current_page, "html.parser")

        # Враги находятся на позициях 21-25
        for pos in range(21, 26):
            unit = soup.select_one(f".unit._unit-pos-{pos}")
            if unit:
                # Проверяем что у юнита есть HP (значит живой)
                # Класс unit-hp, не unit-hp-bar
                hp_el = unit.select_one(".unit-hp")
                if hp_el:
                    return True

        return False

    def _collect_loot(self, refresher_url: str, loot_take_url: str | None, collected: set) -> int:
        """Собирает лут через refresher"""
        if not refresher_url:
            return 0

        try:
            # Вызываем refresher
            resp = self.session.get(refresher_url, timeout=10)
            if resp.status_code != 200:
                return 0

            response_text = resp.text

            # Ищем lootTakeUrl в ответе refresher
            if not loot_take_url:
                loot_match = re.search(r"lootTakeUrl\s*=\s*'([^']+)'", response_text)
                if loot_match:
                    loot_take_url = loot_match.group(1)

            # Ищем dropLoot в ответе
            if "dropLoot" not in response_text:
                return 0

            # Парсим ID лута
            loot_ids = re.findall(r"id:\s*'(\d+)'", response_text)
            if not loot_ids or not loot_take_url:
                return 0

            count = 0
            for loot_id in loot_ids:
                if loot_id not in collected:
                    take_url = loot_take_url + loot_id
                    try:
                        self.session.get(take_url, timeout=5)
                        collected.add(loot_id)
                        count += 1
                    except:
                        pass

            if count > 0:
                print(f"[TUTORIAL] Собрано лута: {count}")

            return count
        except Exception as e:
            return 0

    def _run_combat_loop(self) -> bool:
        """Цикл боя - атакуем пока не победим"""
        print("[TUTORIAL] Запускаю боевой цикл...")

        max_turns = 50
        for turn in range(max_turns):
            if not self.current_page:
                break

            # Проверяем победу
            if self._check_victory():
                print("[TUTORIAL] Победа!")
                return True

            # Ищем URL атаки
            attack_url = self._find_attack_url()
            if not attack_url:
                print("[TUTORIAL] URL атаки не найден")
                break

            # Атакуем
            print(f"[TUTORIAL] Ход {turn + 1}: атакую...")
            resp = self._get(attack_url, spa=True)

            if resp:
                # Обновляем страницу после атаки
                time.sleep(0.6)  # GCD

        return False

    def _find_attack_url(self) -> str | None:
        """Ищет URL для атаки на странице боя"""
        if not self.current_page:
            return None

        # Паттерн для Wicket AJAX
        pattern = r'"c":"ptx_combat_rich2_attack_link"[^}]*"u":"([^"]+)"'
        match = re.search(pattern, self.current_page)
        if match:
            return match.group(1)

        # Альтернативный паттерн
        pattern2 = r'Wicket\.Ajax\.ajax\(\{[^}]*"u":"([^"]+attack[^"]+)"'
        match2 = re.search(pattern2, self.current_page)
        if match2:
            return match2.group(1)

        return None

    def _find_skill_url(self, skill_num: int = 1) -> str | None:
        """
        Ищет URL для использования скилла на странице боя.

        Args:
            skill_num: Номер скилла (1-5), по умолчанию 1 (индекс в HTML: skill_num - 1)

        Returns:
            URL для активации скилла или None
        """
        if not self.current_page:
            return None

        # В HTML skill_num 1 = индекс 0 в массиве skills
        skill_index = skill_num - 1

        # Паттерн 1: Ищем по индексу в URL (skills-0-skillBlock-skillBlockInner-skillLink)
        # Пример: "u":"https://m.vten.ru/dungeon/combat/...skills-0-skillBlock-skillBlockInner-skillLink&1=normal"
        pattern1 = rf'"u":"([^"]*skills-{skill_index}-skillBlock[^"]*skillLink[^"]*)"'
        match1 = re.search(pattern1, self.current_page)
        if match1:
            return match1.group(1)

        # Паттерн 2: Старый формат - "c":"ptx_combat_rich2_skill_link_1","u":"..."
        pattern2 = rf'"c":"ptx_combat_rich2_skill_link_{skill_num}"[^}}]*"u":"([^"]+)"'
        match2 = re.search(pattern2, self.current_page)
        if match2:
            return match2.group(1)

        # Паттерн 3: Альтернативный - ищем по skill в component id
        pattern3 = rf'Wicket\.Ajax\.ajax\(\{{[^}}]*"c":"[^"]*skill[^"]*"[^}}]*"u":"([^"]+)"'
        match3 = re.search(pattern3, self.current_page, re.IGNORECASE)
        if match3:
            return match3.group(1)

        # Паттерн 4: Обратный порядок c и u
        pattern4 = rf'"u":"([^"]+)"[^}}]*"c":"ptx_combat_rich2_skill_link_{skill_num}"'
        match4 = re.search(pattern4, self.current_page)
        if match4:
            return match4.group(1)

        return None

    def _check_victory(self) -> bool:
        """Проверяет победили ли мы"""
        if not self.current_page:
            return False

        # Сначала проверяем что мы на странице боя
        # Если нет URL атаки и нет признаков боя - возможно мы не в бою
        if "combat" not in self.current_page.lower() and "attackUrl" not in self.current_page:
            # Не на странице боя
            return False

        # Признаки победы (только для страницы боя!)
        victory_indicators = [
            "combat-result",  # Результат боя
            "Продолжить",     # Кнопка после победы
            "Победа",         # Текст победы
        ]

        for indicator in victory_indicators:
            if indicator in self.current_page:
                return True

        # Если нет врагов (все убиты) - тоже победа
        # Проверяем наличие активных врагов
        if "enemy-dead" in self.current_page and "enemy-alive" not in self.current_page:
            return True

        return False

    def _complete_quest_with_next(self, quest_id: str) -> str | None:
        """
        Сдаёт квест и возвращает ID следующего квеста.

        Returns:
            ID следующего квеста если есть, "" если квест сдан но следующего нет,
            None если ошибка сдачи
        """
        print(f"[TUTORIAL] Сдаю квест: {quest_id}")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html',
            'ptxSPA': 'true',
        }

        reward_pattern = r'href="([^"]*ppAction=take_quest_reward[^"]*)"'

        # Шаг 1: Идём в таверну с параметром quest=...&take=false
        # Это откроет квест и покажет модалку с кнопкой "Забрать награду"
        tavern_url = f"{self.base_url}/tavern?quest={quest_id}&take=false"
        headers['Referer'] = tavern_url
        resp = self._get(tavern_url, spa=False)

        if not resp:
            print("[TUTORIAL] Ошибка загрузки таверны")
            return None

        # Ищем кнопку "Забрать награду" в модалке
        reward_match = re.search(reward_pattern, self.current_page or "")

        if reward_match:
            reward_link = reward_match.group(1).replace("&amp;", "&")
            print(f"[TUTORIAL] Найдена кнопка сдачи: {reward_link[:70]}...")

            reward_resp = self.session.get(reward_link, headers=headers)
            print(f"[TUTORIAL] Сдаю квест: статус {reward_resp.status_code}")

            if reward_resp.status_code == 200:
                self.current_page = reward_resp.text
                print("[TUTORIAL] Квест сдан через кнопку!")

                # Ищем ID следующего квеста в ответе
                next_quest_match = re.search(
                    r'quest=([a-z_0-9]+)',
                    self.current_page or "",
                    re.IGNORECASE
                )
                if next_quest_match:
                    next_quest = next_quest_match.group(1)
                    if next_quest != quest_id and "tuturial" in next_quest:
                        print(f"[TUTORIAL] Следующий квест: {next_quest}")
                        return next_quest

                return ""  # Квест сдан

        # Шаг 2: Пробуем /city?quest=...&take=false
        print("[TUTORIAL] Пробую /city для сдачи...")
        city_url = f"{self.base_url}/city?quest={quest_id}&take=false"
        resp = self._get(city_url, spa=False)

        if resp:
            reward_match = re.search(reward_pattern, self.current_page or "")
            if reward_match:
                reward_link = reward_match.group(1).replace("&amp;", "&")
                print(f"[TUTORIAL] Найдена кнопка в /city: {reward_link[:70]}...")

                reward_resp = self.session.get(reward_link, headers=headers)
                if reward_resp.status_code == 200:
                    self.current_page = reward_resp.text
                    print("[TUTORIAL] Квест сдан!")
                    return ""

        # Шаг 3: Пробуем через API (фоллбек)
        print("[TUTORIAL] Пробую через API...")
        tavern_resp = self._get(f"{self.base_url}/tavern", spa=False)

        if not tavern_resp:
            return ""

        api_urls = self._parse_tavern_api()
        if not api_urls:
            print("[TUTORIAL] API не найден, квест возможно уже сдан")
            return ""

        api_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'ptxAPI': 'true',
            'X-Requested-With': 'XMLHttpRequest',
        }

        if 'complete' in api_urls:
            complete_url = f"{api_urls['complete']}&quest_id={quest_id}"
            print(f"[TUTORIAL] Complete через API: {complete_url[:70]}...")

            complete_resp = self.session.get(complete_url, headers=api_headers)
            print(f"[TUTORIAL] Complete ответ: {complete_resp.status_code}")

            if complete_resp.status_code == 200:
                try:
                    complete_data = complete_resp.json()
                    print(f"[TUTORIAL] Complete data: {complete_data}")

                    status = complete_data.get('status', '').lower()
                    next_quest = complete_data.get('quest', '')

                    if next_quest:
                        print(f"[TUTORIAL] Следующий квест: {next_quest}")

                    if status in ('ok', 'success'):
                        print("[TUTORIAL] Квест сдан через API!")
                        return next_quest
                    elif status == 'fail':
                        print("[TUTORIAL] Fail - квест возможно уже сдан")
                        return ""
                    else:
                        return next_quest
                except Exception:
                    pass
            elif complete_resp.status_code == 404:
                print("[TUTORIAL] 404 - квест возможно уже сдан")
                return ""

        return ""

    def _complete_quest(self, quest_id: str) -> bool:
        """Сдаёт квест в таверне (обёртка для обратной совместимости)"""
        result = self._complete_quest_with_next(quest_id)
        return result is not None

    def change_character_name(self, new_name: str) -> bool:
        """
        Меняет имя персонажа (доступно после создания).

        Флоу:
        1. Загрузить /user/mainsettings (HTML страница)
        2. Найти apiSetUrl в Vue инициализации
        3. Вызвать apiSetUrl с setting_id=character3 -> получить redirect на changelogin
        4. Загрузить страницу changelogin
        5. Заполнить и отправить форму
        """
        print(f"[TUTORIAL] Меняю имя на: {new_name}")

        # Шаг 1: Загружаем страницу настроек
        settings_url = f"{self.base_url}/user/mainsettings"
        resp = self._get(settings_url, spa=False)

        if not resp:
            print("[TUTORIAL] Ошибка загрузки настроек")
            return False

        print(f"[TUTORIAL] Загружена страница настроек: {resp.url}")

        # Шаг 2: Ищем apiSetUrl в Vue инициализации
        # Паттерн: apiSetUrl: 'https://...IEndpointBehaviorListener.1-pnlSettings-blockMain...'
        api_set_match = re.search(r"apiSetUrl:\s*'([^']+)'", self.current_page or "")

        if not api_set_match:
            print("[TUTORIAL] apiSetUrl не найден")
            return False

        api_set_url = api_set_match.group(1)
        print(f"[TUTORIAL] apiSetUrl: {api_set_url[:70]}...")

        # Шаг 3: Вызываем apiSetUrl с setting_id=character3
        # Это должно вернуть JSON с redirect на /user/settings/changelogin
        change_url = f"{api_set_url}&setting_id=character3"

        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'ptxAPI': 'true',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': resp.url,
            'X-Requested-With': 'XMLHttpRequest',
        }

        print(f"[TUTORIAL] Запрос смены имени: {change_url[:70]}...")
        resp2 = self.session.get(change_url, headers=headers)

        print(f"[TUTORIAL] Статус: {resp2.status_code}")

        if resp2.status_code != 200:
            print(f"[TUTORIAL] Ошибка: {resp2.status_code}")
            print(f"[TUTORIAL] Ответ: {resp2.text[:200]}")
            return False

        # Шаг 4: Парсим JSON ответ с redirect
        redirect_url = None
        try:
            data = resp2.json()
            print(f"[TUTORIAL] JSON ответ: {data}")
            if data.get("status") == "redirect":
                redirect_url = data.get("url")
                print(f"[TUTORIAL] Редирект на: {redirect_url}")
        except Exception as e:
            print(f"[TUTORIAL] Ошибка парсинга JSON: {e}")
            print(f"[TUTORIAL] Ответ: {resp2.text[:300]}")
            return False

        if not redirect_url:
            print("[TUTORIAL] URL редиректа не найден в ответе")
            return False

        # Шаг 5: Загружаем страницу changelogin
        if not redirect_url.startswith("http"):
            redirect_url = f"{self.base_url}{redirect_url}"

        resp3 = self._get(redirect_url, spa=False)

        if not resp3:
            print("[TUTORIAL] Ошибка загрузки страницы смены имени")
            return False

        print(f"[TUTORIAL] Страница changelogin загружена: {resp3.url}")

        # Шаг 6: Парсим форму
        soup = BeautifulSoup(self.current_page or "", "html.parser")

        # Ищем форму
        form = soup.find("form", id=re.compile(r"id\w+"))
        if not form:
            print("[TUTORIAL] Форма не найдена")
            # Сохраняем для отладки
            with open("changelogin_debug.html", "w", encoding="utf-8") as f:
                f.write(self.current_page or "")
            return False

        form_id = form.get("id", "")
        action_url = form.get("action", "")
        print(f"[TUTORIAL] Форма: id={form_id}, action={action_url[:60]}...")

        # Собираем данные формы
        form_data = {}

        # Скрытое поле Wicket (id3d_hf_0)
        hidden_field = form.find("input", type="hidden")
        if hidden_field:
            field_name = hidden_field.get("name", "")
            form_data[field_name] = hidden_field.get("value", "")

        # Поле имени
        login_input = form.find("input", attrs={"name": "login"})
        if login_input:
            form_data["login"] = new_name
        else:
            print("[TUTORIAL] Поле login не найдено")
            return False

        print(f"[TUTORIAL] Данные формы: {form_data}")

        # Шаг 7: Отправляем форму
        submit_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': self.base_url,
            'Referer': resp3.url,
        }

        if not action_url.startswith("http"):
            action_url = f"{self.base_url}{action_url}"

        print(f"[TUTORIAL] Отправляю POST на: {action_url[:80]}...")

        resp4 = self.session.post(action_url, data=form_data, headers=submit_headers)

        if resp4.status_code in (200, 302):
            print(f"[TUTORIAL] Ответ: статус {resp4.status_code}")
            # Проверяем ответ на ошибки
            if "feedbackPanelERROR" in resp4.text:
                error_soup = BeautifulSoup(resp4.text, "html.parser")
                error_span = error_soup.find("span", class_="feedbackPanelERROR")
                if error_span:
                    print(f"[TUTORIAL] Ошибка сервера: {error_span.get_text(strip=True)}")
                    return False
            print(f"[TUTORIAL] Имя успешно изменено на '{new_name}'!")
            return True
        else:
            print(f"[TUTORIAL] Ошибка: статус {resp4.status_code}")
            return False


def test_tutorial():
    """Тест туториала"""
    print("=" * 50)
    print("ТЕСТ ТУТОРИАЛА")
    print("=" * 50)

    # Нужна сессия с cookie usr
    session = requests.Session()

    # Здесь нужно подставить актуальные cookies
    # session.cookies.set('JSESSIONID', '...', domain='m.vten.ru')
    # session.cookies.set('usr', '...', domain='m.vten.ru')

    tutorial = TutorialRunner(session)
    success = tutorial.run_tutorial()

    if success:
        print("\n[OK] Туториал пройден!")
    else:
        print("\n[FAIL] Ошибка туториала")

    return success


if __name__ == "__main__":
    test_tutorial()
