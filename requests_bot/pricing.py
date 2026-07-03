# ============================================
# VMMO Dynamic Pricing - множитель цены по спросу
# ============================================
# Проблема: боты всегда продают по цене конкурента (или -1с), даже когда
# товар улетает за час при суточном лоте — то есть системно недооценивают.
#
# Решение: контроллер множителя цены на данных sales_stats:
#   - товар продаётся быстро и почти весь (медиана tts < 4ч, sell-through
#     >= 85%) → поднимаем множитель на шаг (+5%)
#   - товар протухает (sell-through < 60%) → опускаем на шаг
#   - иначе держим (мёртвая зона гасит раскачку)
#
# Обновление не чаще раза в UPDATE_INTERVAL на предмет, шаг маленький,
# порог по выборке — три предохранителя от осцилляции.
# ============================================

import json
import fcntl
from datetime import datetime, timedelta
from pathlib import Path

from .sales_tracker import SALES_FILE

POLICY_FILE = Path(__file__).parent.parent / "profiles" / "price_policy.json"
POLICY_LOCK = Path(__file__).parent.parent / "profiles" / ".price_policy_lock"

# Границы и шаг контроллера
MULT_MIN = 1.00
MULT_MAX = 1.40
MULT_STEP = 0.05

# Правила (окно анализа и пороги)
WINDOW_HOURS = 48          # анализируем продажи за последние 48ч
MIN_SAMPLE = 3             # минимум событий (sold+expired) для решения
FAST_TTS_SEC = 4 * 3600    # «продаётся быстро» = медиана < 4ч
PROMOTE_SELL_THROUGH = 0.85
DEMOTE_SELL_THROUGH = 0.60

UPDATE_INTERVAL = 6 * 3600  # пересчёт политики не чаще раза в 6ч

# In-process кэш политики, чтобы не читать файл на каждый лот
_policy_cache = None
_policy_cache_time = 0.0
_POLICY_CACHE_TTL = 300  # 5 минут


def _load_policy() -> dict:
    if not POLICY_FILE.exists():
        return {"items": {}, "updated": 0}
    try:
        with open(POLICY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"items": {}, "updated": 0}


def _save_policy(policy: dict):
    try:
        POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(POLICY_FILE, "w", encoding="utf-8") as f:
            json.dump(policy, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[PRICING] Ошибка сохранения политики: {e}")


def _norm(name: str) -> str:
    """'Железо x10' -> 'Железо'"""
    import re
    return re.sub(r" x\d+$", "", str(name)).strip()


def _recompute_policy():
    """Пересчитывает множители по свежим sales_stats (вызывается редко, под локом)."""
    import statistics
    import time as _time

    try:
        with open(SALES_FILE, "r", encoding="utf-8") as f:
            stats = json.load(f)
    except Exception as e:
        print(f"[PRICING] Не смог прочитать sales_stats: {e}")
        return

    cutoff = (datetime.now() - timedelta(hours=WINDOW_HOURS)).timestamp()

    def ts(x):
        try:
            return datetime.fromisoformat(x["timestamp"]).timestamp()
        except Exception:
            return 0

    sold = {}   # item -> {"count": n, "tts": [...]}
    expired = {}
    for x in stats.get("sold", []):
        if ts(x) < cutoff or x.get("transfer"):
            continue
        n = _norm(x.get("item", ""))
        if n in ("(неизвестно)", ""):
            continue
        rec = sold.setdefault(n, {"count": 0, "tts": []})
        rec["count"] += 1
        if x.get("time_to_sell") is not None:
            rec["tts"].append(x["time_to_sell"])
    for x in stats.get("expired", []):
        if ts(x) < cutoff:
            continue
        n = _norm(x.get("item", ""))
        expired[n] = expired.get(n, 0) + 1

    policy = _load_policy()
    items = policy.setdefault("items", {})
    now = _time.time()

    for name in set(sold) | set(expired):
        s = sold.get(name, {"count": 0, "tts": []})
        e = expired.get(name, 0)
        total = s["count"] + e
        if total < MIN_SAMPLE:
            continue

        entry = items.setdefault(name, {"mult": 1.0, "updated": 0})
        # Не дёргаем предмет чаще UPDATE_INTERVAL
        if now - entry.get("updated", 0) < UPDATE_INTERVAL:
            continue

        sell_through = s["count"] / total
        med_tts = statistics.median(s["tts"]) if s["tts"] else None
        old = entry["mult"]

        if (sell_through >= PROMOTE_SELL_THROUGH
                and med_tts is not None and med_tts < FAST_TTS_SEC
                and old < MULT_MAX):
            entry["mult"] = round(min(MULT_MAX, old + MULT_STEP), 2)
            entry["reason"] = (f"promote: st={sell_through:.0%}, "
                               f"tts={int(med_tts)//60}м")
        elif sell_through < DEMOTE_SELL_THROUGH and old > MULT_MIN:
            entry["mult"] = round(max(MULT_MIN, old - MULT_STEP), 2)
            entry["reason"] = f"demote: st={sell_through:.0%}"
        else:
            entry["reason"] = f"hold: st={sell_through:.0%}"

        if entry["mult"] != old:
            print(f"[PRICING] {name}: множитель {old:.2f} -> {entry['mult']:.2f} ({entry['reason']})")
        entry["updated"] = now

    policy["updated"] = now
    _save_policy(policy)


def get_price_multiplier(item_name: str) -> float:
    """
    Возвращает множитель цены для предмета (>= 1.0).

    Лениво пересчитывает политику, если она устарела (> UPDATE_INTERVAL).
    Дёшево: политика кэшируется в процессе на 5 минут.
    """
    global _policy_cache, _policy_cache_time
    import time as _time

    now = _time.time()
    if _policy_cache is None or now - _policy_cache_time > _POLICY_CACHE_TTL:
        policy = _load_policy()
        # Пересчёт под файловым локом — только один бот из 23 его делает
        if now - policy.get("updated", 0) > UPDATE_INTERVAL:
            try:
                POLICY_LOCK.parent.mkdir(parents=True, exist_ok=True)
                with open(POLICY_LOCK, "w") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    try:
                        _recompute_policy()
                        policy = _load_policy()
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except BlockingIOError:
                pass  # другой бот уже пересчитывает
            except Exception as e:
                print(f"[PRICING] Ошибка пересчёта: {e}")
        _policy_cache = policy
        _policy_cache_time = now

    entry = _policy_cache.get("items", {}).get(_norm(item_name))
    if not entry:
        return 1.0
    try:
        mult = float(entry.get("mult", 1.0))
    except Exception:
        return 1.0
    return max(MULT_MIN, min(MULT_MAX, mult))


def apply_multiplier(total_silver: int, item_name: str) -> int:
    """Применяет множитель спроса к цене лота (в серебре)."""
    mult = get_price_multiplier(item_name)
    if mult <= 1.0:
        return total_silver
    return int(total_silver * mult)
