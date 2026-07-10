# ============================================
# VMMO Heal - отхил перед данжем (кружка в таверне)
# ============================================
# Проблема: бот мог полезть в данж недохиленным после предыдущего данжа —
# смерть, понижение сложности, в итоге данж улетал в вечный skip, хотя
# персонаж его тянет.
#
# Решение: перед входом в данж читаем свой HP% из шапки (есть на КАЖДОЙ
# странице: <span class="i12 i12-heart_NN"> — NN и есть процент). Если ниже
# порога — пьём кружку в таверне (Ptx.Shadows.Ui.Tavern.apiDrinkUrl,
# стоит 1 серебро, работает вне боя).
#
# Никогда не блокируем вход: не смогли распарсить/отхилить — идём как есть,
# просто логируем. Хуже не делаем.
# ============================================

import re
import time

# NN в i12-heart_NN = процент HP (проверено: heart_100 на здоровых страницах,
# heart_66 + class="warn" на цифре при 66% HP)
HP_RE = re.compile(r'i12-heart_(\d+)')
DRINK_URL_RE = re.compile(r"apiDrinkUrl\s*=\s*'([^']+)'")

API_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

MAX_DRINKS = 3  # предохранитель: не больше 3 кружек за раз (3 серебра)


def get_own_hp_percent(html):
    """Процент HP из шапки страницы (None если не нашли)."""
    if not html:
        return None
    m = HP_RE.search(html)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def ensure_healed(client, threshold=90):
    """
    Проверяет HP и при необходимости хилит кружкой в таверне.

    Args:
        client: VMMOClient
        threshold: минимальный HP% для входа в данж

    Returns:
        bool: True если HP >= threshold (или не смогли проверить — не блокируем)
    """
    try:
        # Шапка с HP есть на каждой странице — сперва пробуем уже загруженную
        # (нулевая цена), /city дёргаем только если там HP не нашёлся.
        hp = get_own_hp_percent(getattr(client, "current_page", None))
        if hp is None:
            resp = client.get("/city")
            hp = get_own_hp_percent(resp.text if resp is not None else None)
        if hp is None:
            print("[HEAL] Не смог распарсить HP из шапки — иду как есть")
            return True
        if hp >= threshold:
            return True

        print(f"[HEAL] HP {hp}% < {threshold}% — иду в таверну за кружкой")

        for attempt in range(MAX_DRINKS):
            # Таверна: парсим apiDrinkUrl (URL сессионный, каждый раз свежий)
            resp = client.get("/tavern")
            html = resp.text if resp is not None else ""

            hp = get_own_hp_percent(html)
            if hp is not None and hp >= threshold:
                print(f"[HEAL] HP уже {hp}% — отхилен")
                return True

            m = DRINK_URL_RE.search(html)
            if not m:
                print("[HEAL] Не нашёл apiDrinkUrl в таверне — иду как есть")
                return True

            drink_url = m.group(1).replace("&amp;", "&")
            print(f"[HEAL] Пью кружку ({attempt + 1}/{MAX_DRINKS})...")
            try:
                client.session.get(drink_url, headers=API_HEADERS, timeout=30)
            except Exception as e:
                print(f"[HEAL] Ошибка кружки: {e}")
                return True  # не блокируем
            time.sleep(1.0)

            # Перечитываем HP
            resp = client.get("/city")
            hp = get_own_hp_percent(resp.text if resp is not None else None)
            if hp is None:
                return True
            if hp >= threshold:
                print(f"[HEAL] Отхилен: HP {hp}%")
                return True
            print(f"[HEAL] После кружки HP {hp}%")

        print(f"[HEAL] После {MAX_DRINKS} кружек HP {hp}% — иду как есть")
        return True
    except Exception as e:
        # Любая ошибка отхила не должна ломать цикл данжей
        print(f"[HEAL] Ошибка ensure_healed: {e}")
        return True
