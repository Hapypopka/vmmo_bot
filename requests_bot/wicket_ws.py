"""Wicket WebSocket client для прослушки push-уведомлений игры.

Контекст:
    Игра пушит уведомления (приглашения в банду, чат, лут) через
    Wicket WebSocket. HTTP-only бот их пропускает — сервер кладёт
    в очередь WS-канала и не возвращает в HTML страниц.

URL и параметры выяснены через MCP-браузер (Шнейне в /city):
    wss://vmmo.vten.ru/wicket/websocket
        ?pageId=<int>
        &context=com.playtox.shadows.wicket.pages.<class>
        &wicket-ajax-baseurl=<path>
        &wicket-app-name=WicketApplicationFilter

Сервер шлёт XML-сообщения вида:
    <ajax-response ptxMsgId="N">
        <component id="...">...</component>
        <priority-evaluate><![CDATA[...JS...]]></priority-evaluate>
    </ajax-response>

Клиент должен отвечать ack-сообщениями:
    "#N prepared in X.X msec"
    "#N processed in X.X msec"

Сервер по этим ack считает что сообщение доставлено. Без ack
очередь может накапливаться и сервер будет fallback'ить в HTML
(но только в первые ~2 минуты сессии — потом перестаёт).
"""

import re
import time
import json
import threading
from urllib.parse import urlparse

try:
    import websocket
except ImportError:
    websocket = None

from requests_bot.logger import log_info, log_debug, log_warning, log_error


WS_BASE = "wss://vmmo.vten.ru/wicket/websocket"
WICKET_APP_NAME = "WicketApplicationFilter"

# Параметры записаны в HTML как JS-литерал (не JSON), пример:
#   Ptx.Shadows.WebSocket.params = {
#       pageId: 1,  context: 'com.playtox....DungeonCombatPage', ...
#       baseUrl: 'dungeon/combat/demonsBaron', ...
#   }
# Парсим отдельные поля регуляркой — JSON.loads тут не сработает.
#
# Игра иногда рендерит chained-assign:
#   Ptx.Shadows.WebSocket.params = params = { ... }
# Поэтому позволяем любые символы между `=` и `{`.
_WS_BLOCK_RE = re.compile(
    r'Ptx\.Shadows\.WebSocket\.params\s*=[^{]*\{([^}]+)\}',
    re.DOTALL,
)
_FIELD_PAGE_ID = re.compile(r'pageId\s*:\s*(\d+)')
_FIELD_CONTEXT = re.compile(r'context\s*:\s*["\']([^"\']+)["\']')
_FIELD_BASE_URL = re.compile(r'baseUrl\s*:\s*["\']([^"\']*)["\']')
_PAGE_ID_FALLBACK_RE = re.compile(r'window\.ptxPageId\s*=\s*(\d+)')

# Маркеры приглашения в банду — для invite от лидера
_INVITE_MARKERS = ("приглашает тебя в банду", "feedbackAction=accept")
_FEEDBACK_ACCEPT_RE = re.compile(r'href=\\?"([^"]*feedbackAction=accept[^"]*)\\?"')
_INVITER_RE = re.compile(
    r'<b[^>]*>([^<]+?)</b>\s*приглашает тебя в банду',
)


def extract_ws_params_from_html(html):
    """Достаёт WS-параметры (pageId, context, baseUrl) из HTML страницы.

    Returns:
        dict с pageId/context/baseUrl или None если не нашли.
    """
    if not html:
        return None

    # Ищем блок WebSocket.params = {...} и парсим поля по отдельности
    block_m = _WS_BLOCK_RE.search(html)
    if block_m:
        body = block_m.group(1)
        page_id_m = _FIELD_PAGE_ID.search(body)
        context_m = _FIELD_CONTEXT.search(body)
        base_url_m = _FIELD_BASE_URL.search(body)
        if page_id_m and context_m:
            return {
                "pageId": int(page_id_m.group(1)),
                "context": context_m.group(1),
                "baseUrl": base_url_m.group(1) if base_url_m else "",
            }

    # Fallback по window.ptxPageId
    page_id_m = _PAGE_ID_FALLBACK_RE.search(html)
    if page_id_m:
        return {
            "pageId": int(page_id_m.group(1)),
            "context": "",
            "baseUrl": "",
        }
    return None


def _build_ws_url(page_id, context, base_url):
    from urllib.parse import quote
    return (
        f"{WS_BASE}"
        f"?pageId={page_id}"
        f"&context={quote(context)}"
        f"&wicket-ajax-baseurl={quote(base_url)}"
        f"&wicket-app-name={WICKET_APP_NAME}"
    )


def _cookies_to_header(session):
    """requests.Session cookies → Cookie: header string."""
    parts = []
    for c in session.cookies:
        # Только vmmo.vten.ru / .vmmo.vten.ru cookies
        if c.domain and "vmmo.vten.ru" not in c.domain and ".vten.ru" not in c.domain:
            continue
        parts.append(f"{c.name}={c.value}")
    return "; ".join(parts)


class WicketWSListener:
    """Слушает Wicket WebSocket в фоновом потоке.

    Использование:
        listener = WicketWSListener(client, page_id=4, context="...", base_url="city")
        listener.start()
        # ... основная логика бота ...
        invite = listener.wait_for_invite(timeout=60, leader_username="Пупупу Пупупу")
        if invite:
            client.get(invite["accept_url"])
        listener.stop()

    Threadsafe — основной поток просто ждёт через wait_for_invite,
    WS-поток наполняет внутренний буфер событий.
    """

    def __init__(self, client, page_id, context, base_url):
        if websocket is None:
            raise RuntimeError("websocket-client не установлен (pip install websocket-client)")
        self.client = client
        self.page_id = int(page_id)
        self.context = context
        self.base_url = base_url
        self.ws_url = _build_ws_url(page_id, context, base_url)
        self._ws = None
        self._thread = None
        self._stop = threading.Event()

        # Для invite-ожидания
        self._invite_event = threading.Event()
        self._pending_invite = None  # dict {accept_url, inviter_name, raw_message}
        self._lock = threading.Lock()

        # Счётчик полученных сообщений (для статистики)
        self._messages_received = 0
        self._invite_filter_username = None  # ожидаемый ник лидера или None для любого

    # ---------- Public API ----------

    def start(self):
        """Запускает WS-соединение в фоновом потоке."""
        cookie_header = _cookies_to_header(self.client.session)
        ua = self.client.session.headers.get("User-Agent", "Mozilla/5.0")

        headers = {
            "Cookie": cookie_header,
            "User-Agent": ua,
            "Origin": "https://vmmo.vten.ru",
        }

        self._ws = websocket.WebSocketApp(
            self.ws_url,
            header=[f"{k}: {v}" for k, v in headers.items()],
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self._thread = threading.Thread(
            target=self._ws.run_forever,
            kwargs={"ping_interval": 20, "ping_timeout": 10},
            daemon=True,
            name=f"WicketWS-{self.page_id}",
        )
        self._thread.start()
        log_debug(f"[WS] Запущен слушатель: pageId={self.page_id} ctx={self.context[-30:]}")

    def stop(self):
        """Закрывает WS и останавливает поток."""
        self._stop.set()
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=2)
        log_debug(f"[WS] Слушатель остановлен (получено {self._messages_received} сообщений)")

    def wait_for_invite(self, timeout=60, leader_username=None):
        """Ждёт инвайт от лидера через WS.

        Args:
            timeout: максимум секунд ждать
            leader_username: фильтр по никнейму лидера (None = любой)

        Returns:
            dict {accept_url, inviter_name, raw} если получили
            None если timeout
        """
        self._invite_filter_username = leader_username
        self._invite_event.clear()
        with self._lock:
            self._pending_invite = None

        if self._invite_event.wait(timeout):
            with self._lock:
                return self._pending_invite
        return None

    # ---------- Internal callbacks ----------

    def _on_open(self, ws):
        log_debug(f"[WS] Open pageId={self.page_id}")

    def _on_close(self, ws, code, reason):
        log_debug(f"[WS] Close code={code} reason={reason}")

    def _on_error(self, ws, error):
        log_debug(f"[WS] Error: {error}")

    def _on_message(self, ws, message):
        """Обработка входящего сообщения от сервера.

        Сервер шлёт XML <ajax-response ptxMsgId="N">...</ajax-response>.
        Мы должны:
        1. Ответить ack ("#N prepared in X.X msec" + "#N processed in X.X msec")
        2. Проверить наличие маркеров приглашения в content.
        """
        self._messages_received += 1

        if not isinstance(message, str):
            try:
                message = message.decode("utf-8", errors="ignore")
            except Exception:
                return

        # Ack: извлекаем ptxMsgId и шлём подтверждения
        msg_id_m = re.search(r'ptxMsgId="(\d+)"', message)
        if msg_id_m:
            msg_id = msg_id_m.group(1)
            try:
                # Имитируем точно такой же формат как настоящий клиент
                self._ws.send(f"#{msg_id} prepared in 0.2 msec")
                self._ws.send(f"#{msg_id} processed in 0.5 msec")
            except Exception:
                pass

        # Проверяем маркеры приглашения
        if any(marker in message for marker in _INVITE_MARKERS):
            self._extract_invite(message)

    def _extract_invite(self, message):
        """Парсит invite-сообщение и заполняет _pending_invite."""
        # Ник пригласившего (если есть)
        inviter_m = _INVITER_RE.search(message)
        inviter_name = inviter_m.group(1).strip() if inviter_m else None

        # Если стоит фильтр по никнейму — проверяем
        if self._invite_filter_username:
            expected = self._invite_filter_username.strip()
            if inviter_name and inviter_name != expected:
                log_debug(f"[WS] Invite от '{inviter_name}', а ждём '{expected}' — игнорирую")
                return

        # Извлекаем feedbackAction=accept URL.
        # WS-сообщения содержат escaped JSON: href=\"URL\"
        accept_m = _FEEDBACK_ACCEPT_RE.search(message)
        if not accept_m:
            log_debug("[WS] Найден маркер invite, но accept URL не извлечён")
            return

        accept_url = accept_m.group(1).replace("&amp;", "&").replace("\\/", "/")
        if not accept_url.startswith("http"):
            accept_url = "https://vmmo.vten.ru" + accept_url

        log_info(f"[WS] ⚡ Получен инвайт от '{inviter_name or '?'}'")

        with self._lock:
            self._pending_invite = {
                "accept_url": accept_url,
                "inviter_name": inviter_name,
                "raw": message[:1000],
            }
        self._invite_event.set()


def listener_for_current_page(client):
    """Создаёт listener'а на основе текущей страницы клиента.

    Перед вызовом убедись что client.current_page содержит свежий HTML
    с Ptx.Shadows.WebSocket.params (после get на /city, /backpack и т.п.).

    Returns:
        WicketWSListener (не запущенный) или None если параметры не нашлись.
    """
    params = extract_ws_params_from_html(client.current_page)
    if not params or params.get("pageId") is None or not params.get("context"):
        log_debug("[WS] Не удалось извлечь WS-параметры из HTML")
        return None

    return WicketWSListener(
        client,
        page_id=params["pageId"],
        context=params["context"],
        base_url=params["baseUrl"] or "city",
    )
