"""
Debug CLI для VMMO Bot.

Позволяет быстро изучать HTML/AJAX страниц игры без скриншотов и браузера.
Использует куки работающего профиля — НЕ вызывает login/logout, безопасно
для параллельно работающих ботов.

Запуск на сервере:
    ssh -i ~/.ssh/id_ed25519_vmmo root@45.131.187.128 \\
        "cd /home/claude/vmmo_bot && python3 -m requests_bot.debug_cli <cmd> ..."

Команды:
    get <url>                        — HTML страницы (truncate по --limit)
    select <url> <css>               — все совпадения CSS-селектора (text + attrs)
    text <url> <css>                 — только текст селектора (strip)
    ajax-urls <url> [substr]         — Wicket AJAX c/u пары (опц. фильтр по подстроке)
    wicket <url> <element_id>        — конкретный AJAX URL по c-id
    links <url> [substr]             — все ссылки (a href)
    find <url> <regex>               — произвольный regex по HTML
    title <url>                      — <title> страницы
    url <url>                        — финальный URL после редиректов
    check-entry <dungeon_id>         — проверить почему не работает вход в данж
                                        (запустит логику бота и скажет причину)
    last-requests [N] [filter]       — последние N HTTP-запросов работающего бота
                                        (читает logs/requests/<profile>.jsonl)
    tail-requests                    — live-tail запросов работающего бота (follow)

Опции:
    --profile <name>   Профиль для куков (default: char3)
    --limit <n>        Обрезать HTML/текст до N символов (default: 2000)
    --raw              Без форматирования, сырой вывод
"""
import argparse
import json
import re
import sys
import os
import time

# Путь к проекту — чтобы запуск работал и из корня, и из requests_bot/
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_here))

from requests_bot.client import VMMOClient
from requests_bot.constants import Patterns


def _make_client(profile: str) -> VMMOClient:
    """Создаёт клиент с куками указанного профиля (без логина).

    Важно: вызываем config.set_profile чтобы VMMOClient мог открыть корректный
    request log файл (<profile>.jsonl) — без этого get_profile_name() вернёт None
    и файл будет называться unknown.jsonl.
    """
    from requests_bot import config as cfg
    # КРИТИЧНО: отключаем file-logging в клиенте debug_cli, чтобы не затереть
    # JSONL работающего бота (он открывается с truncate при старте).
    os.environ["VMMO_LOG_REQUESTS"] = "0"

    try:
        cfg.set_profile(profile)
    except Exception as e:
        print(f"[WARN] set_profile({profile}) failed: {e}", file=sys.stderr)

    cookies_path = os.path.join(_here, "..", "profiles", profile, "cookies.json")
    cookies_path = os.path.normpath(cookies_path)

    client = VMMOClient()
    if not os.path.exists(cookies_path):
        print(f"[ERR] Куки не найдены: {cookies_path}", file=sys.stderr)
        sys.exit(2)
    client.load_cookies(cookies_path)
    return client


def _fetch(client: VMMOClient, url: str) -> str:
    resp = client.get(url)
    if resp is None or not client.current_page:
        print("[ERR] Не удалось загрузить страницу", file=sys.stderr)
        sys.exit(3)
    return client.current_page


def cmd_get(client, args):
    html = _fetch(client, args.url)
    out = html if args.raw else html[: args.limit]
    print(out)
    if not args.raw and len(html) > args.limit:
        print(f"\n... (обрезано, {len(html)} всего, покажи --limit 0 или --raw для полного)")


def cmd_select(client, args):
    _fetch(client, args.url)
    soup = client.soup()
    matches = soup.select(args.css) if soup else []
    print(f"[*] {len(matches)} совпадений по '{args.css}'")
    for i, el in enumerate(matches, 1):
        text = el.get_text(strip=True)[:120]
        attrs = {k: v for k, v in el.attrs.items() if k in ("id", "class", "href", "data-id", "title")}
        print(f"  [{i}] <{el.name}> {attrs} → {text!r}")


def cmd_text(client, args):
    _fetch(client, args.url)
    soup = client.soup()
    for el in (soup.select(args.css) if soup else []):
        print(el.get_text(strip=True))


def cmd_ajax_urls(client, args):
    html = _fetch(client, args.url)
    urls = {}
    for element_id, url in Patterns.WICKET_AJAX.findall(html):
        urls[element_id] = url
    # Альтернативный порядок "c","u"
    for element_id, url in re.findall(r'"c":"([^"]+)","u":"([^"]+)"', html):
        urls.setdefault(element_id, url)

    substr = args.filter
    filtered = {k: v for k, v in urls.items() if not substr or substr in k or substr in v}
    print(f"[*] {len(filtered)} AJAX URLs" + (f" (фильтр '{substr}')" if substr else ""))
    for element_id, url in filtered.items():
        print(f"  {element_id}")
        print(f"    → {url}")


def cmd_wicket(client, args):
    html = _fetch(client, args.url)
    for element_id, url in Patterns.WICKET_AJAX.findall(html):
        if element_id == args.element_id:
            print(url)
            return
    for element_id, url in re.findall(r'"c":"([^"]+)","u":"([^"]+)"', html):
        if element_id == args.element_id:
            print(url)
            return
    print(f"[ERR] AJAX URL для '{args.element_id}' не найден", file=sys.stderr)
    sys.exit(4)


def cmd_links(client, args):
    _fetch(client, args.url)
    soup = client.soup()
    if not soup:
        return
    substr = args.filter
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if substr and substr not in href:
            continue
        text = a.get_text(strip=True)[:80]
        print(f"  {href}  —  {text!r}")


def cmd_find(client, args):
    html = _fetch(client, args.url)
    matches = re.findall(args.regex, html)
    print(f"[*] {len(matches)} совпадений")
    for m in matches[:50]:
        print(f"  {m!r}")


def cmd_title(client, args):
    _fetch(client, args.url)
    soup = client.soup()
    t = soup.find("title") if soup else None
    print(t.get_text(strip=True) if t else "(нет title)")


def cmd_url(client, args):
    _fetch(client, args.url)
    print(client.current_url)


def _log_path(profile):
    """Путь к JSONL-логу HTTP запросов работающего бота."""
    return os.path.join(os.path.dirname(_here), "logs", "requests", f"{profile}.jsonl")


def _format_log_entry(entry):
    """Одна строка лога для человека."""
    status = entry.get("status", "?")
    ms = entry.get("ms", 0)
    size = entry.get("size", 0)
    method = entry.get("method", "?")
    url = entry.get("url", "")[:100]
    # Сокращаем полный URL (убираем base + query, оставляем path)
    url_short = url.replace("https://vmmo.vten.ru", "").replace("https://m.vten.ru", "")
    ts = entry.get("ts", "")
    return f"  {ts}  {method:4} {status} {ms:4}ms {size:6}B  {url_short}"


def cmd_last_requests(client, args):
    """Показывает последние N запросов работающего бота из JSONL."""
    path = _log_path(args.profile)
    if not os.path.exists(path):
        print(f"[ERR] Лог не найден: {path}")
        print("[HINT] Бот должен быть запущен с включённым VMMO_LOG_REQUESTS (по умолчанию on).")
        return

    n = int(args.n) if args.n else 50
    filter_sub = args.filter

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    entries = []
    for line in lines:
        try:
            e = json.loads(line)
            if filter_sub and filter_sub not in e.get("url", ""):
                continue
            entries.append(e)
        except Exception:
            continue

    entries = entries[-n:]
    print(f"[*] Последние {len(entries)} запросов{' (фильтр: ' + filter_sub + ')' if filter_sub else ''}:")
    for e in entries:
        print(_format_log_entry(e))


def cmd_tail_requests(client, args):
    """Live-tail запросов: читает файл построчно по мере появления."""
    path = _log_path(args.profile)
    if not os.path.exists(path):
        print(f"[ERR] Лог не найден: {path}")
        return

    # Открываем, seek в конец, читаем новые строки
    print(f"[*] Tail {path} (Ctrl+C для выхода)")
    with open(path, "r", encoding="utf-8") as f:
        f.seek(0, 2)  # в конец
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            try:
                e = json.loads(line)
                print(_format_log_entry(e))
            except Exception:
                pass


def cmd_check_entry(client, args):
    """Прогоняет логику входа в данж и объясняет почему не вышло.

    Это главный debug-инструмент для кейсов типа 'char13 зациклился на Barony'.
    Делает всё что делает бот, но вместо попытки войти — печатает диагноз.
    """
    from requests_bot.run_dungeon import DungeonRunner
    import re

    dungeon_id = args.dungeon_id
    # Извлекаем короткое имя из 'dng:Barony' → 'Barony'
    short_name = dungeon_id.split(":", 1)[1] if ":" in dungeon_id else dungeon_id

    print(f"[*] Проверяю вход в {dungeon_id} (профиль: {args.profile})")
    print()

    # 1. Получаем API link как это делает бот
    resp = client.get("/dungeons?52")
    api_link_match = re.search(r"apiLinkUrl:\s*'([^']+)'", client.current_page or "")
    if not api_link_match:
        print("[ERR] apiLinkUrl не найден — возможно не залогинен")
        return
    api_link_url = api_link_match.group(1)

    # 2. Запрашиваем redirect
    import requests as _rq
    enter_url = f"{api_link_url}&link_id={dungeon_id}"
    headers = {"Accept": "application/json, text/javascript, */*; q=0.01",
               "X-Requested-With": "XMLHttpRequest"}
    try:
        data = client.session.get(enter_url, headers=headers, timeout=10).json()
    except Exception as e:
        print(f"[ERR] API enter: {e}")
        return

    if data.get("status") != "redirect":
        print(f"[FAIL] API вернул не redirect: {data}")
        return

    landing_url = data["url"]
    if not landing_url.endswith("/normal"):
        landing_url += "/normal"
    print(f"[OK] Landing URL: {landing_url}")

    # 3. Загружаем landing и диагностируем
    client.get(landing_url)
    print(f"[OK] Loaded: {client.current_url}")
    print()

    # 4. Прогоняем через ту же логику что enter_dungeon
    runner = DungeonRunner(client)
    html = client.current_page or ""

    # Копия логики поиска кнопки входа из enter_dungeon
    enter_btn = None
    for pat_name, pat in [
        ("standby", r'href="([^"]*dungeon/standby/[^"?]+)"'),
        ("ILinkListener", r'href=["\']([^"\']*ILinkListener[^"\']*enterLinksPanel[^"\']*)["\']'),
    ]:
        m = re.search(pat, html)
        if m:
            enter_btn = (pat_name, m.group(1))
            break
    if not enter_btn:
        soup = client.soup()
        if soup:
            for btn in soup.select("a.go-btn"):
                txt = btn.get_text(strip=True)
                href = btn.get("href", "")
                if "Войти" in txt and href and href != "#":
                    enter_btn = ("go-btn_Войти", href)
                    break

    if enter_btn:
        print(f"[OK] Кнопка входа найдена ({enter_btn[0]}): {enter_btn[1][:100]}")
        print("[RESULT] Вход возможен — бот должен пройти.")
        return

    # 5. Нет кнопки — диагностируем причину
    reason, detail = runner._diagnose_no_entry(html)
    print(f"[FAIL] Кнопка входа не найдена!")
    print(f"[DIAGNOSIS] reason={reason!r}, detail={detail!r}")

    if reason == "prerequisite":
        print(f"\n[ROOT CAUSE] Игра требует сначала пройти: {detail}")
        print(f"→ Bot.py теперь скипнет '{dungeon_id}' через record_lock(reason='prerequisite')")
    elif reason == "level":
        print(f"\n[ROOT CAUSE] Недостаточный уровень (нужен {detail})")
    else:
        print(f"\n[ROOT CAUSE] Неизвестно. HTML-фрагменты рядом с 'Сначала'/'уровен':")
        for m in re.finditer(r'.{0,80}(?:Сначала|уровен|заблок|недоступ).{0,80}', html, re.IGNORECASE):
            print(f"  > {m.group(0)[:200]}")


COMMANDS = {
    "get": (cmd_get, [("url", {})]),
    "select": (cmd_select, [("url", {}), ("css", {})]),
    "text": (cmd_text, [("url", {}), ("css", {})]),
    "ajax-urls": (cmd_ajax_urls, [("url", {}), ("filter", {"nargs": "?", "default": None})]),
    "wicket": (cmd_wicket, [("url", {}), ("element_id", {})]),
    "links": (cmd_links, [("url", {}), ("filter", {"nargs": "?", "default": None})]),
    "find": (cmd_find, [("url", {}), ("regex", {})]),
    "title": (cmd_title, [("url", {})]),
    "url": (cmd_url, [("url", {})]),
    "check-entry": (cmd_check_entry, [("dungeon_id", {})]),
    "last-requests": (cmd_last_requests, [
        ("n", {"nargs": "?", "default": None}),
        ("filter", {"nargs": "?", "default": None}),
    ]),
    "tail-requests": (cmd_tail_requests, []),
}


def main():
    parser = argparse.ArgumentParser(
        description="VMMO Bot debug CLI — быстрая инспекция HTML/AJAX без браузера",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--profile", default="char3", help="Профиль для куков (default: char3)")
    parser.add_argument("--limit", type=int, default=2000, help="Обрезать вывод до N символов")
    parser.add_argument("--raw", action="store_true", help="Сырой вывод без обрезки")

    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, (_, pos_args) in COMMANDS.items():
        sp = sub.add_parser(name)
        for arg_name, arg_opts in pos_args:
            sp.add_argument(arg_name, **arg_opts)

    args = parser.parse_args()
    # File-only команды не требуют HTTP-клиента и куков
    file_only = {"last-requests", "tail-requests"}
    client = None if args.cmd in file_only else _make_client(args.profile)
    handler, _ = COMMANDS[args.cmd]
    handler(client, args)


if __name__ == "__main__":
    main()
