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
from requests_bot.config import get_profile_name, get_profile_username, get_game_nickname, get_party_dungeon_config
from requests_bot.logger import log_info, log_debug, log_warning, log_error

BASE_URL = "https://vmmo.vten.ru"
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Файлы координации
PARTY_STATE_FILE = os.path.join(SCRIPT_DIR, "shared_party_state.json")
PARTY_LOCK_FILE = os.path.join(SCRIPT_DIR, "shared_party_state.lock")

# Таймауты
FORMING_TIMEOUT = 180      # 3 мин на сбор пати — даёт запас на медленный цикл мембера в дневном режиме
INVITE_TIMEOUT = 60        # 60с на accept инвайта
LOBBY_TIMEOUT = 90         # 90с ожидание в лобби
COMBAT_TIMEOUT = 600       # 10 мин на бой
POLL_INTERVAL = 5          # Интервал проверки файла

# Пати-данжены
PARTY_DUNGEONS = {
    # Tab2: 1-29 уровень (все данжи)
    "dng:dSanctuary": {
        "name": "Святилище Накрила",
        "url_id": "dSanctuary",
        "max_members": 2,
        "tab": "tab2",
    },
    "dng:dHellRuins": {
        "name": "Адские Развалины",
        "url_id": "dHellRuins",
        "max_members": 3,
        "tab": "tab2",
    },
    "dng:RestMonastery": {
        "name": "Монастырь Покоя",
        "url_id": "RestMonastery",
        "max_members": 4,
        "tab": "tab2",
    },
    "dng:Underlight": {
        "name": "Логово Кобольдов",
        "url_id": "Underlight",
        "max_members": 4,
        "tab": "tab2",
    },
    "dng:HighDungeon": {
        "name": "Высокая Темница",
        "url_id": "HighDungeon",
        "max_members": 4,
        "tab": "tab2",
    },
    "dng:CitadelHolding": {
        "name": "Крепость Холдинг",
        "url_id": "CitadelHolding",
        "max_members": 4,
        "tab": "tab2",
    },
    "dng:way2Baron": {
        "name": "Путь к Барону",
        "url_id": "way2Baron",
        "max_members": 2,
        "tab": "tab2",
    },
    "dng:Barony": {
        "name": "Владения Барона",
        "url_id": "Barony",
        "max_members": 4,
        "tab": "tab2",
    },
    "dng:ShadowGuard": {
        "name": "Пороги Шэдоу Гарда",
        "url_id": "ShadowGuard",
        "max_members": 5,
        "tab": "tab2",
    },
    # Ивент
    "dng:14feb_DungeonForest": {
        "name": "Древний Лес",
        "url_id": "14feb_DungeonForest",
        "max_members": 2,
        "tab": "event",
    },
    # Текущий ивент Май 2026 — Огненная Башня (event-party).
    # Используется через run_event_party для координации (Пупупу + до 2 мемберов).
    "dng:FireTower": {
        "name": "Огненная Башня",
        "url_id": "FireTower",
        "max_members": 3,  # подтверждено в landing: "3чел."
        "tab": "event",
        "is_event": True,
        # КД проверяется через valentine_event.is_dungeon_on_cooldown_for_profile
        # (shared state) — а не через is_on_cooldown (которое читает party cooldowns).
        "event_dungeon_key": "FireTower",  # ключ в VALENTINE_DUNGEONS
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


def is_on_cooldown(profile, dungeon_id):
    """Проверяет КД данжа из shared state.

    Раньше был дефолт dungeon_id='dng:ShadowGuard' — это маскировало баги,
    когда вызывающий забывал передать конкретный данж. Теперь обязательный.
    """
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


def cleanup_own_stale_party(profile):
    """Если бот застрял в старой пати (не дошёл до лобби), выходим.

    Ситуация: бот создал/вступил в пати, но был остановлен.
    При перезапуске is_in_party() блокирует новую пати.
    """
    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
            for p in state["parties"]:
                if profile not in p.get("members", {}):
                    continue
                member = p["members"][profile]
                status = member.get("status", "")
                age = time.time() - member.get("joined_at", 0)

                # Если бот не в бою и завис дольше 30с — зависшая пати
                if status not in ("in_combat",) and age > 30:
                    log_info(f"[PARTY] Очистка зависшей пати {p['id']} (status={status}, age={int(age)}с)")
                    if p.get("leader") == profile:
                        state["parties"] = [pp for pp in state["parties"] if pp["id"] != p["id"]]
                    else:
                        p["members"].pop(profile, None)
                    _save_state(state)
                    return
    except Exception as e:
        log_error(f"[PARTY] Ошибка cleanup_own_stale_party: {e}")


def find_forming_party(profile):
    """Ищет FORMING пати, к которой бот может присоединиться.

    Возвращает пати dict или None. Проверяет КД бота для данжа пати.
    """
    try:
        with FileLock(PARTY_LOCK_FILE):
            state = _load_state()
            _cleanup_stale(state)

            # Уже в пати?
            for p in state["parties"]:
                if profile in p.get("members", {}):
                    return None

            # Ищем forming пати с местом и без КД у бота
            for p in state["parties"]:
                if p.get("state") != "forming":
                    continue
                target = p.get("target_members", 2)
                if len(p.get("members", {})) >= target:
                    continue
                if profile in p.get("members", {}):
                    continue
                # Проверяем КД бота для этого данжа
                dungeon_id = p.get("dungeon_id", "")
                key = f"{profile}:{dungeon_id}"
                cd_until = state.get("cooldowns", {}).get(key, 0)
                if time.time() < cd_until:
                    continue  # КД на этот данж — пропускаем
                return dict(p)
    except Exception:
        pass
    return None


def can_join_party(profile, dungeon_id):
    """Может ли бот участвовать в пати."""
    if is_on_cooldown(profile, dungeon_id):
        return False
    if is_in_party(profile):
        return False
    return True


def try_join_or_create_party(profile, username, dungeon_id, difficulty="impossible", target_members=2, only_join=False):
    """Атомарно: найти FORMING пати и вступить, или создать новую.

    only_join=True: только вступить в существующую (для роли member). Если
    forming пати нет — вернуть None, не создавать. Защищает от race-окна
    когда find_forming_party нашёл пати, но к моменту try_join... пати
    уже исчезла, и мембер случайно становится лидером.

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

            # only_join=True: мембер пришёл присоединиться, но forming уже нет — выходим
            if only_join:
                return None

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

        # === ПОЛНЫЙ ДИАГ-ЛОГ ===
        # Логируем всё что есть на момент POST: cookies, headers, body
        try:
            cookies_str = "; ".join(f"{c.name}={c.value[:40]}{'...' if len(c.value) > 40 else ''}"
                                     for c in self.client.session.cookies if "vten" in (c.domain or ""))
            log_info(f"[PARTY-DIAG] POST URL: {form_url}")
            log_info(f"[PARTY-DIAG] POST data: {data}")
            log_info(f"[PARTY-DIAG] Cookies (vten): {cookies_str[:300]}")
            ua = self.client.session.headers.get("User-Agent", "?")
            log_info(f"[PARTY-DIAG] UA: {ua}")
            log_info(f"[PARTY-DIAG] Current URL до POST: {self.client.current_url}")
        except Exception as e:
            log_debug(f"[PARTY-DIAG] log fail: {e}")

        log_info(f"[PARTY] Лидер: приглашаю '{username}'")

        post_headers = {
            **self.client.session.headers,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            log_info(f"[PARTY-DIAG] Request headers: {dict(post_headers)}")
        except Exception:
            pass
        resp = self.client.session.post(form_url, data=data, headers=post_headers)
        time.sleep(0.5)

        # 4. Проверяем ответ
        resp_text = resp.text if resp else ""

        # === ПОЛНЫЙ ДИАГ-ЛОГ RESPONSE ===
        try:
            log_info(
                f"[PARTY-DIAG] POST resp status={resp.status_code if resp else 'None'}, "
                f"len={len(resp_text)}, "
                f"final_url={resp.url if resp else 'None'}"
            )
            try:
                log_info(f"[PARTY-DIAG] Response headers: {dict(resp.headers)}")
            except Exception:
                pass
            log_info(f"[PARTY-DIAG] POST resp head[0:500]: {resp_text[:500]!r}")
            # Также ищем ключевые маркеры
            markers = {
                "has_invite_sent": "Приглашение отправлено" in resp_text,
                "has_already_pending": "уже имеет приглашение" in resp_text,  # КРИТИЧНО — invite в очереди
                "has_already_invited": "уже приглашён" in resp_text or "уже пригласил" in resp_text,
                "has_offline": "не в сети" in resp_text or "оффлайн" in resp_text.lower(),
                "has_not_found": "не найден" in resp_text,
                "has_error_panel": "feedbackPanelERROR" in resp_text,
                "has_doconfirm": "/doconfirm" in resp_text,
                "has_login_form": 'name="login"' in resp_text,
                "has_notice_show": "Notice.show" in resp_text,
                "has_pending_request": "pendingRequest" in resp_text or "ожидает" in resp_text,
            }
            if markers["has_already_pending"]:
                log_warning(
                    f"[PARTY] ⚠ Сервер: 'уже имеет приглашение' — pending invite "
                    f"висит у мембера, новый дропается. Ждать expire или мембер "
                    f"должен перелогиниться."
                )
            log_info(f"[PARTY-DIAG] Resp markers: {markers}")
            # Поиск Notice.show вызовов в JS — может там скрытое уведомление
            notice_matches = re.findall(r'Notice\.show\(\s*\{[^}]{0,500}', resp_text)
            if notice_matches:
                log_info(f"[PARTY-DIAG] Найдено {len(notice_matches)} Notice.show вызовов")
                for i, nm in enumerate(notice_matches[:3]):
                    log_info(f"[PARTY-DIAG] Notice #{i}: {nm[:300]}")
            # Дамп ПОЛНОГО ответа в файл
            try:
                import os as _os
                debug_dir = "/tmp/debug_party"
                _os.makedirs(debug_dir, exist_ok=True)
                ts = int(time.time())
                fname = f"{debug_dir}/invite_post_resp_{ts}.html"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(f"<!-- POST {form_url} -->\n")
                    f.write(f"<!-- data: {data} -->\n")
                    f.write(f"<!-- status: {resp.status_code if resp else 'None'} -->\n")
                    f.write(f"<!-- markers: {markers} -->\n")
                    f.write(resp_text)
                log_info(f"[PARTY-DIAG] Full POST response dumped: {fname}")
            except Exception as e:
                log_debug(f"[PARTY-DIAG] dump fail: {e}")
        except Exception as e:
            log_debug(f"[PARTY-DIAG] log resp fail: {e}")

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

        Логика портирована из run_dungeon._start_combat (вариант 4 Wicket AJAX):
        Wicket возвращает XML с <redirect>URL</redirect> — нужно по нему перейти.

        КРИТИЧНО: после invite_player лидер остаётся на /party/search, а не в лобби.
        Поэтому первым делом явно идём в /dungeon/lobby/{url_id}.

        Returns:
            bool: True если бой начался
        """
        # Явно идём в лобби — после invite_player current_url = /party/search,
        # а кнопка "Начать бой" есть только в lobby.
        lobby_url = f"{self.base_url}/dungeon/lobby/{self.url_id}"
        log_debug(f"[PARTY] Лидер: иду в лобби {lobby_url}")
        self.client.get(lobby_url)
        time.sleep(0.5)

        html = self.client.current_page or ""

        # 1. AJAX вариант — ищем "u":"...linkStartCombat..." в JS
        match = re.search(r'"u":"([^"]*linkStartCombat[^"]*)"', html)
        if match:
            ajax_url = match.group(1).replace("\\", "")
            if not ajax_url.startswith("http"):
                ajax_url = urljoin(self.client.current_url, ajax_url)

            base_path = self.client.current_url.split("?")[0].replace(self.base_url, "")
            headers = {
                "Wicket-Ajax": "true",
                "Wicket-Ajax-BaseURL": base_path.lstrip("/"),
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/xml, text/xml, */*; q=0.01",
            }
            log_info("[PARTY] Лидер: 'Начать бой!' (AJAX)")
            resp = self.client.session.get(ajax_url, headers={**self.client.session.headers, **headers})

            if resp.status_code == 200 and ("xml" in resp.headers.get("Content-Type", "") or "<ajax-response" in resp.text):
                # Ищем redirect в XML ответе
                redirect_match = re.search(r'<redirect>\s*<!\[CDATA\[([^]]+)\]\]>\s*</redirect>', resp.text)
                if not redirect_match:
                    redirect_match = re.search(r'<redirect>([^<]+)</redirect>', resp.text)
                if redirect_match:
                    combat_url = redirect_match.group(1).strip()
                    if not combat_url.startswith("http"):
                        combat_url = urljoin(self.client.current_url, combat_url)
                    log_info(f"[PARTY] Лидер: redirect → combat")
                    self.client.get(combat_url)
                    if "/combat" in (self.client.current_url or ""):
                        log_info("[PARTY] Бой начался!")
                        return True

                # Ищем "Loading content for ..."
                load_match = re.search(r"Loading content for .*?'([^']+)'", resp.text)
                if load_match:
                    combat_url = load_match.group(1)
                    if not combat_url.startswith("http"):
                        combat_url = urljoin(self.client.current_url, combat_url)
                    log_info(f"[PARTY] Лидер: loading combat URL")
                    self.client.get(combat_url)
                    if "/combat" in (self.client.current_url or ""):
                        log_info("[PARTY] Бой начался!")
                        return True

            # AJAX отработал, но без redirect — возможно сервер просто обновил DOM.
            # Перезагружаем lobby URL и проверяем не редиректнуло ли на combat.
            time.sleep(1)
            self.client.get(self.client.current_url)
            if "/combat" in (self.client.current_url or ""):
                log_info("[PARTY] Бой начался (после reload)!")
                return True

        # 2. Фоллбек href
        match = re.search(r'href="([^"]*linkStartCombat[^"]*)"', html)
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

        # Если мы здесь — кнопка не найдена в HTML.
        # Раньше был фолбек с constructed URL по pageId — он не работал
        # (формат игры изменился). Удалён, чтобы не вводить в заблуждение лог.
        log_warning(f"[PARTY] Не удалось начать бой. URL: {self.client.current_url}")

        # Сохраняем HTML для диагностики
        try:
            import os as _os
            from requests_bot.config import SCRIPT_DIR as _SCRIPT_DIR
            debug_path = _os.path.join(_SCRIPT_DIR, "debug_party_no_combat.html")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            log_debug(f"[PARTY] HTML dump: {debug_path}")
        except Exception:
            pass

        return False

    def leave_lobby(self):
        """Покинуть банду.

        ВАЖНО: после клика leaveParty сервер кидает на /doconfirm — там надо
        ещё раз нажать 'Да, точно' (a.go-btn → /city?ppAction=leaveParty).
        Без этого банда остаётся активной → бот не может войти в новые данжи.
        Кейс 2026-05-01: char25 после ивента застрял в банде, CYCLE 10
        попыток войти в обычные данжи все 'кнопка входа не найдена'.
        """
        html = self.client.current_page or ""
        match = re.search(r'href="([^"]*leaveParty[^"]*)"', html)
        if not match:
            self.client.get(f"{self.base_url}/city")
            time.sleep(0.5)
            html = self.client.current_page or ""
            match = re.search(r'href="([^"]*leaveParty[^"]*)"', html)

        if not match:
            log_debug("[PARTY] Кнопка 'Покинуть банду' не найдена")
            return False

        url = match.group(1).replace("&amp;", "&")
        if not url.startswith("http"):
            url = urljoin(self.client.current_url, url)
        log_info("[PARTY] Покидаем банду (шаг 1: клик leaveParty)")
        self.client.get(url)
        time.sleep(0.5)

        # Шаг 2: подтверждение если попали на /doconfirm
        if "/doconfirm" in (self.client.current_url or ""):
            self._confirm_doconfirm("Да, точно")

        return True

    def _confirm_doconfirm(self, button_text="Да, точно") -> bool:
        """Нажимает кнопку подтверждения на /doconfirm странице.

        Структура: <a class="go-btn">Да, точно</a> — ведёт на действие.
        <a class="go-btn _night">Нет, отмена</a> — ведёт обратно.
        """
        soup = self.client.soup()
        if not soup:
            return False
        for a in soup.select("a.go-btn"):
            if a.get_text(strip=True) == button_text:
                href = a.get("href", "").replace("&amp;", "&")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = urljoin(self.client.current_url, href)
                log_info(f"[PARTY] Подтверждение doconfirm: '{button_text}'")
                self.client.get(href)
                time.sleep(0.5)
                return True
        log_warning(f"[PARTY] Не нашёл кнопку '{button_text}' на doconfirm")
        return False

    # === Мембер ===

    def _extract_inviter_name(self, html):
        """Извлекает имя пригласившего из notice HTML.

        Формат: <span>ИМЯ</span> приглашает тебя в банду
        Или escaped: <span>ИМЯ<\\/span> приглашает тебя в банду
        """
        # Обычный HTML
        m = re.search(r'<span>([^<]+)</span>\s*приглашает тебя в банду', html)
        if m:
            return m.group(1).strip()
        # JS-escaped
        m = re.search(r'<span>([^<]+)<\\/span>\s*приглашает тебя в банду', html)
        if m:
            return m.group(1).strip()
        # Ещё вариант escaped
        m = re.search(r'<span>([^<]+)<\\\/span>\s*приглашает тебя в банду', html)
        if m:
            return m.group(1).strip()
        return None

    def check_and_accept_invite(self, leader_username, page="city", attempt=0):
        """Мембер: проверяет приглашение на странице и принимает.

        Уведомление рендерится через JS (Ptx.Shadows.Notice.show),
        поэтому URL извлекается из escaped JSON в <script> теге.
        Принимает ТОЛЬКО приглашение от своего лидера.

        Returns:
            tuple[bool, dict]: (нашли и приняли инвайт, диагностические маркеры)
        """
        # Cache-busting чтобы сервер/прокси не отдавали закешированную версию.
        # Также явный no-cache header.
        url = f"{self.base_url}/{page}?_={int(time.time() * 1000)}"
        try:
            self.client.session.headers["Cache-Control"] = "no-cache"
            self.client.session.headers["Pragma"] = "no-cache"
            self.client.get(url)
        finally:
            self.client.session.headers.pop("Cache-Control", None)
            self.client.session.headers.pop("Pragma", None)
        time.sleep(0.5)
        html = self.client.current_page or ""
        current_url = self.client.current_url or ""

        # Ищем notice с приглашением (текст есть в JS даже без рендеринга)
        has_invite = "приглашает тебя в банду" in html
        has_feedback = "feedbackAction=accept" in html

        # Диагностические маркеры всегда считаем (для возврата)
        markers = {
            "size": len(html),
            "url": current_url[:120],
            "has_invite_text": has_invite,
            "has_feedback_accept": has_feedback,
            "has_notice_js": "Ptx.Shadows.Notice" in html,
            "has_feedback_anywhere": "feedbackAction" in html,
            "has_party_word": ("банду" in html or "банда" in html),
            "has_leader_name": (leader_username in html) if leader_username else False,
            "has_login_form": ('name="login"' in html or "Вход в аккаунт" in html),
            # Доп. маркеры — что-нибудь push-related серверу всё-таки могло упасть
            "has_notice_show": "Notice.show" in html,
            "has_pending": "pendingRequest" in html or "ожидает" in html,
            "has_inviter": "приглашает" in html,  # без 'тебя в банду' тоже учитываем
            "has_acceptlink": "accept" in html.lower(),
        }

        # Логируем КАЖДУЮ попытку на INFO — это разовое расследование.
        # После того как баг найден — снизить до debug.
        log_info(f"[PARTY-DBG] invite-poll #{attempt} /{page}: {markers}")

        # Поиск ВСЕХ Notice.show вызовов в HTML — даже если не про банду,
        # это покажет что сервер пушит на эту сессию что-то другое
        notice_calls = re.findall(r'Notice\.show\(\s*\{[^}]{0,500}', html)
        if notice_calls:
            log_info(f"[PARTY-DBG] /{page} имеет {len(notice_calls)} Notice.show вызов(а)")
            for i, nc in enumerate(notice_calls[:2]):
                log_info(f"[PARTY-DBG]   notice #{i}: {nc[:300]}")

        if not has_invite and not has_feedback:
            # Дамп HTML только при подозрительных состояниях:
            #  - login_form (нас разлогинило)
            #  - notice есть, но не про банду (инвайт другого формата?)
            #  - первая попытка после ожидаемого invite (attempt 2-3)
            should_dump = (
                markers["has_login_form"]
                or (markers["has_notice_js"] and not markers["has_party_word"])
                or attempt in (2, 3)
            )
            if should_dump:
                try:
                    import os
                    from requests_bot.config import get_profile_name
                    debug_dir = "/tmp/debug_party"
                    os.makedirs(debug_dir, exist_ok=True)
                    safe_page = page.replace("/", "_")
                    profile = get_profile_name() or "unknown"
                    fname = f"{debug_dir}/invite_{profile}_{safe_page}_a{attempt}_{int(time.time())}.html"
                    with open(fname, "w", encoding="utf-8") as f:
                        f.write(f"<!-- URL: {current_url} -->\n")
                        f.write(f"<!-- Attempt: {attempt}, Page: {page} -->\n")
                        f.write(f"<!-- Markers: {markers} -->\n")
                        f.write(html)
                    log_warning(f"[PARTY-DBG] dump: {fname}")
                except Exception as e:
                    log_debug(f"[PARTY-DBG] dump fail: {e}")

            return False, markers

        # Проверяем что приглашение от нашего лидера
        inviter = self._extract_inviter_name(html)
        if inviter and inviter != leader_username:
            log_warning(f"[PARTY] Мембер: приглашение от '{inviter}', а ждём от '{leader_username}' — отклоняю")
            decline_url = self._find_feedback_url(html, "decline")
            if decline_url:
                self.client.get(decline_url)
                time.sleep(0.5)
            return False, markers

        log_info(f"[PARTY] Мембер: вижу приглашение от {inviter or '?'}! (page=/{page})")

        accept_url = self._find_feedback_url(html, "accept")
        if not accept_url:
            log_warning("[PARTY] Мембер: URL 'Принять' не найден в HTML")
            for i, line in enumerate(html.split('\n')):
                if 'feedback' in line.lower() or 'приглашает' in line.lower():
                    log_debug(f"[PARTY] HTML[{i}]: {line[:200]}")
            return False, markers

        log_info(f"[PARTY] Мембер: принимаю приглашение от {leader_username}")
        log_debug(f"[PARTY] Accept URL: {accept_url}")
        self.client.get(accept_url)
        time.sleep(0.5)

        current = self.client.current_url or ""
        log_debug(f"[PARTY] После accept URL: {current}")
        if "/dungeon/lobby/" in current or "/dungeon/standby/" in current:
            log_info("[PARTY] Мембер: уже в лобби после accept!")
            return True, markers

        return self.enter_dungeon_feedback(), markers

    def wait_and_accept_invite(self, leader_username, timeout=INVITE_TIMEOUT):
        """Мембер ждёт инвайт от лидера.

        Стратегия:
            1. Открываем /city и подписываемся на Wicket WebSocket
               (push-канал игры — там реально приходят notice о приглашениях).
            2. Параллельно поллим HTTP-страницы как fallback на случай если
               WS-сообщение пришло раньше подписки.
            3. Какое из двух сработает — то и используем.

        Без WS чисто HTTP-fallback почти не ловит инвайт (сервер пушит
        через WS-канал и в HTML страниц не возвращает после первых ~2
        минут сессии).

        Returns:
            bool: True если приглашение принято и вошёл в данж
        """
        from requests_bot.wicket_ws import listener_for_current_page

        log_info(f"[PARTY] Мембер: жду инвайт от {leader_username} ({timeout}с)...")

        # Сначала встаём на /city — там и WS-канал нужного типа (CityPage),
        # и реальные приглашения приходят сюда.
        self.client.get(f"{self.base_url}/city")
        time.sleep(0.3)

        ws_listener = None
        try:
            ws_listener = listener_for_current_page(self.client)
            if ws_listener:
                ws_listener.start()
                log_info(f"[PARTY] WS-слушатель запущен на pageId={ws_listener.page_id}")
            else:
                log_warning("[PARTY] WS-слушатель не создан, fallback на HTTP-поллинг")
        except Exception as e:
            log_warning(f"[PARTY] Ошибка WS: {e}")

        try:
            # Если WS поднялся — ждём сначала через него, параллельно делая
            # лёгкие HTTP-полли как страховку.
            deadline = time.time() + timeout
            attempt = 0
            # Fallback-страницы для HTTP-полла.
            # Из реальных успехов 04-06 мая: invite приходил почти ВСЕГДА на
            # /dungeons (polling #2-#3). На /city реже. Поэтому поллим в
            # основном /dungeons + /city, чаще.
            pages = ["dungeons", "city", "dungeons", "city", "dungeons", "city", "tavern"]
            last_markers = None

            # WS-проверка делается в маленьком цикле (короткие wait) чтобы успевать
            # делать HTTP-полли параллельно. Уменьшил с 3.0 до 1.5 — invite
            # имеет show_time 4сек, чтобы не пропустить окно показа.
            ws_poll_step = 1.5  # сек между проверками WS

            while time.time() < deadline:
                # 1) Проверка WS
                if ws_listener:
                    invite = ws_listener.wait_for_invite(timeout=ws_poll_step, leader_username=leader_username)
                    if invite:
                        log_info(f"[PARTY] Мембер: вижу инвайт через WS от '{invite['inviter_name'] or '?'}'")
                        accept_url = invite["accept_url"]
                        log_debug(f"[PARTY] WS Accept URL: {accept_url}")
                        self.client.get(accept_url)
                        time.sleep(0.5)
                        # После accept сервер обычно редиректит в лобби
                        current = self.client.current_url or ""
                        if "/dungeon/lobby/" in current or "/dungeon/standby/" in current:
                            log_info("[PARTY] Мембер: уже в лобби после accept!")
                            return True
                        return self.enter_dungeon_feedback()
                else:
                    time.sleep(ws_poll_step)

                # 2) Параллельный HTTP-полл (на случай если WS пропустил)
                page = pages[attempt % len(pages)]
                attempt += 1
                result, markers = self.check_and_accept_invite(leader_username, page=page, attempt=attempt)
                if result:
                    return True
                last_markers = markers

            log_warning(f"[PARTY] Мембер: таймаут ожидания приглашения ({timeout}с), {attempt} HTTP-попыток")
            if last_markers:
                log_warning(f"[PARTY] Последняя HTTP-проверка: {last_markers}")
            return False
        finally:
            if ws_listener:
                try:
                    ws_listener.stop()
                except Exception:
                    pass


# ============================================
# Главная функция координации
# ============================================

def run_party_dungeon(client, dungeon_runner, dungeon_id, difficulty="impossible", role=None):
    """Главная функция: координация + вход + бой.

    Вызывается из bot.py с уже определённым dungeon_id (раньше был дефолт
    'dng:ShadowGuard' — маскировал баг когда bot.py забывал передавать).

    role: 'leader' | 'member' | None.
        - 'leader': создаёт новую пати если нет forming
        - 'member': только присоединяется, НЕ создаёт (защита от race-окна
          между find_forming_party в bot.py и try_join_or_create_party здесь)
        - None: старое поведение (создаст всегда, оставлено для совместимости)

    Returns:
        "completed" — данж пройден
        "died" — погибли
        "timeout" — не собрали пати
        "error" — ошибка
        None — нет возможности (КД, уже в пати)
    """
    profile = get_profile_name()
    username = get_profile_username()
    nickname = get_game_nickname()  # Игровой ник (для инвайтов)

    # Очистка зависших пати от предыдущих сессий
    cleanup_own_stale_party(profile)

    if not can_join_party(profile, dungeon_id):
        return None

    dungeon_cfg = PARTY_DUNGEONS.get(dungeon_id)
    if not dungeon_cfg:
        return None

    # Кол-во мемберов берём из конфига профиля (по умолчанию 2)
    party_cfg = get_party_dungeon_config()
    target_members = party_cfg.get("members", 2)

    # Пробуем вступить или создать (nickname для инвайтов)
    result = try_join_or_create_party(
        profile, nickname, dungeon_id, difficulty, target_members,
        only_join=(role == "member"),  # мембер не создаёт пати
    )
    if not result:
        if role == "member":
            log_debug(f"[PARTY] Мембер {profile}: forming пати исчезла, ждём следующий цикл")
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
        # Не удалось войти — КД в игре или ещё в банде
        record_cooldown(profile, dungeon_id, seconds=600)  # 10 мин при ошибке входа
        leave_party(profile, party_id)
        # Возвращаемся в город
        party_client.client.get(f"{party_client.base_url}/city")
        time.sleep(1)
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

        # Возвращаемся в лобби перед каждым инвайтом
        party_client.client.get(f"{party_client.base_url}/dungeon/lobby/{party_client.url_id}")
        time.sleep(0.5)

        if not party_client.invite_player(mem_username):
            log_warning(f"[PARTY] Лидер: не удалось пригласить {mem_username}")
            # Продолжаем с остальными

    # 4. Ждём пока все мемберы зайдут в лобби (status=in_lobby)
    #    Каждые 30с переотправляем инвайт тем, кто ещё не в лобби
    log_info("[PARTY] Лидер: жду всех в лобби...")
    lobby_deadline = time.time() + LOBBY_TIMEOUT
    reinvite_interval = 30
    last_reinvite = time.time()

    while time.time() < lobby_deadline:
        members = get_party_members(party_id)
        # Проверяем что мемберов достаточно И все в лобби.
        # Без len-проверки баг: если мембер ушёл (leave_party после таймаута
        # своего invite), он удаляется из members, остаётся ТОЛЬКО лидер.
        # all(...) для одного элемента = True → лидер шёл в бой соло.
        if len(members) >= target_members and all(m.get("status") == "in_lobby" for m in members.values()):
            break

        # Переотправляем инвайт каждые 30с
        if time.time() - last_reinvite >= reinvite_interval:
            for mem_profile, mem_info in members.items():
                if mem_profile == profile:
                    continue
                if mem_info.get("status") == "in_lobby":
                    continue
                mem_username = mem_info.get("username", "")
                if mem_username:
                    log_info(f"[PARTY] Лидер: повторный инвайт {mem_username}")
                    # Возвращаемся в лобби перед инвайтом
                    party_client.client.get(f"{party_client.base_url}/dungeon/lobby/{party_client.url_id}")
                    time.sleep(0.5)
                    party_client.invite_player(mem_username)
            last_reinvite = time.time()

        time.sleep(POLL_INTERVAL)
    else:
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

    # Возвращаемся в город (чтобы не застрять в данже)
    party_client.client.get(f"{party_client.base_url}/city")
    time.sleep(1)

    # Помечаем завершение
    mark_completed(party_id)

    log_info(f"[PARTY] {profile}: бой окончен — {result}, {actions} действий")
    return result


# ============================================
# Event-party (ивент-данж в пати)
# ============================================

def cleanup_before_party(client) -> bool:
    """Готовит бота к пати: возвращает в город, выходит из банды/данжа.

    Вызывается перед началом пати-логики чтобы избежать ситуации когда бот
    застрял где-то ещё (в обычном данже, в банде с прошлой сессии и т.д.).
    Без этого инвайт лидера может не дойти, или мембер не сможет принять.

    Returns:
        bool: True если cleanup успешен (бот в /city и не в банде)
    """
    log_info("[EVENT-PARTY] Cleanup: возврат в город и выход из банды...")

    # 1. Идём в /city
    try:
        client.get(f"{BASE_URL}/city")
        time.sleep(0.5)
    except Exception as e:
        log_error(f"[EVENT-PARTY] Не удалось перейти в /city: {e}")
        return False

    # 2. Если есть кнопка "Покинуть банду" — нажимаем (с подтверждением doconfirm)
    html = client.current_page or ""
    leave_match = re.search(r'href="([^"]*leaveParty[^"]*)"', html)
    if leave_match:
        leave_url = leave_match.group(1).replace("&amp;", "&")
        if not leave_url.startswith("http"):
            leave_url = urljoin(client.current_url, leave_url)
        log_info("[EVENT-PARTY] В банде — покидаем (шаг 1)")
        try:
            client.get(leave_url)
            time.sleep(0.5)
            # Шаг 2: подтверждение если попали на /doconfirm.
            # БАГ ИГРЫ: leaveParty ведёт сначала на /doconfirm с кнопкой "Да, точно".
            # Без подтверждения банда остаётся активной.
            if "/doconfirm" in (client.current_url or ""):
                soup = client.soup()
                if soup:
                    for a in soup.select("a.go-btn"):
                        if a.get_text(strip=True) == "Да, точно":
                            href = a.get("href", "").replace("&amp;", "&")
                            if href and not href.startswith("http"):
                                href = urljoin(client.current_url, href)
                            log_info("[EVENT-PARTY] Подтверждаю выход (doconfirm)")
                            client.get(href)
                            time.sleep(0.5)
                            break
            # Возвращаемся в город
            client.get(f"{BASE_URL}/city")
            time.sleep(0.3)
        except Exception as e:
            log_warning(f"[EVENT-PARTY] Не удалось покинуть банду: {e}")
            return False

    # 3. Финальная проверка — в /city ли мы (не в данже/комбате)
    cur = client.current_url or ""
    if "/dungeon/" in cur or "/combat" in cur:
        log_warning(f"[EVENT-PARTY] После cleanup всё ещё в данже: {cur}")
        return False

    return True


def run_event_party(client, dungeon_runner, dungeon_id, role):
    """Координация event-party (ивент-данж только когда у обоих нет КД).

    Отличия от run_party_dungeon:
    - cleanup перед стартом (выход из обычного данжа/банды)
    - Лидер дополнительно проверяет КД мембера в shared state перед созданием пати
    - Мембер: если у себя есть КД — не вступает (не должен идти в ивент один)

    Args:
        dungeon_id: 'dng:FireTower' и т.п. (с префиксом dng:)
        role: 'leader' | 'member'

    Returns:
        same as run_party_dungeon
    """
    from requests_bot.config import get_profile_name, get_profile_username, get_game_nickname
    from requests_bot.valentine_event import is_dungeon_on_cooldown_for_profile, VALENTINE_DUNGEONS

    profile = get_profile_name()
    username = get_profile_username()
    nickname = get_game_nickname()

    dungeon_cfg = PARTY_DUNGEONS.get(dungeon_id)
    if not dungeon_cfg or not dungeon_cfg.get("is_event"):
        log_error(f"[EVENT-PARTY] {dungeon_id} не помечен is_event")
        return None

    # Маппинг dng:FireTower → FireTower (ключ в VALENTINE_DUNGEONS)
    event_key = dungeon_cfg.get("event_dungeon_key", dungeon_id.replace("dng:", ""))

    # 1. Проверяем КД у себя
    if is_dungeon_on_cooldown_for_profile(profile, event_key):
        log_debug(f"[EVENT-PARTY] У меня КД на {event_key}, пропускаем")
        return None

    # 2. Решаем стоит ли вообще идти в пати ПРЕЖДЕ чем делать cleanup.
    #    Cleanup делает HTTP-запросы (/city, leaveParty) — каждый цикл их делать
    #    избыточно. Делаем только когда есть РЕАЛЬНАЯ возможность собрать пати.
    max_party_size = dungeon_cfg.get("max_members", 2)

    if role == "leader":
        # Лидер: берёт ВСЕХ доступных мемберов из shared state (до лимита данжа)
        try:
            with FileLock(PARTY_LOCK_FILE):
                state = _load_state()
            event_cd = state.get("event_cooldowns", {})

            potential_members = []
            for other_profile, cooldowns in event_cd.items():
                if other_profile == profile:
                    continue
                cd_until = cooldowns.get(event_key, 0)
                if time.time() >= cd_until:
                    potential_members.append(other_profile)

            if not potential_members:
                log_debug(f"[EVENT-PARTY] Лидер: нет доступных мемберов")
                return None

            # Размер пати = я + доступные мемберы, но не больше max данжа
            target_members = min(1 + len(potential_members), max_party_size)
            log_info(f"[EVENT-PARTY] Лидер: доступные мемберы: {potential_members} → target_members={target_members}")
        except Exception as e:
            log_error(f"[EVENT-PARTY] Ошибка проверки КД мемберов: {e}")
            return None
    else:
        # Мембер: проверяем что есть forming пати — иначе не делаем cleanup впустую
        forming = find_forming_party(profile)
        if not forming or forming.get("dungeon_id") != dungeon_id:
            log_debug(f"[EVENT-PARTY] Мембер: forming пати на {dungeon_id} нет, ждём")
            return None
        target_members = max_party_size  # для try_join_or_create_party — реальное число берётся из forming party

    # 3. Cleanup ТОЛЬКО когда реально пойдём в пати
    if not cleanup_before_party(client):
        log_warning("[EVENT-PARTY] Cleanup не удался, пропускаем цикл")
        return None

    # 4. Очистка зависшей пати
    cleanup_own_stale_party(profile)

    # 5. Защита от уже-в-пати
    if is_in_party(profile):
        log_debug(f"[EVENT-PARTY] Уже в пати, пропускаем")
        return None

    # 6. Сложность пати: лидер берёт из своего конфига (event_party_difficulty,
    # default "hero"). Мембер ждёт инвайт — сложность ему не нужна.
    from requests_bot.config import get_event_party_difficulty
    from requests_bot.valentine_event import DIFFICULTY_URL_MAP
    party_difficulty_raw = get_event_party_difficulty() if role == "leader" else "hero"
    party_difficulty = DIFFICULTY_URL_MAP.get(party_difficulty_raw, "hard")

    # 7. Координация через try_join_or_create_party
    result = try_join_or_create_party(
        profile, nickname, dungeon_id, party_difficulty, target_members,
        only_join=(role == "member"),
    )
    if not result:
        if role == "member":
            log_debug(f"[EVENT-PARTY] Мембер {profile}: forming пати исчезла, ждём")
        return None

    party_id = result["id"]
    actual_role = result["role"]
    party = result["party"]
    party_client = PartyDungeonClient(client, dungeon_id)

    # Если попали как мембер — сложность узнали из forming-party (записал лидер)
    if actual_role == "member":
        party_difficulty = party.get("difficulty", party_difficulty)

    log_info(f"[EVENT-PARTY] {username}: role={actual_role}, party={party_id}, difficulty={party_difficulty}")

    try:
        if actual_role == "leader":
            return _run_as_leader(
                profile, username, party_id, party_client,
                dungeon_runner, dungeon_id, party_difficulty, target_members,
            )
        else:
            # Мембер: сложность из forming-party (записал лидер)
            leader_username = party.get("leader_username", "")
            return _run_as_member(
                profile, username, party_id, party_client,
                dungeon_runner, dungeon_id, leader_username,
            )
    except Exception as e:
        log_error(f"[EVENT-PARTY] Ошибка: {e}")
        import traceback
        traceback.print_exc()
        party_client.leave_lobby()
        leave_party(profile, party_id)
        return "error"
