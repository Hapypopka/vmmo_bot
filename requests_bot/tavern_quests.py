# ============================================
# VMMO Tavern Quests - дэйли-караваны таверны
# ============================================
# Разведка 2026-07-10 (за Пупупу, проба на char10):
# - GET /tavern → SPA-конфиг с apiFullUrl / apiQuestAcceptUrl /
#   apiQuestCompleteUrl (те же Wicket-endpoints, что в туториале)
# - apiFullUrl → JSON: {player, quests: [секции, в них content[]]}
# - Цепочка обычного каравана (дэйли, период 1440м):
#     qKaravanDayli20prequest  «Взнос» — сдай 5 минералов (списываются на
#         complete; после accept status сразу 'complete', если ресурс есть)
#     qKaravanDayli20          «Пора в путь» — accept даёт redirect на
#         /training/h/<id> → обычный бой (движок combat как в данжах)
#     qKaravanReward20         награда: взнос возвращается + бонус
# - Аналогично «Новые» (5 сапфиров) и «Элитные» (3 рубина).
# - Сюжетная цепочка qKaravanFirst..Seven+ (тоже training-бои) открывает
#   дэйлики: до её прохождения у чара виден только обычный взнос или ничего.
# - Караваны есть во всех 4 светлых городах (igles/quazar/default/shade).
#
# Резервы: взнос делаем только если ресурса хватает с запасом — не съедаем
# рубины, зарезервированные под gold_transfer.
# ============================================

import json
import os
import re
import time

from requests_bot.logger import log_info, log_warning, log_debug

API_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

CARAVAN_MARKER = "Karavan"
CHECK_INTERVAL = 3 * 3600   # проверяем таверну не чаще раза в 3ч (дэйли и есть)
MAX_FIGHTS_PER_QUEST = 20   # сюжетные «убей N бандитов» — серия боёв
MAX_QUESTS_PER_RUN = 6      # предохранитель на один заход

# Взносы: quest_id -> (ключ в resources.json, ключ resource_sell, сколько сдаём)
DONATE_COSTS = {
    "qKaravanDayli20prequest": ("минералы", "mineral", 5),
    "qKaravanDayli30prequest": ("сапфиры", "sapphire", 5),
    "qKaravanEliteDayli30pre": ("рубины", "ruby", 3),
}

# Минимальный запас для взноса. Резерв продаж (resource_sell.reserve) тут НЕ
# подходит: он means «копить до N», а караван взнос ВОЗВРАЩАЕТ + даёт сверху —
# с резервом 5000 минералов взнос в 5 шт блокировался бы вечно.
# Исключение — рубины: они зарезервированы под gold_transfer, их уважаем
# по полному резерву из конфига (см. _donate_allowed).
DONATE_MIN_KEEP = {
    "mineral": 50,
    "sapphire": 10,
}


def _cache_file():
    from requests_bot.config import PROFILE_DIR
    return os.path.join(PROFILE_DIR, "tavern_quests.json")


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
        log_debug(f"[TAVERN] Ошибка сохранения кэша: {e}")


def _get_tavern_api(client):
    """Открывает таверну и парсит API-endpoints. None если не в городе/в бою."""
    resp = client.get("/tavern")
    if resp is None:
        return None
    urls = dict(re.findall(r"(api\w+Url)\s*=\s*'([^']+)'", resp.text))
    if "apiFullUrl" not in urls:
        log_debug("[TAVERN] apiFullUrl не найден (в бою или редирект) — пропуск")
        return None
    return urls


def _fetch_quests(client, urls):
    """Возвращает список караван-квестов из apiFullUrl."""
    resp = client.session.get(urls["apiFullUrl"], headers=API_HEADERS, timeout=30)
    if resp.status_code != 200:
        return None
    data = resp.json()
    quests = []
    for sec in data.get("quests", []):
        for q in sec.get("content", []):
            if CARAVAN_MARKER in q.get("id", ""):
                quests.append(q)
    return quests


def _resource_counts():
    """Текущие ресурсы из resources.json профиля ({'минералы': N, ...})."""
    from requests_bot.config import PROFILE_DIR
    try:
        with open(os.path.join(PROFILE_DIR, "resources.json"), encoding="utf-8") as f:
            return json.load(f).get("current_session", {}).get("current", {}) or {}
    except Exception:
        return {}


def _donate_allowed(quest_id):
    """Хватает ли ресурса на взнос (взнос возвращается — floor маленький).

    Рубины — особый случай: зарезервированы под gold_transfer, уважаем
    полный резерв из resource_sell.
    """
    if quest_id not in DONATE_COSTS:
        return True
    res_name, sell_key, cost = DONATE_COSTS[quest_id]
    have = _resource_counts().get(res_name)
    if have is None:
        # Не знаем сколько ресурса — не рискуем
        log_debug(f"[TAVERN] {quest_id}: количество '{res_name}' неизвестно — пропуск")
        return False
    if sell_key == "ruby":
        from requests_bot.config import get_resource_sell_config
        keep = int(get_resource_sell_config(sell_key).get("reserve", 10) or 10)
    else:
        keep = DONATE_MIN_KEEP.get(sell_key, 10)
    if have - cost < keep:
        log_info(f"[TAVERN] {quest_id}: {res_name} {have} - взнос {cost} < запас {keep} — пропуск")
        return False
    return True


def _accept(client, urls, quest_id):
    """Принимает квест. Возвращает (ok, redirect_url|None)."""
    resp = client.session.get(urls["apiQuestAcceptUrl"] + f"&quest_id={quest_id}",
                              headers=API_HEADERS, timeout=30)
    if resp.status_code != 200:
        return False, None
    try:
        data = resp.json()
    except Exception:
        return False, None
    if data.get("status") == "Fail":
        log_debug(f"[TAVERN] accept {quest_id}: {data.get('answer')}")
        return False, None
    url = data.get("url")
    # redirect на /training/ = боевой квест; redirect на /tavern = мирный
    return True, (url if url and "/training/" in url else None)


def _complete(client, urls, quest_id):
    resp = client.session.get(urls["apiQuestCompleteUrl"] + f"&quest_id={quest_id}",
                              headers=API_HEADERS, timeout=30)
    if resp.status_code != 200:
        return False
    try:
        ok = resp.json().get("status") == "OK"
    except Exception:
        return False
    if ok:
        log_info(f"[TAVERN] Квест {quest_id} сдан ✓")
    return ok


def _quest_state(client, urls, quest_id):
    """Перечитывает статус/прогресс квеста. None если квест исчез из списка."""
    quests = _fetch_quests(client, urls) or []
    for q in quests:
        if q.get("id") == quest_id:
            return q
    return None


def _fight_training(client, dungeon_runner, battle_url, quest_id):
    """Боевой шаг: /training/h/<id> редиректит на /fight?0=<id> — бой движком данжей.

    Returns: 'won' | 'died' | 'error' | 'no_battle'
    """
    # Отхил перед боем (караваны — те же мусорные смерти без него)
    from requests_bot.heal import ensure_healed
    ensure_healed(client)

    resp = client.get(battle_url)
    if resp is None:
        return "error"
    # Караван «едет» реальное время между этапами: если бой ещё не готов,
    # /training/h/<id> редиректит на карточку в таверне — вернёмся позже (3ч).
    # Готовый бой: /quest_dungeon/<id>, внутри которого JS-редирект на
    # /dungeon/standby/Karavan-* (HTTP-клиент JS не исполняет — достаём URL
    # из HTML сами). Дальше стандартный данж-бой, наш движок.
    #
    # ВАЖНО: критерий «мы в бою» — ТОЛЬКО attack-button-link/ptx_combat_rich.
    # Слово 'battlefield' есть даже на главной (JS-конфиг) — с ним движок
    # молотил 500 холостых действий на главной странице (баг 2026-07-10).
    def _in_combat():
        p = client.current_page or ""
        return "attack-button-link" in p or "ptx_combat_rich" in p

    if not _in_combat():
        # Не в бою: ищем ССЫЛКУ на караванный данж (обязательно Karavan в
        # пути, чтобы не уйти в чужой данж со страницы таверны/города)
        m = re.search(
            r'["\']((?:https?://[^"\']+)?/dungeon/(?:standby|combat|lobby)/[^"\']*[Kk]aravan[^"\']*)["\']',
            client.current_page or "")
        if not m:
            log_debug(f"[TAVERN] {quest_id}: бой ещё не готов (url={client.current_url}) — караван в пути")
            return "no_battle"
        client.get(m.group(1).replace("&amp;", "&"))
        if not _in_combat():
            log_debug(f"[TAVERN] {quest_id}: standby не привёл в бой (url={client.current_url})")
            return "no_battle"
    # Паттерн ивент-данжей: combat_url = текущая страница, тот же движок.
    # Лимит 60 действий: реальные бои каравана — 5-15 действий, 500 дефолтных
    # означало 17 минут молотьбы при любом сбое детекции.
    dungeon_runner.current_dungeon_id = f"tavern:{quest_id}"
    dungeon_runner.combat_url = client.current_url
    result, actions = dungeon_runner.fight_until_done(max_actions=60)
    log_info(f"[TAVERN] Бой {quest_id}: {result} ({actions} действий)")
    if result == "died":
        dungeon_runner.resurrect()
        return "died"
    if result == "completed" or (
            # После победы в training-бою игра редиректит в таверну
            # (/tavern?quest=<id>&take=true) — движок видит 'unknown'.
            result == "unknown" and "/tavern" in (client.current_url or "")):
        _take_profession_loot(client)
        return "won"
    return "error"


def _take_profession_loot(client):
    """После боя каравана бывает кнопка «Забрать» (professionPanel) — жмём."""
    try:
        page = client.current_page or ""
        m = re.search(r'href="([^"]*professionPanel[^"]*)"[^>]*>\s*Забрать', page)
        if not m:
            # Кнопка может быть на странице боя, а мы уже в таверне — не страшно
            return
        client.get(m.group(1).replace("&amp;", "&"))
        log_info("[TAVERN] Забрал лут каравана")
    except Exception as e:
        log_debug(f"[TAVERN] Ошибка забора лута: {e}")


def _process_quest(client, urls, dungeon_runner, q):
    """Обрабатывает один караван-квест. Возвращает True если что-то сделали."""
    qid = q.get("id")
    status = q.get("status")
    progress = q.get("progress") or {}
    done = progress.get("current", 0) >= progress.get("total", 1)

    # Дэйли на КД — не трогаем
    period = q.get("period") or {}
    if (period.get("left") or {}).get("num", 0) > 0:
        return False

    # Готов к сдаче (после accept взнос сразу 'complete', если ресурс есть)
    if status == "complete":
        return _complete(client, urls, qid)

    if status == "active":
        if done:
            return _complete(client, urls, qid)
        # Активный боевой: ре-accept (= кнопка «Приступить» у бармена, двигает
        # этап «караван едет»), потом пробуем бой по стандартному training-URL
        _accept(client, urls, qid)
        return _run_battle_quest(client, urls, dungeon_runner, qid,
                                 f"/training/h/{qid}")

    if status == "none":
        if not _donate_allowed(qid):
            return False
        ok, battle_url = _accept(client, urls, qid)
        if not ok:
            return False
        log_info(f"[TAVERN] Принят квест {qid}" + (" (бой)" if battle_url else ""))
        if battle_url:
            return _run_battle_quest(client, urls, dungeon_runner, qid, battle_url)
        # Мирный (взнос/награда): перечитываем — если готов, сдаём
        state = _quest_state(client, urls, qid)
        if state and state.get("status") == "complete":
            return _complete(client, urls, qid)
        if state and state.get("status") == "active":
            prog = state.get("progress") or {}
            if prog.get("current", 0) >= prog.get("total", 1):
                return _complete(client, urls, qid)
            log_debug(f"[TAVERN] {qid}: принят, прогресс "
                      f"{prog.get('current')}/{prog.get('total')} — дождёмся")
        return True

    return False


def _run_battle_quest(client, urls, dungeon_runner, qid, battle_url):
    """Серия боёв до выполнения прогресса, потом сдача."""
    for i in range(MAX_FIGHTS_PER_QUEST):
        outcome = _fight_training(client, dungeon_runner, battle_url, qid)
        if outcome == "died":
            log_warning(f"[TAVERN] Смерть в бою {qid} — караваны отложены")
            return False
        if outcome == "no_battle":
            # Игра не пустила (этап ещё не готов / караван в пути) — не ошибка
            return False
        if outcome == "error":
            return False
        state = _quest_state(client, urls, qid)
        if state is None:
            # Квест исчез из списка — вероятно завершён игрой
            log_info(f"[TAVERN] {qid} исчез из списка после боя — считаем сделанным")
            return True
        prog = state.get("progress") or {}
        if state.get("status") == "complete" or prog.get("current", 0) >= prog.get("total", 1):
            return _complete(client, urls, qid)
        log_debug(f"[TAVERN] {qid}: прогресс {prog.get('current')}/{prog.get('total')}, ещё бой")
    log_warning(f"[TAVERN] {qid}: не добили за {MAX_FIGHTS_PER_QUEST} боёв")
    return False


def run_tavern_caravans(client, dungeon_runner, force=False):
    """
    Главный вход: проходит доступные караван-квесты (взносы, сопровождения,
    награды, сюжетную цепочку). Вызывается из цикла бота, когда данжи на КД.

    Безопасность: любая ошибка гасится, цикл бота не ломается.
    """
    try:
        from requests_bot.config import is_tavern_caravans_enabled
        if not is_tavern_caravans_enabled():
            return 0

        cache = _load_cache()
        if not force and time.time() < cache.get("next_check", 0):
            return 0

        urls = _get_tavern_api(client)
        if urls is None:
            return 0

        quests = _fetch_quests(client, urls)
        if quests is None:
            return 0

        # Видимость в панели/TG: чем бот занят
        try:
            from requests_bot.bot import set_activity
            set_activity("🐫 Караваны таверны")
        except Exception:
            pass

        log_debug(f"[TAVERN] Караваны в таверне: "
                  f"{[(q['id'], q.get('status')) for q in quests]}")

        done = 0
        for q in quests:
            if done >= MAX_QUESTS_PER_RUN:
                break
            try:
                if _process_quest(client, urls, dungeon_runner, q):
                    done += 1
                    # Список квестов мог поменяться (next открылся) — перечитываем
                    quests_new = _fetch_quests(client, urls)
                    if quests_new is not None:
                        seen = {x.get("id") for x in quests}
                        fresh = [x for x in quests_new if x.get("id") not in seen]
                        quests.extend(fresh)
            except Exception as e:
                log_warning(f"[TAVERN] Ошибка квеста {q.get('id')}: {e}")

        cache["next_check"] = time.time() + CHECK_INTERVAL
        cache["last_run"] = time.time()
        _save_cache(cache)
        if done:
            log_info(f"[TAVERN] Караваны: обработано квестов: {done}")
        return done
    except Exception as e:
        log_warning(f"[TAVERN] Ошибка run_tavern_caravans: {e}")
        return 0
