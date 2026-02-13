# ============================================
# VMMO Party Dungeon Coordination Module
# ============================================
# Координация ботов для совместного прохождения
# пати-данжей (Пороги Шэдоу Гарда и др.)
# ============================================

import os
import re
import json
import time
from urllib.parse import urljoin

from requests_bot.craft_prices import FileLock
from requests_bot.config import get_profile_name, get_profile_username, get_party_dungeon_config
from requests_bot.logger import log_info, log_debug, log_warning, log_error

BASE_URL = "https://vmmo.vten.ru"
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Файлы координации
PARTY_STATE_FILE = os.path.join(SCRIPT_DIR, "shared_party_state.json")
PARTY_LOCK_FILE = os.path.join(SCRIPT_DIR, "shared_party_state.lock")

# Таймауты
FORMING_TIMEOUT = 120      # 2 мин на сбор пати
INVITE_TIMEOUT = 60        # 60с на accept инвайта
LOBBY_TIMEOUT = 90         # 90с ожидание в лобби
COMBAT_TIMEOUT = 600       # 10 мин на бой
POLL_INTERVAL = 5          # Интервал проверки файла

# Пати-данжены
PARTY_DUNGEONS = {
    "dng:ShadowGuard": {
        "name": "Пороги Шэдоу Гарда",
        "url_id": "ShadowGuard",
        "max_members": 5,
        "tab": "tab2",
    },
    "dng:Underlight": {
        "name": "Логово Кобольдов",
        "url_id": "Underlight",
        "max_members": 4,
        "tab": "tab2",
    },
    "dng:CitadelHolding": {
        "name": "Крепость Холдинг",
        "url_id": "CitadelHolding",
        "max_members": 4,
        "tab": "tab2",
    },
}


# ============================================
# Файловая координация (shared_party_state.json)
# ============================================

def _load_state():
    if not os.path.exists(PARTY_STATE_FILE):
        return {"parties": [], "cooldowns": {}}
    try:
        with open(PARTY_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"parties": [], "cooldowns": {}}


def _save_state(state):
    with open(PARTY_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _cleanup_stale(state):
    """Удаляет зависшие пати по таймаутам."""
    now = time.time()
    alive = []
    for p in state["parties"]:
        age = now - p.get("created_at", 0)
        updated_age = now - p.get("updated_at", 0)
        s = p.get("state", "")

        if s == "forming" and age > FORMING_TIMEOUT:
            continue
        if s == "inviting" and age > FORMING_TIMEOUT + INVITE_TIMEOUT:
            continue
        if s == "ready" and updated_age > LOBBY_TIMEOUT:
            continue
        if s == "in_combat" and updated_age > COMBAT_TIMEOUT:
            continue
        if s == "completed":
            continue
        alive.append(p)
    state["parties"] = alive


def _find_party(state, party_id):
    for p in state["parties"]:
        if p["id"] == party_id:
            return p
    return None


def is_on_cooldown(profile, dungeon_id="dng:ShadowGuard"):
    """Проверяет КД данжа из shared state."""
    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
    except Exception:
        return False
    key = f"{profile}:{dungeon_id}"
    cd_until = state.get("cooldowns", {}).get(key, 0)
    return time.time() < cd_until


def is_in_party(profile):
    """Проверяет не состоит ли бот уже в пати."""
    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
            _cleanup_stale(state)
    except Exception:
        return False
    for p in state["parties"]:
        if profile in p.get("members", {}):
            return True
    return False


def can_join_party(profile, dungeon_id):
    """Может ли бот участвовать в пати."""
    if is_on_cooldown(profile, dungeon_id):
        return False
    if is_in_party(profile):
        return False
    return True


def try_join_or_create_party(profile, username, dungeon_id, difficulty="impossible", target_members=2):
    """Атомарно: найти FORMING пати и вступить, или создать новую.

    Returns:
        dict: {"id": ..., "role": "leader"|"member", "party": {...}} или None
    """
    dungeon_cfg = PARTY_DUNGEONS.get(dungeon_id)
    if not dungeon_cfg:
        return None

    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
            _cleanup_stale(state)

            # Уже в пати?
            for p in state["parties"]:
                if profile in p.get("members", {}):
                    return None

            # Ищем FORMING пати для этого данжа
            for p in state["parties"]:
                if (p.get("dungeon_id") == dungeon_id and
                        p.get("state") == "forming" and
                        len(p.get("members", {})) < target_members):
                    p["members"][profile] = {
                        "role": "member",
                        "username": username,
                        "status": "waiting_invite",
                        "joined_at": time.time(),
                    }
                    p["updated_at"] = time.time()
                    _save_state(state)
                    return {"id": p["id"], "role": "member", "party": p}

            # Нет подходящей — создаём новую
            party_id = f"party_{int(time.time())}_{profile}"
            new_party = {
                "id": party_id,
                "dungeon_id": dungeon_id,
                "difficulty": difficulty,
                "state": "forming",
                "leader": profile,
                "leader_username": username,
                "members": {
                    profile: {
                        "role": "leader",
                        "username": username,
                        "status": "creating",
                        "joined_at": time.time(),
                    }
                },
                "created_at": time.time(),
                "updated_at": time.time(),
                "target_members": target_members,
            }
            state["parties"].append(new_party)
            _save_state(state)
            return {"id": party_id, "role": "leader", "party": new_party}
    except Exception as e:
        log_error(f"[PARTY] Ошибка координации: {e}")
        return None


def update_member_status(profile, party_id, status):
    """Обновляет статус бота в пати."""
    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
            party = _find_party(state, party_id)
            if party and profile in party["members"]:
                party["members"][profile]["status"] = status
                party["updated_at"] = time.time()
                _save_state(state)
    except Exception as e:
        log_error(f"[PARTY] Ошибка update_member_status: {e}")


def update_party_state(party_id, new_state):
    """Обновляет состояние пати."""
    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
            party = _find_party(state, party_id)
            if party:
                party["state"] = new_state
                party["updated_at"] = time.time()
                _save_state(state)
    except Exception as e:
        log_error(f"[PARTY] Ошибка update_party_state: {e}")


def get_party_members(party_id):
    """Возвращает список мемберов пати."""
    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
            party = _find_party(state, party_id)
            if party:
                return dict(party.get("members", {}))
    except Exception:
        pass
    return {}


def wait_for_members(party_id, target_count, timeout=FORMING_TIMEOUT):
    """Лидер ждёт пока наберётся нужное число мемберов.

    Returns:
        "ready" — все собрались
        "timeout" — не набрали за таймаут
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        members = get_party_members(party_id)
        if len(members) >= target_count:
            return "ready"
        remaining = int(deadline - time.time())
        if remaining % 15 == 0 and remaining > 0:
            log_debug(f"[PARTY] Лидер: жду мемберов ({len(members)}/{target_count}), осталось {remaining}с")
        time.sleep(POLL_INTERVAL)
    return "timeout"


def wait_for_all_in_lobby(party_id, timeout=LOBBY_TIMEOUT):
    """Ждёт пока все мемберы будут в статусе 'in_lobby'.

    Returns:
        "ready" — все в лобби
        "timeout" — не все зашли
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        members = get_party_members(party_id)
        if members and all(m.get("status") == "in_lobby" for m in members.values()):
            return "ready"
        time.sleep(POLL_INTERVAL)
    return "timeout"


def leave_party(profile, party_id):
    """Убирает бота из пати. Если лидер — отменяет пати."""
    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
            party = _find_party(state, party_id)
            if not party:
                _save_state(state)
                return
            if party.get("leader") == profile:
                # Лидер уходит — отменяем пати
                state["parties"] = [p for p in state["parties"] if p["id"] != party_id]
            else:
                party["members"].pop(profile, None)
                party["updated_at"] = time.time()
            _save_state(state)
    except Exception as e:
        log_error(f"[PARTY] Ошибка leave_party: {e}")


def record_cooldown(profile, dungeon_id, seconds=4 * 3600):
    """Записывает КД данжа."""
    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
            key = f"{profile}:{dungeon_id}"
            state.setdefault("cooldowns", {})[key] = time.time() + seconds
            _save_state(state)
    except Exception as e:
        log_error(f"[PARTY] Ошибка record_cooldown: {e}")


def mark_completed(party_id):
    """Помечает пати как завершённую (будет удалена при cleanup)."""
    update_party_state(party_id, "completed")


# ============================================
# Игровые действия (HTTP)
# ============================================

class PartyDungeonClient:
    """Выполняет игровые действия для пати-данжа."""

    def __init__(self, client, dungeon_id):
        self.client = client
        self.dungeon_id = dungeon_id
        self.dungeon_cfg = PARTY_DUNGEONS.get(dungeon_id, {})
        self.url_id = self.dungeon_cfg.get("url_id", "")
        self.base_url = BASE_URL

    # === Лидер ===

    def enter_as_leader(self, difficulty="impossible"):
        """Лидер: landing → 'Войти' → lobby.

        Returns:
            bool: True если успешно в лобби
        """
        # 1. Переходим на landing
        landing_url = f"{self.base_url}/dungeon/landing/{self.url_id}/{difficulty}"
        log_info(f"[PARTY] Лидер: landing {landing_url}")
        resp = self.client.get(landing_url)
        html = self.client.current_page or ""

        # 2. Ищем createPartyOrEnterLink
        match = re.search(
            r'href="([^"]*createPartyOrEnterLink[^"]*)"',
            html
        )
        if not match:
            log_warning("[PARTY] Не найдена кнопка 'Войти' (createPartyOrEnterLink)")
            return False

        enter_url = match.group(1).replace("&amp;", "&")
        if not enter_url.startswith("http"):
            enter_url = urljoin(self.client.current_url, enter_url)

        log_info("[PARTY] Лидер: кликаю 'Войти'")
        self.client.get(enter_url)
        time.sleep(0.5)

        # 3. Проверяем что в лобби
        current = self.client.current_url or ""
        if "/dungeon/lobby/" in current or "/dungeon/standby/" in current:
            log_info("[PARTY] Лидер: в лобби!")
            return True

        log_warning(f"[PARTY] Лидер: не удалось попасть в лобби, URL: {current}")
        return False

    def invite_player(self, username):
        """Лидер: 'Поиск игроков' → ввод ника → отправка.

        Returns:
            bool: True если приглашение отправлено
        """
        html = self.client.current_page or ""

        # 1. Ищем ссылку "Поиск игроков"
        match = re.search(r'href="([^"]*party/search[^"]*)"', html)
        if not match:
            log_warning("[PARTY] Не найдена кнопка 'Поиск игроков'")
            return False

        search_url = match.group(1).replace("&amp;", "&")
        if not search_url.startswith("http"):
            search_url = urljoin(self.client.current_url, search_url)

        log_info("[PARTY] Лидер: 'Поиск игроков'")
        self.client.get(search_url)
        time.sleep(0.5)

        html = self.client.current_page or ""

        # 2. Ищем форму inviteForm
        form_match = re.search(
            r'action="([^"]*inviteForm[^"]*)"',
            html
        )
        if not form_match:
            log_warning("[PARTY] Не найдена форма inviteForm")
            return False

        form_url = form_match.group(1).replace("&amp;", "&")
        if not form_url.startswith("http"):
            form_url = urljoin(self.client.current_url, form_url)

        # 3. Отправляем POST с ником
        # Ищем hidden field
        hidden_match = re.search(r'name="([^"]*_hf_0)"', html)
        hidden_name = hidden_match.group(1) if hidden_match else ""

        data = {
            "p::name": username,
            "p::submit": "1",
        }
        if hidden_name:
            data[hidden_name] = ""

        log_info(f"[PARTY] Лидер: приглашаю '{username}'")

        resp = self.client.session.post(form_url, data=data, headers={
            **self.client.session.headers,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        time.sleep(0.5)

        # 4. Проверяем ответ
        resp_text = resp.text if resp else ""
        if "Приглашение отправлено" in resp_text:
            log_info(f"[PARTY] Лидер: приглашение отправлено для '{username}'!")
            # Обновляем текущую страницу
            self.client.get(self.client.current_url)
            return True

        # Может отображаться на перезагруженной странице
        self.client.get(self.client.current_url)
        html = self.client.current_page or ""
        if "Приглашение отправлено" in html:
            log_info(f"[PARTY] Лидер: приглашение отправлено для '{username}'!")
            return True

        log_warning("[PARTY] Лидер: не удалось отправить приглашение")
        return False

    def _find_feedback_url(self, html, action):
        """Ищет URL feedbackAction в HTML и JS-контенте.

        Уведомления рендерятся через JS (Ptx.Shadows.Notice.show),
        поэтому URL лежит внутри escaped JSON: href=\"URL\"

        Args:
            html: HTML страницы
            action: "accept", "decline", "enterDungeon"

        Returns:
            str|None: готовый URL или None
        """
        target = f"feedbackAction={action}"

        # 1. Обычный HTML: href="...feedbackAction=accept..."
        match = re.search(
            rf'href="([^"]*{re.escape(target)}[^"]*)"',
            html
        )

        # 2. JS-escaped (Notice.show JSON): href=\"...feedbackAction=accept...\"
        if not match:
            match = re.search(
                rf'href=\\"([^"\\]*{re.escape(target)}[^"\\]*)\\"',
                html
            )

        if not match:
            return None

        url = match.group(1).replace("&amp;", "&")
        # Куки привязаны к vmmo.vten.ru, а уведомления содержат m.vten.ru
        url = url.replace("https://m.vten.ru", self.base_url)

        if not url.startswith("http"):
            url = urljoin(self.client.current_url, url)

        return url

    def enter_dungeon_feedback(self):
        """Нажимает 'Войти в подземелье' (feedbackAction=enterDungeon).

        Returns:
            bool: True если нажали
        """
        html = self.client.current_page or ""
        url = self._find_feedback_url(html, "enterDungeon")

        if not url:
            # Пробуем обновить страницу
            self.client.get(self.client.current_url)
            time.sleep(0.5)
            html = self.client.current_page or ""
            url = self._find_feedback_url(html, "enterDungeon")

        if not url:
            log_debug("[PARTY] Не найдена кнопка 'Войти в подземелье'")
            return False

        log_info("[PARTY] Клик 'Войти в подземелье'")
        self.client.get(url)
        time.sleep(0.5)
        return True

    def start_combat(self, difficulty="impossible"):
        """Лидер: нажимает 'Начать бой!' через Wicket AJAX.

        Паттерн URL: IBehaviorListener.0-lobby-dungeon-blockStart-linkStartCombat

        Returns:
            bool: True если бой начался
        """
        html = self.client.current_page or ""

        # Ищем linkStartCombat в скриптах или Wicket AJAX
        match = re.search(
            r'"u":"([^"]*linkStartCombat[^"]*)"',
            html
        )
        if match:
            ajax_url = match.group(1).replace("\\", "")
            if not ajax_url.startswith("http"):
                ajax_url = urljoin(self.client.current_url, ajax_url)
            log_info("[PARTY] Лидер: 'Начать бой!' (AJAX)")
            headers = {
                "Wicket-Ajax": "true",
                "Wicket-Ajax-BaseURL": self.client.current_url.replace(self.base_url, "").lstrip("/"),
                "X-Requested-With": "XMLHttpRequest",
            }
            resp = self.client.session.get(ajax_url, headers={**self.client.session.headers, **headers})
            time.sleep(1)
            # Проверяем редирект на combat
            self.client.get(self.client.current_url)
            if "/combat" in (self.client.current_url or ""):
                log_info("[PARTY] Бой начался!")
                return True

        # Фоллбек: ищем linkStartCombat в href
        match = re.search(
            r'href="([^"]*linkStartCombat[^"]*)"',
            html
        )
        if match:
            url = match.group(1).replace("&amp;", "&")
            if not url.startswith("http"):
                url = urljoin(self.client.current_url, url)
            log_info("[PARTY] Лидер: 'Начать бой!' (href)")
            self.client.get(url)
            time.sleep(1)
            if "/combat" in (self.client.current_url or ""):
                log_info("[PARTY] Бой начался!")
                return True

        # Фоллбек 2: строим URL из pageId
        page_match = re.search(r'pageId:\s*(\d+)', html)
        if page_match:
            page_id = page_match.group(1)
            lobby_base = self.client.current_url.split("?")[0]
            combat_url = f"{lobby_base}?{page_id}-1.IBehaviorListener.0-lobby-dungeon-blockStart-linkStartCombat&1={difficulty}"
            log_info("[PARTY] Лидер: 'Начать бой!' (constructed URL)")
            headers = {
                "Wicket-Ajax": "true",
                "Wicket-Ajax-BaseURL": self.client.current_url.replace(self.base_url, "").lstrip("/"),
                "X-Requested-With": "XMLHttpRequest",
            }
            resp = self.client.session.get(combat_url, headers={**self.client.session.headers, **headers})
            time.sleep(1)
            self.client.get(self.client.current_url)
            if "/combat" in (self.client.current_url or ""):
                log_info("[PARTY] Бой начался!")
                return True

        log_warning("[PARTY] Не удалось начать бой")
        return False

    def leave_lobby(self):
        """Покинуть банду."""
        html = self.client.current_page or ""
        match = re.search(r'href="([^"]*leaveParty[^"]*)"', html)
        if not match:
            # Пробуем из города
            self.client.get(f"{self.base_url}/city")
            time.sleep(0.5)
            html = self.client.current_page or ""
            match = re.search(r'href="([^"]*leaveParty[^"]*)"', html)

        if match:
            url = match.group(1).replace("&amp;", "&")
            if not url.startswith("http"):
                url = urljoin(self.client.current_url, url)
            log_info("[PARTY] Покидаем банду")
            self.client.get(url)
            time.sleep(0.5)
            return True

        log_debug("[PARTY] Кнопка 'Покинуть банду' не найдена")
        return False

    # === Мембер ===

    def check_and_accept_invite(self, leader_username):
        """Мембер: проверяет приглашение в городе и принимает.

        Уведомление рендерится через JS (Ptx.Shadows.Notice.show),
        поэтому URL извлекается из escaped JSON в <script> теге.

        Returns:
            bool: True если приглашение принято
        """
        # Переходим в город чтобы увидеть уведомление
        self.client.get(f"{self.base_url}/city")
        time.sleep(0.5)
        html = self.client.current_page or ""

        # Ищем notice с приглашением (текст есть в JS даже без рендеринга)
        if "приглашает тебя в банду" not in html:
            return False

        log_info("[PARTY] Мембер: вижу приглашение!")

        # Ищем URL принятия из HTML или JS-контента
        accept_url = self._find_feedback_url(html, "accept")
        if not accept_url:
            log_warning("[PARTY] Мембер: URL 'Принять' не найден в HTML")
            return False

        log_info(f"[PARTY] Мембер: принимаю приглашение от {leader_username}")
        self.client.get(accept_url)
        time.sleep(0.5)

        # После accept сервер может редиректить прямо в лобби
        current = self.client.current_url or ""
        if "/dungeon/lobby/" in current or "/dungeon/standby/" in current:
            log_info("[PARTY] Мембер: уже в лобби после accept!")
            return True

        # Иначе ищем кнопку "Войти в подземелье"
        return self.enter_dungeon_feedback()

    def wait_and_accept_invite(self, leader_username, timeout=INVITE_TIMEOUT):
        """Мембер: поллит город ожидая приглашение.

        Returns:
            bool: True если приглашение принято и вошёл в данж
        """
        deadline = time.time() + timeout
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            if attempt == 1:
                log_info(f"[PARTY] Мембер: жду инвайт от {leader_username} ({timeout}с)...")
            if self.check_and_accept_invite(leader_username):
                return True
            time.sleep(POLL_INTERVAL)

        log_warning(f"[PARTY] Мембер: таймаут ожидания приглашения ({timeout}с)")
        return False


# ============================================
# Главная функция координации
# ============================================

def run_party_dungeon(client, dungeon_runner, dungeon_id="dng:ShadowGuard", difficulty="impossible"):
    """Главная функция: координация + вход + бой.

    Вызывается из bot.py.

    Returns:
        "completed" — данж пройден
        "died" — погибли
        "timeout" — не собрали пати
        "error" — ошибка
        None — нет возможности (КД, уже в пати)
    """
    profile = get_profile_name()
    username = get_profile_username()

    if not can_join_party(profile, dungeon_id):
        return None

    dungeon_cfg = PARTY_DUNGEONS.get(dungeon_id)
    if not dungeon_cfg:
        return None

    # Кол-во мемберов берём из конфига профиля (по умолчанию 2)
    party_cfg = get_party_dungeon_config()
    target_members = party_cfg.get("members", 2)

    # Пробуем вступить или создать
    result = try_join_or_create_party(profile, username, dungeon_id, difficulty, target_members)
    if not result:
        return None

    party_id = result["id"]
    role = result["role"]
    party = result["party"]
    party_client = PartyDungeonClient(client, dungeon_id)

    log_info(f"[PARTY] {username}: role={role}, party={party_id}")

    try:
        if role == "leader":
            return _run_as_leader(
                profile, username, party_id, party_client,
                dungeon_runner, dungeon_id, difficulty, target_members
            )
        else:
            leader_username = party.get("leader_username", "")
            return _run_as_member(
                profile, username, party_id, party_client,
                dungeon_runner, dungeon_id, leader_username
            )
    except Exception as e:
        log_error(f"[PARTY] Ошибка: {e}")
        import traceback
        traceback.print_exc()
        party_client.leave_lobby()
        leave_party(profile, party_id)
        return "error"


def _run_as_leader(profile, username, party_id, party_client, dungeon_runner, dungeon_id, difficulty, target_members):
    """Логика лидера."""

    # 1. Входим в данж (создаём пати в игре)
    if not party_client.enter_as_leader(difficulty):
        leave_party(profile, party_id)
        return "error"

    update_member_status(profile, party_id, "in_lobby")
    update_party_state(party_id, "forming")

    # 2. Ждём пока мемберы появятся в JSON
    log_info(f"[PARTY] Лидер: жду {target_members - 1} мемберов...")
    wait_result = wait_for_members(party_id, target_members, timeout=FORMING_TIMEOUT)

    if wait_result != "ready":
        log_warning("[PARTY] Лидер: таймаут сбора, отменяю")
        party_client.leave_lobby()
        leave_party(profile, party_id)
        return "timeout"

    # 3. Инвайтим каждого мембера
    members = get_party_members(party_id)
    update_party_state(party_id, "inviting")

    for mem_profile, mem_info in members.items():
        if mem_profile == profile:
            continue
        mem_username = mem_info.get("username", "")
        if not mem_username:
            continue

        log_info(f"[PARTY] Лидер: инвайчу {mem_username}")

        # Возвращаемся в лобби для инвайта (если ушли на /party/search)
        if not party_client.invite_player(mem_username):
            log_warning(f"[PARTY] Лидер: не удалось пригласить {mem_username}")
            # Продолжаем с остальными

    # 4. Ждём пока все мемберы зайдут в лобби (status=in_lobby)
    log_info("[PARTY] Лидер: жду всех в лобби...")
    lobby_result = wait_for_all_in_lobby(party_id, timeout=LOBBY_TIMEOUT)

    if lobby_result != "ready":
        log_warning("[PARTY] Лидер: не все зашли в лобби, отменяю")
        party_client.leave_lobby()
        leave_party(profile, party_id)
        return "timeout"

    # 5. Нажимаем "Войти в подземелье" если есть
    party_client.enter_dungeon_feedback()
    time.sleep(1)

    # 6. Начинаем бой
    update_party_state(party_id, "ready")
    log_info("[PARTY] Лидер: все в лобби, начинаю бой!")

    if not party_client.start_combat(difficulty):
        log_warning("[PARTY] Лидер: не удалось начать бой")
        party_client.leave_lobby()
        leave_party(profile, party_id)
        return "error"

    # 7. Бой
    update_party_state(party_id, "in_combat")
    return _fight_dungeon(profile, party_id, party_client, dungeon_runner, dungeon_id)


def _run_as_member(profile, username, party_id, party_client, dungeon_runner, dungeon_id, leader_username):
    """Логика мембера."""

    # 1. Ждём приглашение и принимаем
    if not party_client.wait_and_accept_invite(leader_username, timeout=INVITE_TIMEOUT):
        log_warning("[PARTY] Мембер: не получил инвайт")
        leave_party(profile, party_id)
        return "timeout"

    # 2. Обновляем статус — мы в лобби
    update_member_status(profile, party_id, "in_lobby")
    log_info(f"[PARTY] Мембер {username}: в лобби!")

    # 3. Ждём начала боя (лидер стартует)
    deadline = time.time() + LOBBY_TIMEOUT
    while time.time() < deadline:
        current_url = party_client.client.current_url or ""
        if "/combat" in current_url:
            break

        # Обновляем страницу
        party_client.client.get(party_client.client.current_url)
        time.sleep(POLL_INTERVAL)
    else:
        log_warning("[PARTY] Мембер: таймаут ожидания боя")
        party_client.leave_lobby()
        leave_party(profile, party_id)
        return "timeout"

    # 4. Бой
    log_info(f"[PARTY] Мембер {username}: бой начался!")
    return _fight_dungeon(profile, party_id, party_client, dungeon_runner, dungeon_id)


def _fight_dungeon(profile, party_id, party_client, dungeon_runner, dungeon_id):
    """Общая логика боя (для лидера и мембера)."""
    dungeon_runner.current_dungeon_id = dungeon_id
    dungeon_runner.combat_url = dungeon_runner.client.current_url
    dungeon_runner._save_loot_url_from_combat_page()

    result, actions = dungeon_runner.fight_until_done()

    # Записываем КД
    record_cooldown(profile, dungeon_id)

    # Покидаем банду
    party_client.leave_lobby()
    leave_party(profile, party_id)

    # Помечаем завершение
    mark_completed(party_id)

    log_info(f"[PARTY] {profile}: бой окончен — {result}, {actions} действий")
    return result
