# ============================================
# VMMO WebSocket Client
# ============================================
# Получает события боя через WebSocket
# Используется для сбора лута (dropLoot events)
# ============================================

import re
import json
import threading
import time
from queue import Queue, Empty
from urllib.parse import urlencode

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    print("[WARN] websocket-client not installed. Run: pip install websocket-client")


class VMMMOWebSocket:
    """
    WebSocket клиент для VMMO.
    Слушает события боя и собирает ID лута из dropLoot сообщений.
    """

    def __init__(self, session_cookies, page_id, context_class="DungeonCombatPage"):
        """
        Args:
            session_cookies: Куки из requests сессии
            page_id: ID страницы (из window.ptxPageId)
            context_class: Класс страницы для контекста
        """
        if not WEBSOCKET_AVAILABLE:
            raise ImportError("websocket-client library required")

        self.page_id = page_id
        self.context_class = context_class
        self.cookies = session_cookies

        # Очередь для ID лута
        self.loot_queue = Queue()
        self.loot_ids = []  # Все полученные ID

        # WebSocket
        self.ws = None
        self.ws_thread = None
        self.running = False
        self.connected = False

        # lootTakeUrl для сбора
        self.loot_take_url = None

    def _build_ws_url(self, base_url="dungeon/combat"):
        """Строит URL для WebSocket соединения"""
        # wss://vmmo.vten.ru/wicket/websocket?pageId=XXX&context=...
        params = {
            "pageId": self.page_id,
            "context": f"com.playtox.shadows.wicket.pages.dungeon.combat.{self.context_class}",
            "wicket-ajax-baseurl": base_url,
            "wicket-app-name": "WicketApplicationFilter",
        }
        return f"wss://vmmo.vten.ru/wicket/websocket?{urlencode(params)}"

    def _get_cookie_header(self):
        """Формирует Cookie header из requests cookies"""
        if hasattr(self.cookies, 'items'):
            # requests CookieJar
            return "; ".join([f"{name}={value}" for name, value in self.cookies.items()])
        return str(self.cookies)

    def _on_message(self, ws, message):
        """Обработка входящих сообщений"""
        # Ищем dropLoot в сообщении
        # Формат: Ptx.Shadows.Combat.dropLoot({\n                id: '127275',
        if "dropLoot" in message:
            print(f"[WS] dropLoot found in message!")
            # Ищем все id: '123456' после каждого dropLoot
            for match in re.finditer(r"dropLoot", message):
                start = match.end()
                # Берём 200 символов после dropLoot (там могут быть переносы и пробелы)
                fragment = message[start:start+200]
                id_match = re.search(r"id:\s*'(\d+)'", fragment)
                if id_match:
                    loot_id = id_match.group(1)
                    if loot_id not in self.loot_ids:
                        self.loot_ids.append(loot_id)
                        self.loot_queue.put(loot_id)
                        print(f"[WS-LOOT] Упал лут: {loot_id}")
                else:
                    print(f"[WS] dropLoot but no id found in: {fragment[:50]}")

    def _on_error(self, ws, error):
        """Обработка ошибок"""
        print(f"[WS] Error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Обработка закрытия соединения"""
        self.connected = False
        print(f"[WS] Соединение закрыто")

    def _on_open(self, ws):
        """Обработка открытия соединения"""
        self.connected = True
        print(f"[WS] Соединение установлено (page_id={self.page_id})")
        # Отправляем pageId для регистрации
        ws.send(f"pageId: {self.page_id}")

    def connect(self, base_url="dungeon/combat"):
        """Подключается к WebSocket"""
        if self.running:
            return True

        ws_url = self._build_ws_url(base_url)
        cookie_header = self._get_cookie_header()

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
            cookie=cookie_header,
            header={
                "Origin": "https://vmmo.vten.ru",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/128.0",
            }
        )

        self.running = True
        self.ws_thread = threading.Thread(target=self._run_forever, daemon=True)
        self.ws_thread.start()

        # Ждём подключения
        for _ in range(50):  # 5 секунд
            if self.connected:
                return True
            time.sleep(0.1)

        print("[WS] Не удалось подключиться за 5 секунд")
        return False

    def _run_forever(self):
        """Запускает WebSocket в отдельном потоке"""
        try:
            self.ws.run_forever(
                ping_interval=30,
                ping_timeout=10,
            )
        except Exception as e:
            print(f"[WS] Run error: {e}")
        finally:
            self.running = False
            self.connected = False

    def disconnect(self):
        """Закрывает соединение"""
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        self.connected = False

    def get_pending_loot(self, timeout=0.1):
        """
        Возвращает список ID лута из очереди.
        Non-blocking, возвращает всё что накопилось.
        """
        loot_ids = []
        while True:
            try:
                loot_id = self.loot_queue.get(timeout=timeout)
                loot_ids.append(loot_id)
            except Empty:
                break
        return loot_ids

    def get_all_loot_ids(self):
        """Возвращает все ID лута полученные за сессию"""
        return list(self.loot_ids)

    def clear_loot(self):
        """Очищает очередь и список лута"""
        self.loot_ids.clear()
        while not self.loot_queue.empty():
            try:
                self.loot_queue.get_nowait()
            except Empty:
                break

    def set_loot_url(self, loot_take_url):
        """Устанавливает базовый URL для сбора лута"""
        self.loot_take_url = loot_take_url

    def is_connected(self):
        """Проверяет активно ли соединение"""
        return self.connected and self.running


def extract_page_id_from_html(html):
    """Извлекает page_id из window.ptxPageId в HTML"""
    if not html:
        return None
    match = re.search(r'window\.ptxPageId\s*=\s*(\d+)', html)
    if match:
        return match.group(1)
    return None


# Тест
if __name__ == "__main__":
    print("WebSocket client module loaded")
    print(f"websocket-client available: {WEBSOCKET_AVAILABLE}")
