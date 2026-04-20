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

# Путь к проекту — чтобы запуск работал и из корня, и из requests_bot/
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_here))

from requests_bot.client import VMMOClient
from requests_bot.constants import Patterns


def _make_client(profile: str) -> VMMOClient:
    """Создаёт клиент с куками указанного профиля (без логина)."""
    from requests_bot import config as cfg
    # Явно указываем профиль через env — config.py читает VMMO_PROFILE
    os.environ["VMMO_PROFILE"] = profile
    # Перечитываем конфиг (на случай если он уже кешировал профиль)
    cookies_path = os.path.join(_here, "..", "profiles", profile, "cookies.json")
    cookies_path = os.path.normpath(cookies_path)

    client = VMMOClient()
    if not os.path.exists(cookies_path):
        print(f"[ERR] Куки не найдены: {cookies_path}", file=sys.stderr)
        sys.exit(2)
    # Напрямую передаём путь — не полагаемся на config.COOKIES_FILE
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
    client = _make_client(args.profile)
    handler, _ = COMMANDS[args.cmd]
    handler(client, args)


if __name__ == "__main__":
    main()
