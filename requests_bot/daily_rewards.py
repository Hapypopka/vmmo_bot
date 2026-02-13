# ============================================
# VMMO Daily Rewards Module (requests version)
# ============================================
# Автосбор ежедневных наград + Великая Библиотека
# ============================================

import re
import os
import json
import random
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from requests_bot.config import add_protected_item
import requests_bot.config as config  # Для динамического доступа к PROFILE_DIR
from requests_bot.logger import log_info, log_debug, log_error, log_warning

BASE_URL = "https://vmmo.vten.ru"

# Московский часовой пояс (UTC+3)
MSK = timezone(timedelta(hours=3))

# Маппинг день -> (row, container) для URL формирования
# Структура наград в HTML:
# Row 0: дни 1, 2, 3 (containers 0, 1, 2)
# Row 1: дни 4, 5, 6 (containers 0, 1, 2)
# Row 2: день 7 (container 0, colspan=3)
DAY_TO_POSITION = {
    1: (0, 0),
    2: (0, 1),
    3: (0, 2),
    4: (1, 0),
    5: (1, 1),
    6: (1, 2),
    7: (2, 0),
}


def get_daily_rewards_cache_file():
    """Возвращает путь к файлу кэша ежедневных наград"""
    profile_dir = config.PROFILE_DIR  # Динамически получаем из config
    if profile_dir:
        return os.path.join(profile_dir, "daily_rewards_cache.json")
    return "daily_rewards_cache.json"


def is_reward_collected_today():
    """
    Проверяет, была ли уже собрана награда сегодня (по МСК).

    Returns:
        bool: True если награда уже собрана сегодня
    """
    cache_file = get_daily_rewards_cache_file()

    try:
        if not os.path.exists(cache_file):
            return False

        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        last_collected = data.get("last_collected")
        if not last_collected:
            return False

        # Парсим дату последнего сбора
        last_date = datetime.fromisoformat(last_collected)

        # Текущая дата по МСК
        now_msk = datetime.now(MSK)

        # Сравниваем даты (только день)
        if last_date.date() >= now_msk.date():
            return True

        return False

    except (json.JSONDecodeError, IOError, ValueError) as e:
        print(f"[DAILY] Ошибка чтения кэша: {e}")
        return False


def mark_reward_collected():
    """Записывает в кэш что награда собрана"""
    cache_file = get_daily_rewards_cache_file()

    now_msk = datetime.now(MSK)
    data = {
        "last_collected": now_msk.isoformat(),
        "last_collected_readable": now_msk.strftime("%Y-%m-%d %H:%M:%S MSK")
    }

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[DAILY] Кэш обновлён: {data['last_collected_readable']}")
    except IOError as e:
        print(f"[DAILY] Ошибка записи кэша: {e}")


class DailyRewardsClient:
    """Клиент для сбора ежедневных наград"""

    def __init__(self, client):
        """
        Args:
            client: VMMOClient instance
        """
        self.client = client
        self.rewards_collected = 0

    def has_daily_reward_available(self):
        """
        Проверяет наличие доступной ежедневной награды на главной странице.

        Returns:
            bool: True если есть доступная награда
        """
        soup = self.client.soup()
        if not soup:
            return False

        # Ищем ссылку на /dailyrewardevent
        daily_link = soup.select_one('a[href*="dailyrewardevent"]')
        if daily_link:
            return True

        return False

    def open_daily_rewards_modal(self):
        """
        Открывает страницу ежедневных наград и возвращает pageId.

        Returns:
            int or None: pageId для формирования AJAX URL
        """
        # Важно: нужно перейти именно на /dailyrewardevent,
        # а не на /city - иначе HTML не содержит daily-box элементы!
        resp = self.client.get("/dailyrewardevent")
        if resp.status_code != 200:
            print(f"[DAILY] Ошибка загрузки /dailyrewardevent: {resp.status_code}")
            return None

        return self.client.get_page_id()

    def _build_reward_url(self, page_id, day):
        """
        Формирует AJAX URL для сбора награды определённого дня.

        Args:
            page_id: pageId из страницы
            day: Номер дня (1-7)

        Returns:
            str: URL для AJAX запроса
        """
        if day not in DAY_TO_POSITION:
            return None

        row, container = DAY_TO_POSITION[day]

        # Паттерн URL из Wicket.Ajax биндинга:
        # /city?{pageId}-1.IBehaviorListener.0-feedbackUsualBlock-eventPanels-0-eventPanel-blockReward-block-rowsList-{row}-rewardContainer-{col}-dailyBox-dailyBoxReward
        url = (
            f"{BASE_URL}/city?{page_id}-1.IBehaviorListener.0-"
            f"feedbackUsualBlock-eventPanels-0-eventPanel-blockReward-block-"
            f"rowsList-{row}-rewardContainer-{container}-dailyBox-dailyBoxReward"
        )
        return url

    def find_available_reward_from_html(self):
        """
        Находит доступную награду по HTML (если класс _available присутствует).

        Returns:
            dict or None: Информация о награде
        """
        soup = self.client.soup()
        if not soup:
            return None

        # Ищем блок с _available
        available_box = None
        for box in soup.select("div.daily-box"):
            classes = box.get("class", [])
            if "_available" in classes:
                available_box = box
                break

        if not available_box:
            return None

        reward_info = {
            'day': None,
            'item_name': None,
            'item_rarity': None,
        }

        # День награды
        day_div = available_box.select_one("div.day-title")
        if day_div:
            for cls in day_div.get("class", []):
                if cls.startswith("_day"):
                    try:
                        reward_info['day'] = int(cls.replace("_day", ""))
                    except ValueError:
                        pass

        # Название предмета
        prize_name = available_box.select_one("div.daily-box-prize-name")
        if prize_name:
            rarity_span = prize_name.select_one("span[class*='i']")
            if rarity_span:
                reward_info['item_name'] = rarity_span.get_text(strip=True)
                for cls in rarity_span.get("class", []):
                    if cls.startswith("i") and cls != "i12":
                        reward_info['item_rarity'] = cls
                        break
            item_link = prize_name.select_one("a")
            if item_link:
                reward_info['item_name'] = item_link.get_text(strip=True)
                for cls in item_link.get("class", []):
                    if cls.startswith("i"):
                        reward_info['item_rarity'] = cls
                        break

        return reward_info if reward_info['day'] else None

    def find_available_reward_by_ajax(self, page_id):
        """
        Ищет доступную награду путём проверки AJAX URL для каждого дня.

        Args:
            page_id: pageId страницы

        Returns:
            dict or None: {'day': int, 'item_name': str or None}
        """
        print("[DAILY] Проверяю доступные награды через AJAX...")

        for day in range(1, 8):
            url = self._build_reward_url(page_id, day)
            if not url:
                continue

            # Делаем AJAX запрос
            resp = self.client.ajax_get(url)

            if resp.status_code != 200:
                continue

            # Проверяем ответ - если награда доступна, получим XML с успехом
            response_text = resp.text

            # Успешный сбор возвращает XML с обновлением элементов
            # Неуспешный - может вернуть ошибку или пустой ответ
            if "ajax-response" in response_text and "_received" in response_text:
                # Награда собрана! Парсим название из ответа
                item_name = self._parse_item_from_response(response_text)
                print(f"[DAILY] ✓ День {day} собран: {item_name or 'Unknown'}")
                return {'day': day, 'item_name': item_name, 'collected': True}

            # Если ответ содержит ошибку или награда недоступна
            if "error" in response_text.lower() or len(response_text) < 100:
                continue

        return None

    def _parse_item_from_response(self, response_text):
        """
        Парсит название предмета из AJAX ответа.

        Args:
            response_text: XML ответ от сервера

        Returns:
            str or None: Название предмета
        """
        # Ищем название в daily-box-prize-name
        match = re.search(
            r'daily-box-prize-name[^>]*>.*?<(?:span|a)[^>]*class="[^"]*i[A-Z][^"]*"[^>]*>([^<]+)',
            response_text,
            re.DOTALL
        )
        if match:
            return match.group(1).strip()

        # Альтернативный паттерн
        match = re.search(r'>([\w\s]+(?:Свиток|Подарок|Ящик|Сундук)[^<]*)<', response_text)
        if match:
            return match.group(1).strip()

        return None

    def try_collect_day(self, page_id, day):
        """
        Пробует собрать награду за конкретный день.

        Args:
            page_id: pageId страницы
            day: Номер дня (1-7)

        Returns:
            tuple: (success: bool, item_name: str or None)
        """
        url = self._build_reward_url(page_id, day)
        if not url:
            return False, None

        print(f"[DAILY] Пробую собрать день {day}...")
        resp = self.client.ajax_get(url)

        if resp.status_code != 200:
            print(f"[DAILY] День {day}: ошибка запроса ({resp.status_code})")
            return False, None

        response_text = resp.text

        # Проверяем успешность по наличию _received в ответе
        # (награда становится _received после сбора)
        if "ajax-response" in response_text:
            # Ищем признаки успешного сбора
            if "_received" in response_text or "daily-box-prize" in response_text:
                item_name = self._parse_item_from_response(response_text)
                return True, item_name

        return False, None

    def collect_reward(self, reward_info):
        """
        Собирает награду.

        Args:
            reward_info: Информация о награде

        Returns:
            bool: True если успешно собрано
        """
        if not reward_info:
            return False

        day = reward_info.get('day')
        item_name = reward_info.get('item_name', 'Unknown')

        if reward_info.get('collected'):
            # Уже собрано через find_available_reward_by_ajax
            print(f"[DAILY] ✓ Собрано: День {day} - {item_name}")
            self.rewards_collected += 1
            if item_name and item_name != 'Unknown':
                add_protected_item(item_name)
            return True

        # Нужно собрать
        page_id = self.client.get_page_id()
        if not page_id:
            print("[DAILY] Не удалось получить pageId")
            return False

        success, _ = self.try_collect_day(page_id, day)
        if success:
            # Используем item_name из reward_info (спарсен из _available до сбора),
            # а не из AJAX ответа (там может быть название другого дня)
            print(f"[DAILY] ✓ Собрано: День {day} - {item_name}")
            self.rewards_collected += 1
            if item_name and item_name != 'Unknown':
                add_protected_item(item_name)
            return True

        print(f"[DAILY] ✗ Не удалось собрать день {day}")
        return False

    def close_modal(self):
        """
        Закрывает модал ежедневных наград.

        Returns:
            bool: True если успешно закрыт
        """
        soup = self.client.soup()
        if not soup:
            return False

        # Ищем кнопку закрытия
        close_link = soup.select_one("a.popup-close")
        if close_link:
            href = close_link.get("href")
            if href:
                url = urljoin(self.client.current_url, href)
                self.client.get(url)
                return True

        return False

    def check_and_collect(self, force=False):
        """
        Основная функция - проверяет и собирает ежедневную награду.

        Args:
            force: Принудительно проверить (игнорировать кэш)

        Returns:
            dict: {
                'collected': bool,
                'item_name': str or None,
                'day': int or None,
                'skipped': bool  # True если пропущено из-за кэша
            }
        """
        result = {
            'collected': False,
            'item_name': None,
            'day': None,
            'skipped': False
        }

        # Проверяем кэш - может сегодня уже собирали
        if not force and is_reward_collected_today():
            print("[DAILY] Награда уже собрана сегодня (кэш)")
            result['skipped'] = True
            return result

        print("[DAILY] Проверяю ежедневные награды...")

        # Получаем pageId
        page_id = self.open_daily_rewards_modal()
        if not page_id:
            print("[DAILY] Не удалось получить pageId")
            return result

        print(f"[DAILY] PageId: {page_id}")

        # Сначала пробуем найти по HTML (если _available присутствует)
        reward = self.find_available_reward_from_html()

        if reward:
            print(f"[DAILY] Найдена награда в HTML: день {reward.get('day')}")
            result['item_name'] = reward.get('item_name')
            result['day'] = reward.get('day')

            if self.collect_reward(reward):
                result['collected'] = True
                mark_reward_collected()
                return result

        # Если не нашли в HTML - пробуем через AJAX brute-force
        print("[DAILY] Пробую найти награду через AJAX...")
        reward = self.find_available_reward_by_ajax(page_id)

        if reward:
            result['day'] = reward.get('day')
            result['item_name'] = reward.get('item_name')
            result['collected'] = reward.get('collected', False)

            if result['collected']:
                # Награда уже собрана в find_available_reward_by_ajax
                if result['item_name'] and result['item_name'] != 'Unknown':
                    add_protected_item(result['item_name'])
                mark_reward_collected()
                self.rewards_collected += 1
        else:
            print("[DAILY] Нет доступных наград для сбора")
            # Если наград нет - значит уже собрали, помечаем в кэш
            mark_reward_collected()

        return result


# ============================================
# Великая Библиотека (ежедневная бесплатная книга)
# ============================================

def get_library_cache_file():
    """Возвращает путь к файлу кэша библиотеки"""
    profile_dir = config.PROFILE_DIR
    if profile_dir:
        return os.path.join(profile_dir, "library_cache.json")
    return "library_cache.json"


def is_library_collected_today():
    """Проверяет, была ли уже открыта книга сегодня (по МСК)."""
    cache_file = get_library_cache_file()
    try:
        if not os.path.exists(cache_file):
            return False
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_collected = data.get("last_collected")
        if not last_collected:
            return False
        last_date = datetime.fromisoformat(last_collected)
        now_msk = datetime.now(MSK)
        return last_date.date() >= now_msk.date()
    except (json.JSONDecodeError, IOError, ValueError):
        return False


def mark_library_collected():
    """Записывает в кэш что книга открыта сегодня."""
    cache_file = get_library_cache_file()
    now_msk = datetime.now(MSK)
    data = {
        "last_collected": now_msk.isoformat(),
        "last_collected_readable": now_msk.strftime("%Y-%m-%d %H:%M:%S MSK")
    }
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError:
        pass


class LibraryClient:
    """Клиент для сбора ежедневной книги в Великой Библиотеке"""

    def __init__(self, client):
        self.client = client

    def check_and_collect(self):
        """Проверяет и открывает бесплатную книгу.

        ВАЖНО: без ключа клик стоит 50 золота! Проверяем ключи перед кликом.

        Returns:
            bool: True если книга открыта
        """
        if is_library_collected_today():
            log_debug("[LIBRARY] Книга уже собрана сегодня (кэш)")
            return False

        log_info("[LIBRARY] Проверяю Великую Библиотеку...")

        # Переходим на страницу библиотеки
        resp = self.client.get(f"{BASE_URL}/dailygifts")
        html = self.client.current_page or ""

        # Проверяем количество ключей
        # Паттерн: "У тебя <span class="i_book_key"></span> N"
        key_match = re.search(
            r'<span class="i_book_key"></span>\s*(\d+)',
            html
        )

        if not key_match:
            log_warning("[LIBRARY] Счётчик ключей не найден, пропускаю")
            # Не помечаем как собранное — может страница не загрузилась
            return False

        keys = int(key_match.group(1))
        if keys < 1:
            log_info("[LIBRARY] Ключей: 0, пропускаю (клик без ключа стоит 50 золота!)")
            mark_library_collected()
            return False

        log_info(f"[LIBRARY] Ключей: {keys}")

        # Ищем ссылки на книги
        book_links = re.findall(
            r'<a class="book_link" href="([^"]*ppAction=roll[^"]*)"',
            html
        )
        if not book_links:
            log_warning("[LIBRARY] Книги не найдены на странице")
            return False

        # Выбираем случайную книгу
        book_href = random.choice(book_links).replace("&amp;", "&")
        if not book_href.startswith("http"):
            book_href = urljoin(self.client.current_url, book_href)

        num_match = re.search(r'num=(\d+)', book_href)
        book_num = num_match.group(1) if num_match else "?"

        log_info(f"[LIBRARY] Открываю книгу #{book_num}...")
        self.client.get(book_href)

        mark_library_collected()
        log_info(f"[LIBRARY] Книга #{book_num} открыта!")
        return True


def test_daily_rewards(client, collect=False):
    """
    Тест модуля ежедневных наград.

    Args:
        client: VMMOClient
        collect: Если True - попытается собрать награду
    """
    print("=" * 50)
    print("VMMO Daily Rewards Test")
    print("=" * 50)

    # Проверяем кэш
    print(f"\n[*] Файл кэша: {get_daily_rewards_cache_file()}")
    print(f"[*] Награда собрана сегодня (кэш): {is_reward_collected_today()}")

    daily = DailyRewardsClient(client)

    # Идём в город и получаем pageId
    print("\n[*] Загружаю город...")
    page_id = daily.open_daily_rewards_modal()
    print(f"[*] PageId: {page_id}")

    if not page_id:
        print("[ERR] Не удалось получить pageId")
        return

    # Проверяем наличие награды на главной
    has_reward = daily.has_daily_reward_available()
    print(f"[*] Есть ссылка на dailyrewardevent: {has_reward}")

    # Пробуем найти через HTML
    print("\n[*] Ищу награду через HTML...")
    reward = daily.find_available_reward_from_html()
    if reward:
        print(f"[*] Найдена награда в HTML:")
        print(f"    День: {reward.get('day')}")
        print(f"    Предмет: {reward.get('item_name')}")
    else:
        print("[*] В HTML не найдено (класс _available отсутствует)")

    if collect:
        print("\n[*] Собираю награду...")
        result = daily.check_and_collect(force=True)
        print(f"\n[RESULT]:")
        print(f"    Собрано: {result['collected']}")
        print(f"    День: {result['day']}")
        print(f"    Предмет: {result['item_name']}")
    else:
        # Просто показываем какие дни теоретически можно попробовать
        print("\n[*] URL для каждого дня:")
        for day in range(1, 8):
            url = daily._build_reward_url(page_id, day)
            print(f"    День {day}: {url}")

        print("\n[*] Сбор пропущен (используй --collect для сбора)")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Test daily rewards")
    parser.add_argument("--profile", "-p", default="char2", help="Profile name (default: char2)")
    parser.add_argument("--collect", "-c", action="store_true", help="Actually collect the reward")
    args = parser.parse_args()

    # Устанавливаем профиль
    from requests_bot.config import set_profile
    try:
        set_profile(args.profile)
        print(f"[*] Профиль: {args.profile}")
    except Exception as e:
        print(f"[ERR] Ошибка профиля: {e}")
        sys.exit(1)

    from requests_bot.client import VMMOClient

    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            exit(1)

    test_daily_rewards(client, collect=args.collect)
