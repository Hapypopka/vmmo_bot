# ============================================
# VMMO Char Info — снимок «паспорта» персонажа для веб-панели
# ============================================
# Веб-панель хочет показывать у каждого чара: сторону (Светлый/Тёмный),
# класс (Маг/Монах/Воин), уровень и сумму характеристик.
#
# Эти данные НЕ в шапке страницы (там только HP) и НЕ в обычном HTML профиля
# (блок статов рендерится JS). Живой источник — Wicket-AJAX эндпоинт профиля
# (`apiGetUrl` → pnlProfile-blockMain), отдающий JSON:
#   profile: { name, lvl, side(1=свет/2=тьма), class:{name}, title:{name},
#              stats:{ list:[ {id:"sum_stats", value:"34896"}, ... ] } }
#
# Снимаем редко (раз в TTL) прямо из сессии работающего бота и кладём в
# profiles/<char>/char_info.json — панель просто читает файл (и для
# остановленных ботов показывает последний снимок).
# ============================================

import os
import re
import json
import time

PROFILE_LINK_RE = re.compile(r'/user/(\d+)')
API_GET_RE = re.compile(r"apiGetUrl\s*[:=]\s*['\"]([^'\"]+)['\"]")

AJAX_HEADERS = {
    "Wicket-Ajax": "true",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "text/xml, */*; q=0.01",
}

# Снимок не чаще раза в N секунд. Держим час: статы меняются при апгрейде
# снаряжения, и ждать полдня обновления в панели — плохо. Разово по клику в
# панели можно форснуть мимо TTL (см. CLI ниже / /api/char_info/<p>/refresh).
REFRESH_TTL = 3600


def _char_info_path():
    from requests_bot.config import PROFILE_DIR
    return os.path.join(PROFILE_DIR, "char_info.json")


def _find_own_user_id(client):
    """Ищет свой user id по ссылке «Профиль» на главной странице."""
    client.get("/")
    soup = client.soup()
    if soup:
        for a in soup.select('a[href*="/user/"]'):
            if "Профиль" in a.get_text():
                m = PROFILE_LINK_RE.search(a.get("href", ""))
                if m:
                    return m.group(1)
    # fallback: любая ссылка на /user/<id>
    m = PROFILE_LINK_RE.search(client.current_page or "")
    return m.group(1) if m else None


def _to_int(value):
    try:
        return int(re.sub(r"[^\d]", "", str(value)) or 0)
    except Exception:
        return None


def fetch(client):
    """
    Снимает «паспорт» персонажа из сессии клиента.

    Returns:
        dict | None: {name, level, side, class, title, sum_stats, updated}
    """
    uid = _find_own_user_id(client)
    if not uid:
        return None

    client.get(f"/user/{uid}")
    html = client.current_page or ""
    m = API_GET_RE.search(html)
    if not m:
        return None

    url = m.group(1).replace("&amp;", "&")
    headers = dict(AJAX_HEADERS)
    headers["Wicket-Ajax-BaseURL"] = f"user/{uid}"
    try:
        resp = client.session.get(url, headers=headers, timeout=30)
        data = json.loads(resp.text)
    except Exception:
        return None

    p = data.get("profile") or {}
    if not p:
        return None

    sum_stats = None
    for s in (p.get("stats") or {}).get("list", []):
        if s.get("id") == "sum_stats":
            sum_stats = _to_int(s.get("value"))
            break

    return {
        "name": p.get("name"),
        "level": p.get("lvl"),
        "side": p.get("side"),            # 1 = Светлый, 2 = Тёмный
        "class": (p.get("class") or {}).get("name"),
        "title": (p.get("title") or {}).get("name"),
        "sum_stats": sum_stats,
        "updated": int(time.time()),
    }


def save(info):
    """Атомарно пишет снимок в profiles/<char>/char_info.json."""
    if not info:
        return False
    try:
        path = _char_info_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _is_fresh():
    """True если снимок ещё свежий (моложе TTL) — тогда не дёргаем сервер."""
    try:
        path = _char_info_path()
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (time.time() - data.get("updated", 0)) < REFRESH_TTL
    except Exception:
        return False


def refresh_if_stale(client, force=False):
    """
    Снимает паспорт, если предыдущий снимок протух (или его нет).
    Никогда не роняет вызывающего — все ошибки глушим.

    Args:
        force: снять снимок даже если предыдущий ещё свежий (ручное обновление)

    Returns:
        bool: True если сняли и сохранили новый снимок
    """
    try:
        if not force and _is_fresh():
            return False
        info = fetch(client)
        if info:
            return save(info)
    except Exception:
        pass
    return False


def _cli():
    """
    Ручное снятие паспорта из куков профилей (как debug_cli — без login/logout,
    безопасно для работающих ботов). Форсит снимок мимо TTL.

        python3 -m requests_bot.char_info            # все профили
        python3 -m requests_bot.char_info char28     # один/несколько
    """
    import sys
    import glob
    os.environ.setdefault("VMMO_LOG_REQUESTS", "0")
    from requests_bot import config as cfg
    from requests_bot.client import VMMOClient

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profs = sys.argv[1:]
    if not profs:
        profs = sorted(
            (os.path.basename(os.path.dirname(p))
             for p in glob.glob(os.path.join(base, "profiles", "char*", "cookies.json"))),
            key=lambda s: int("".join(filter(str.isdigit, s)) or 0),
        )

    ok = 0
    for prof in profs:
        try:
            cfg.set_profile(prof)
            client = VMMOClient()
            client.load_cookies(os.path.join(base, "profiles", prof, "cookies.json"))
            info = fetch(client)
            if info and save(info):
                ok += 1
                print(f"{prof}: {info['name']} {info['level']}ур side={info['side']} sum={info['sum_stats']}")
            else:
                print(f"{prof}: нет данных")
        except Exception as e:
            print(f"{prof}: ERR {e}")
    print(f"OK {ok}/{len(profs)}")


if __name__ == "__main__":
    _cli()
