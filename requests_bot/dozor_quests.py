# ============================================
# VMMO Dozor Quests - дэйли-дозоры таверны
# ============================================
# Разведка 2026-07-20 (на char15, Иглес, свет):
# - Дозор — цепочка дэйли-квестов таверны (период 1440м), уровень 16+.
#   Стартовые звенья qDozorDaily(Light|Dark)First30 / First видны в списке
#   apiFullUrl, дальше цепочка идёт по полю "quest" ответа Complete:
#   First30 -> First -> Second30 -> Second -> Third30 -> Third ->
#   Dungeon30 -> Dungeon -> конец (8 звеньев за день).
# - Каждое звено: accept -> redirect /training/h/<id> -> /fight (наш движок).
#   «Принеси N тушек» — обманка: один бой закрывает весь прогресс.
# - Звенья Dungeon*: /training/h/ ведёт на /quest_dungeon/<id>, внутри
#   JS-редирект на /dungeon/standby/(Light|Dark)Dozor-Solo*?1=normal —
#   достаём URL из HTML сами (HTTP-клиент JS не исполняет).
# - Победа регистрируется возвратом на /training/h/<id> (как караваны).
# - Награда всей цепочки: ~30 минералов + ~12 сапфиров + влияние гильдии.
# - КВЕСТЫ ЗАВИСЯТ ОТ ГОРОДА: есть в Андере (_neyro), Иглесе (_igles) и
#   _under; НЕТ в Небесном Лагере (_sky), Эфире (_efir), Мелгорде.
#   В Иглесе дозор есть и для света, и для тьмы — туда и переезжаем.
#   Сделанные квесты ИСЧЕЗАЮТ из списка до дневного сброса (не висят с КД),
#   поэтому «нет квестов» != «не тот город» — различаем по кэшу last_completed.
# - Переезд: /cities?continent=0, ссылка lnkGoTo в блоке города — мгновенно
#   и бесплатно (после Адских Игр высокоуровневых чаров закидывает в _sky,
#   так что переезд может повторяться каждый день — это нормально).
# ============================================

import json
import os
import re
import time

from requests_bot.logger import log_info, log_warning, log_debug
from requests_bot.tavern_quests import (
    API_HEADERS, _get_tavern_api, _accept,
)

DOZOR_PREFIX = "qDozorDaily"
DOZOR_CITY = "_igles"       # единственный город, где дозор есть у обеих фракций
CHECK_INTERVAL = 3 * 3600   # дэйли — чаще раза в 3ч смотреть смысла нет
DONE_TTL = 23 * 3600        # цепочка сделана — до завтра не дёргаемся
MAX_QUESTS_PER_RUN = 12     # цепочка = 8 звеньев, с запасом
MAX_FIGHTS_PER_QUEST = 3    # реально хватает одного боя на звено


def _cache_file():
    from requests_bot.config import PROFILE_DIR
    return os.path.join(PROFILE_DIR, "dozor_quests.json")


def _load_cache():
    try:
        with open(_cache_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        with open(_cache_file(), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_debug(f"[DOZOR] Ошибка сохранения кэша: {e}")


def _fetch_dozor_quests(client, urls):
    """Видимые дозор-квесты из apiFullUrl (сделанные исчезают из списка)."""
    resp = client.session.get(urls["apiFullUrl"], headers=API_HEADERS, timeout=30)
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    quests = []
    for sec in data.get("quests", []):
        for q in sec.get("content", []):
            if q.get("id", "").startswith(DOZOR_PREFIX):
                quests.append(q)
    return quests


def _quest_state(client, urls, quest_id):
    """Статус/прогресс дозор-квеста. None если исчез из списка.
    НЕ tavern_quests._quest_state — тот фильтрует список по маркеру Karavan
    и для дозоров всегда возвращал бы None."""
    for q in _fetch_dozor_quests(client, urls) or []:
        if q.get("id") == quest_id:
            return q
    return None


def _travel_to_dozor_city(client):
    """Переезд в Иглес через карту. True если уже там или переехали."""
    resp = client.get("/cities?continent=0")
    if resp is None:
        return False
    html = client.current_page or ""
    cur = re.search(r"map-city ([_a-z-]+) _current", html)
    if cur and cur.group(1) == DOZOR_CITY:
        return True
    m = re.search(
        r'class="map-city ' + DOZOR_CITY + r'[^"]*"(.{0,1500}?)(?=class="map-city |\Z)',
        html, re.S)
    if not m:
        log_debug("[DOZOR] Иглес не найден на карте — пропуск")
        return False
    lm = re.search(r'href="([^"]+locations-\d+-location-lnkGoTo[^"]*)"', m.group(1))
    if not lm:
        log_debug("[DOZOR] Ссылка переезда в Иглес недоступна (город закрыт?)")
        return False
    client.get(lm.group(1).replace("&amp;", "&"))
    log_info("[DOZOR] Переехал в Иглес за дозором")
    return True


def _in_combat(client):
    p = client.current_page or ""
    return "attack-button-link" in p or "ptx_combat_rich" in p


def _fight(client, dungeon_runner, qid):
    """Один бой звена. Returns: 'won' | 'died' | 'no_battle' | 'error'."""
    from requests_bot.heal import ensure_healed
    ensure_healed(client)

    resp = client.get(f"/training/h/{qid}")
    if resp is None:
        return "error"
    if not _in_combat(client):
        # Звено Dungeon*: страница /quest_dungeon/<id> со standby-ссылкой.
        # Обязательно Dozor в пути — чтобы не уйти в чужой данж.
        m = re.search(
            r'["\']((?:https?://[^"\']+)?/dungeon/(?:standby|combat|lobby)/'
            r'[^"\']*[Dd]ozor[^"\']*)["\']',
            client.current_page or "")
        if not m:
            log_debug(f"[DOZOR] {qid}: боя нет (url={client.current_url})")
            return "no_battle"
        client.get(m.group(1).replace("&amp;", "&"))
        if not _in_combat(client):
            log_debug(f"[DOZOR] {qid}: standby не привёл в бой (url={client.current_url})")
            return "no_battle"
    # Тот же паттерн, что караваны: combat_url = текущая страница, наш движок.
    # _save_loot_url_from_combat_page обязателен — без heartbeat сервер не
    # тикает бой (волны не спавнятся, победа не регистрируется).
    dungeon_runner.current_dungeon_id = f"dozor:{qid}"
    dungeon_runner.combat_url = client.current_url
    try:
        dungeon_runner._save_loot_url_from_combat_page()
    except Exception as e:
        log_debug(f"[DOZOR] init combat page: {e}")
    result, actions = dungeon_runner.fight_until_done(max_actions=150)
    log_info(f"[DOZOR] Бой {qid}: {result} ({actions} действий)")
    if result == "died":
        dungeon_runner.resurrect()
        return "died"
    # Победа регистрируется только возвратом на квестовый URL (в браузере
    # это делает JS-редирект) — сервер видит зачистку и ставит прогресс.
    client.get(f"/training/h/{qid}")
    return "won"


def _complete_next(client, urls, qid):
    """Сдаёт квест. Возвращает id следующего звена, None если цепочка
    кончилась, False если сдать не вышло."""
    resp = client.session.get(urls["apiQuestCompleteUrl"] + f"&quest_id={qid}",
                              headers=API_HEADERS, timeout=30)
    if resp.status_code != 200:
        return False
    try:
        data = resp.json()
    except Exception:
        return False
    if data.get("status") != "OK":
        log_debug(f"[DOZOR] complete {qid}: {data}")
        return False
    log_info(f"[DOZOR] Квест {qid} сдан ✓")
    return data.get("quest") or None


def _run_chain(client, urls, dungeon_runner, start_qid):
    """Идёт по цепочке от start_qid по полю next. Возвращает (done, status)."""
    done = 0
    qid = start_qid
    while qid and done < MAX_QUESTS_PER_RUN:
        state = _quest_state(client, urls, qid)
        if state is None:
            break  # исчез из списка — сделан/на КД
        if (state.get("period") or {}).get("left", {}).get("num", 0) > 0:
            break  # на КД
        if state.get("status") == "none":
            _accept(client, urls, qid)
            state = _quest_state(client, urls, qid)
        # Бои до закрытия прогресса (реально хватает одного)
        for _ in range(MAX_FIGHTS_PER_QUEST):
            state = state or _quest_state(client, urls, qid)
            if state is None or state.get("status") == "complete":
                break
            prog = state.get("progress") or {}
            if prog.get("current", 0) >= prog.get("total", 1):
                break
            outcome = _fight(client, dungeon_runner, qid)
            if outcome == "died":
                return done, "died"
            if outcome in ("no_battle", "error"):
                return done, outcome
            state = None  # перечитать на следующей итерации
        nxt = _complete_next(client, urls, qid)
        if nxt is False:
            return done, "error"
        done += 1
        qid = nxt if (nxt or "").startswith(DOZOR_PREFIX) else None
    return done, "ok"


def run_dozor_quests(client, dungeon_runner, force=False):
    """
    Главный вход: проходит дневную цепочку дозоров (8 боевых звеньев,
    ~30 минералов + ~12 сапфиров + влияние). Вызывается из цикла бота,
    когда данжи на КД. Если в текущем городе дозора нет — переезжает в Иглес.

    Безопасность: любая ошибка гасится, цикл бота не ломается.
    """
    try:
        from requests_bot.config import is_dozor_enabled
        if not is_dozor_enabled():
            return 0

        cache = _load_cache()
        now = time.time()
        if not force and now < cache.get("next_check", 0):
            return 0

        urls = _get_tavern_api(client)
        if urls is None:
            return 0
        quests = _fetch_dozor_quests(client, urls)
        if quests is None:
            return 0

        if not quests:
            # Сделаны сегодня (исчезают до сброса) — или город без дозора
            if now - cache.get("last_completed", 0) < DONE_TTL:
                cache["next_check"] = now + CHECK_INTERVAL
                _save_cache(cache)
                return 0
            if not _travel_to_dozor_city(client):
                cache["next_check"] = now + CHECK_INTERVAL
                _save_cache(cache)
                return 0
            urls = _get_tavern_api(client)
            if urls is None:
                return 0
            quests = _fetch_dozor_quests(client, urls) or []
            if not quests:
                # И в Иглесе пусто (низкий уровень?) — не наш день
                cache["next_check"] = now + CHECK_INTERVAL
                _save_cache(cache)
                return 0

        try:
            from requests_bot.bot import set_activity
            set_activity("🦇 Дозор таверны")
        except Exception:
            pass

        log_debug(f"[DOZOR] Видимые дозоры: "
                  f"{[(q['id'], q.get('status')) for q in quests]}")

        total = 0
        # Стартуем с каждого видимого звена: обычно это First30/First, но
        # после смерти посреди цепочки тут будет место обрыва (Second и т.д.)
        for q in quests:
            if total >= MAX_QUESTS_PER_RUN:
                break
            try:
                done, status = _run_chain(client, urls, dungeon_runner, q["id"])
                total += done
                if status == "died":
                    log_warning("[DOZOR] Смерть в дозоре — отложены до след. захода")
                    break
            except Exception as e:
                log_warning(f"[DOZOR] Ошибка цепочки {q.get('id')}: {e}")

        if total:
            cache["last_completed"] = now
            log_info(f"[DOZOR] Дозоры: сделано квестов: {total}")
        cache["next_check"] = now + CHECK_INTERVAL
        _save_cache(cache)
        return total
    except Exception as e:
        log_warning(f"[DOZOR] Ошибка run_dozor_quests: {e}")
        return 0
