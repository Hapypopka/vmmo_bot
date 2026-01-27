# ============================================
# VMMO Bot Web Panel
# ============================================
# Веб-интерфейс для управления ботами
# Запуск: python -m requests_bot.web_panel
# ============================================

import os
import json
import subprocess
import signal
import hmac
import hashlib
from urllib.parse import parse_qsl
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, jsonify, request, redirect, url_for, session

# Resource History модуль
try:
    from requests_bot.resource_history import (
        get_history, get_sessions, get_offline_changes, get_all_chart_data
    )
    RESOURCE_HISTORY_AVAILABLE = True
except ImportError:
    RESOURCE_HISTORY_AVAILABLE = False

# Пути
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Создаём папки если нет
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = "vmmo_bot_secret_key_change_me"


@app.after_request
def add_no_cache_headers(response):
    """Отключаем кэширование для API и динамических страниц"""
    if request.path.startswith('/api/') or request.path in ['/', '/stats', '/config']:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


# Пароль для доступа (простая авторизация)
PANEL_PASSWORD = "1616"

# Telegram Bot Token (для проверки Mini App авторизации)
TELEGRAM_CONFIG_FILE = os.path.join(SCRIPT_DIR, "telegram_config.json")

def get_telegram_bot_token():
    """Получает токен бота из конфига"""
    if os.path.exists(TELEGRAM_CONFIG_FILE):
        with open(TELEGRAM_CONFIG_FILE, "r") as f:
            config = json.load(f)
            return config.get("bot_token", "")
    return ""

# Разрешённые Telegram user IDs (из telegram_config.json)
def get_allowed_telegram_users():
    """Получает список разрешённых пользователей из конфига"""
    if os.path.exists(TELEGRAM_CONFIG_FILE):
        with open(TELEGRAM_CONFIG_FILE, "r") as f:
            config = json.load(f)
            return config.get("allowed_users", [])
    return []

# Профили ботов
PROFILE_NAMES = {
    "char1": "nza",
    "char2": "Happypoq",
    "char3": "Arilyn",
    "char4": "Lovelion",
    "char5": "Хеппипопка",
    "char6": "Faizka",
}

# Названия ресурсов
RESOURCE_NAMES_RU = {
    "mineral": "Минерал",
    "skull": "Череп",
    "sapphire": "Сапфир",
    "ruby": "Рубин",
}

# Данжи Tab2: 1-29 уровень
DUNGEONS_TAB2 = {
    "dng:dSanctuary": "Святилище Накрила",
    "dng:dHellRuins": "Адские Развалины",
    "dng:RestMonastery": "Монастырь Покоя",
    "dng:HighDungeon": "Высокая Темница",
    "dng:Underlight": "Логово Кобольдов",
    "dng:CitadelHolding": "Крепость Холдинг",
    "dng:way2Baron": "Путь к Барону",
    "dng:Barony": "Владения Барона",
    "dng:ShadowGuard": "Пороги Шэдоу Гарда",
}

# Данжи Tab3: 30-39 уровень
DUNGEONS_TAB3 = {
    "dng:TitansGates3": "Врата Титанов",
    "dng:FateTemple": "Храм Судьбы",
    "dng:ShadowGuardCastle": "Шэдоу Гард",
    "dng:AbandonedAlchemistLaboratory": "Затерянная Лаборатория",
    "dng:Residentrenounced": "Обитель Отрекшихся",
    "dng:CrystalTomb": "Хрустальный Склеп",
    "dng:AncCathedral": "Собор Знаний",
    "dng:LostTemple": "Затерянный Храм",
    "dng:AncLibrary": "Хранилище Древних",
    "dng:SanctuaryElements": "Святилище Стихий",
    "dng:AncientCaverns": "Древние Пещеры",
    "dng:SkyCitadel": "Небесная Цитадель",
    "dng:DemonicPortal": "Демонический Портал",
}

# Все данжи
ALL_DUNGEONS = {**DUNGEONS_TAB2, **DUNGEONS_TAB3}

# Сложности данжей
DIFFICULTIES = {
    "normal": "Нормал",
    "hero": "Героик",
    "brutal": "Брутал",
}

# Активные процессы
active_bots = {}

# Файл защищённых предметов
PROTECTED_ITEMS_FILE = os.path.join(SCRIPT_DIR, "protected_items.json")

# Кэш цен крафта
CRAFT_PRICES_CACHE_FILE = os.path.join(SCRIPT_DIR, "craft_prices_cache.json")

# Дефолтные защищённые предметы
DEFAULT_PROTECTED_ITEMS = [
    # Крафт железа
    "Железо", "Железная Руда", "Железный Слиток",
    # Крафт меди/бронзы
    "Медь", "Медная Руда", "Бронза",
    # Крафт платины
    "Платина",
    # Квестовые/ценные
    "Треснутый Кристалл Тикуана",
    "Печать Сталкера I", "Печать Сталкера II", "Печать Сталкера III",
    "Золотой Оберег", "Изумительная пылинка",
    # Все ларцы оберегов (частичное совпадение)
    "Оберегов",
    # Сундуки/ларцы (открываем, не продаём)
    "Сундук", "Ларец", "Ящик", "Шкатулка",
    # Экипировка
    "Шлем Нордов",
    # Ресурсы ивентов
    "Ледяной Кристалл", "Уголь Эфирного Древа",
]


# ============================================
# Авторизация
# ============================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form["password"] == PANEL_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        else:
            error = "Неверный пароль"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


def verify_telegram_webapp_data(init_data: str) -> dict | None:
    """
    Проверяет подпись данных Telegram Web App.
    Возвращает данные пользователя если подпись верна, иначе None.
    """
    bot_token = get_telegram_bot_token()
    if not bot_token:
        return None

    try:
        # Парсим initData
        data_dict = dict(parse_qsl(init_data, keep_blank_values=True))

        # Получаем hash и удаляем его из данных
        received_hash = data_dict.pop("hash", None)
        if not received_hash:
            return None

        # Сортируем и формируем строку для проверки
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(data_dict.items())
        )

        # Создаём secret_key из токена бота
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256
        ).digest()

        # Вычисляем hash
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        # Сравниваем
        if computed_hash == received_hash:
            # Парсим user данные
            user_data = data_dict.get("user")
            if user_data:
                return json.loads(user_data)
        return None
    except Exception as e:
        print(f"[TELEGRAM AUTH] Error: {e}")
        return None


@app.route("/api/telegram_auth", methods=["POST"])
def telegram_auth():
    """
    Авторизация через Telegram Mini App.
    Проверяет initData и автоматически логинит пользователя.
    """
    try:
        data = request.get_json()
        init_data = data.get("initData", "")

        if not init_data:
            return jsonify({"success": False, "error": "No initData"})

        # Проверяем подпись
        user = verify_telegram_webapp_data(init_data)
        if not user:
            return jsonify({"success": False, "error": "Invalid signature"})

        user_id = user.get("id")
        allowed_users = get_allowed_telegram_users()

        # Проверяем есть ли пользователь в списке разрешённых
        if allowed_users and user_id not in allowed_users:
            return jsonify({
                "success": False,
                "error": f"User {user_id} not in allowed_users"
            })

        # Авторизуем
        session["logged_in"] = True
        session["telegram_user"] = user.get("first_name", "Telegram User")
        session["telegram_user_id"] = user_id

        return jsonify({"success": True, "user": user.get("first_name")})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================
# Вспомогательные функции
# ============================================

def get_config(profile):
    """Загружает конфиг профиля"""
    config_path = os.path.join(PROFILES_DIR, profile, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(profile, config):
    """Сохраняет конфиг профиля"""
    config_path = os.path.join(PROFILES_DIR, profile, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def get_resources(profile):
    """Загружает ресурсы профиля"""
    resources_file = os.path.join(PROFILES_DIR, profile, "resources.json")
    if os.path.exists(resources_file):
        with open(resources_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_bot_status(profile):
    """Проверяет статус бота"""
    lock_file = os.path.join(PROFILES_DIR, profile, ".lock")

    if profile in active_bots:
        proc = active_bots[profile]
        if proc.poll() is None:
            return "running"
        else:
            del active_bots[profile]

    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r") as f:
                pid = int(f.read().strip())
            # Проверяем существует ли процесс
            os.kill(pid, 0)
            return "running"
        except (ValueError, ProcessLookupError, PermissionError):
            # Процесс не существует, удаляем lock
            try:
                os.remove(lock_file)
            except Exception:
                pass

    return "stopped"


def start_bot(profile):
    """Запускает бота"""
    if get_bot_status(profile) == "running":
        return False, "Бот уже запущен"

    try:
        log_dir = os.path.join(PROFILES_DIR, profile, "logs")
        os.makedirs(log_dir, exist_ok=True)

        log_file = os.path.join(log_dir, f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        with open(log_file, "w") as log_f:
            proc = subprocess.Popen(
                ["python3", "-m", "requests_bot.bot", "--profile", profile],
                cwd=SCRIPT_DIR,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )

        active_bots[profile] = proc
        return True, f"Бот запущен (PID: {proc.pid})"
    except Exception as e:
        return False, f"Ошибка: {e}"


def stop_bot(profile):
    """Останавливает бота"""
    name = PROFILE_NAMES.get(profile, profile)
    stopped = False

    # Через subprocess
    if profile in active_bots:
        proc = active_bots[profile]
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            stopped = True
        del active_bots[profile]

    # Через lock файл
    lock_file = os.path.join(PROFILES_DIR, profile, ".lock")
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except Exception:
            pass
        try:
            os.remove(lock_file)
        except Exception:
            pass

    if stopped:
        return True, "Бот остановлен"
    return False, "Бот не был запущен"


def get_bot_activity(profile):
    """Возвращает текущую активность бота из status.json"""
    status_file = os.path.join(PROFILES_DIR, profile, "status.json")
    is_running = get_bot_status(profile) == "running"

    if not is_running:
        return None

    if not os.path.exists(status_file):
        return {"activity": "Работает", "time_ago": ""}

    try:
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        activity = data.get("activity", "Работает")
        timestamp = data.get("timestamp")

        if not timestamp:
            return {"activity": activity, "time_ago": ""}

        # Вычисляем время
        try:
            ts = datetime.fromisoformat(timestamp)
            delta = datetime.now() - ts
            minutes = int(delta.total_seconds() / 60)

            if minutes < 1:
                time_ago = "только что"
            elif minutes < 60:
                time_ago = f"{minutes}м"
            else:
                hours = minutes // 60
                time_ago = f"{hours}ч"

            return {"activity": activity, "time_ago": time_ago}
        except Exception:
            return {"activity": activity, "time_ago": ""}
    except Exception:
        return {"activity": "Работает", "time_ago": ""}


def get_all_stats():
    """Собирает статистику всех профилей"""
    stats = []

    for profile, name in PROFILE_NAMES.items():
        config = get_config(profile)
        craft_info = get_craft_info(profile)
        data = {
            "profile": profile,
            "name": name,
            "status": get_bot_status(profile),
            "activity": get_bot_activity(profile),
            "resources": {},
            "earned": {},
            "hours": 0,
            "config": config,
            "is_main": config.get("is_main", False),
            "craft": craft_info,
        }

        resources = get_resources(profile)
        session_data = resources.get("current_session", {})

        if session_data and session_data.get("start"):
            start_res = session_data["start"]
            current_res = session_data.get("current", start_res)

            data["resources"] = current_res

            # Считаем изменения
            for key in set(list(start_res.keys()) + list(current_res.keys())):
                diff = current_res.get(key, 0) - start_res.get(key, 0)
                if diff != 0:
                    data["earned"][key] = diff

            # Длительность
            try:
                start_time = datetime.fromisoformat(session_data.get("start_time", ""))
                data["hours"] = (datetime.now() - start_time).total_seconds() / 3600
            except Exception:
                pass

        stats.append(data)

    return stats


def get_grouped_stats():
    """Собирает статистику с группировкой: мейны отдельно, мулы сгруппированы"""
    all_stats = get_all_stats()

    mains = [s for s in all_stats if s.get("is_main", False)]
    mules = [s for s in all_stats if not s.get("is_main", False)]

    # Суммарная статистика мулов
    mules_summary = {
        "resources": {},
        "earned": {},
        "running_count": 0,
        "total_count": len(mules),
        "total_hours": 0,
    }

    resource_keys = ['золото', 'серебро', 'черепа', 'минералы', 'сапфиры', 'рубины']

    for mule in mules:
        if mule["status"] == "running":
            mules_summary["running_count"] += 1
        mules_summary["total_hours"] += mule.get("hours", 0)

        for key in resource_keys:
            mules_summary["resources"][key] = mules_summary["resources"].get(key, 0) + mule.get("resources", {}).get(key, 0)
            mules_summary["earned"][key] = mules_summary["earned"].get(key, 0) + mule.get("earned", {}).get(key, 0)

    # Сортируем мулов по заработку золота (для рангов)
    mules_sorted = sorted(
        [m for m in mules if m.get("earned", {}).get("золото", 0) > 0],
        key=lambda m: m.get("earned", {}).get("золото", 0),
        reverse=True
    )

    # Лучший мул - первый в отсортированном списке
    best_mule = mules_sorted[0] if mules_sorted else None

    return {
        "mains": mains,
        "mules": mules,
        "mules_summary": mules_summary,
        "best_mule": best_mule,
        "mules_sorted": mules_sorted,
    }


def get_logs(profile, lines=100):
    """Получает последние логи бота"""
    log_dir = os.path.join(PROFILES_DIR, profile, "logs")
    if not os.path.exists(log_dir):
        return "Нет логов"

    # Находим последний лог-файл
    log_files = sorted([f for f in os.listdir(log_dir) if f.endswith(".log")], reverse=True)
    if not log_files:
        return "Нет логов"

    log_path = os.path.join(log_dir, log_files[0])
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except Exception:
        return "Ошибка чтения логов"


def get_deaths(profile):
    """Получает статистику смертей"""
    deaths_file = os.path.join(PROFILES_DIR, profile, "deaths.json")
    if os.path.exists(deaths_file):
        with open(deaths_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_deaths(profile, deaths):
    """Сохраняет статистику смертей"""
    deaths_file = os.path.join(PROFILES_DIR, profile, "deaths.json")
    with open(deaths_file, "w", encoding="utf-8") as f:
        json.dump(deaths, f, ensure_ascii=False, indent=2)


def reset_deaths(profile):
    """Сбрасывает статистику смертей"""
    deaths_file = os.path.join(PROFILES_DIR, profile, "deaths.json")
    if os.path.exists(deaths_file):
        os.remove(deaths_file)
        return True
    return False


def load_protected_items():
    """Загружает список защищённых предметов"""
    if os.path.exists(PROTECTED_ITEMS_FILE):
        try:
            with open(PROTECTED_ITEMS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_PROTECTED_ITEMS.copy()


def save_protected_items(items):
    """Сохраняет список защищённых предметов"""
    try:
        with open(PROTECTED_ITEMS_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def reset_all_skips():
    """Сбрасывает все скипы данжей у всех персонажей"""
    results = []
    for profile in PROFILE_NAMES.keys():
        deaths_file = os.path.join(PROFILES_DIR, profile, "deaths.json")
        name = PROFILE_NAMES.get(profile, profile)

        if os.path.exists(deaths_file):
            try:
                with open(deaths_file, "r", encoding="utf-8") as f:
                    deaths = json.load(f)

                skipped_count = sum(1 for d in deaths.values() if d.get("skipped", False))

                if skipped_count > 0:
                    for dungeon_id, data in deaths.items():
                        if data.get("skipped", False):
                            data["skipped"] = False
                            data["current_difficulty"] = "brutal"

                    with open(deaths_file, "w", encoding="utf-8") as f:
                        json.dump(deaths, f, ensure_ascii=False, indent=2)

                    results.append({"profile": profile, "name": name, "reset": skipped_count})
                else:
                    results.append({"profile": profile, "name": name, "reset": 0})
            except Exception as e:
                results.append({"profile": profile, "name": name, "error": str(e)})
        else:
            results.append({"profile": profile, "name": name, "reset": 0})
    return results


def check_inventory():
    """Проверяет инвентарь крафта у всех персонажей"""
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "-m", "requests_bot.check_inventory", "--telegram"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0 and result.stdout.strip():
            return {"success": True, "output": result.stdout.strip()}
        else:
            return {"success": False, "error": result.stderr.strip() if result.stderr else "Неизвестная ошибка"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Таймаут (2 мин)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def ask_claude(prompt):
    """Отправляет запрос к Claude"""
    import base64
    try:
        encoded_prompt = base64.b64encode(prompt.encode('utf-8')).decode('ascii')
        result = subprocess.run(
            ["su", "-", "claude", "-c",
             f"cd /home/claude/vmmo_bot && echo '{encoded_prompt}' | base64 -d | /home/claude/ask_claude_stdin.sh"],
            capture_output=True,
            text=True,
            timeout=900  # 15 минут
        )
        output = result.stdout.strip()
        if result.returncode == 0 and output:
            return {"success": True, "response": output}
        elif result.stderr:
            return {"success": False, "error": result.stderr}
        else:
            return {"success": False, "error": "Нет ответа от Claude"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Таймаут (15 мин)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_craft_inventory_cache(profile):
    """
    Читает кэш инвентаря крафта для профиля.

    Returns:
        dict: {"rawOre": int, "iron": int, ...} или пустой dict
    """
    cache_file = os.path.join(PROFILES_DIR, profile, "craft_inventory.json")

    if not os.path.exists(cache_file):
        return {}

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Проверяем что кэш не слишком старый (2 часа)
        import time
        timestamp = data.get("timestamp", 0)
        if time.time() - timestamp > 7200:
            return {}

        return data.get("inventory", {})
    except Exception:
        return {}


def build_ingredient_chain(recipe_id, inventory=None, multiplier=1, depth=0, max_depth=5):
    """
    Рекурсивно строит цепочку ингредиентов для рецепта.

    Args:
        recipe_id: ID рецепта (например, "thorBar")
        inventory: dict с текущим инвентарём {"rawOre": 10, "iron": 5, ...}
        multiplier: Множитель количества (для вложенных рецептов)
        depth: Текущая глубина рекурсии
        max_depth: Максимальная глубина (защита от бесконечной рекурсии)

    Returns:
        list: [{"id": "thor", "name": "Тор", "amount": 5, "have": 3, "children": [...]}]
    """
    from requests_bot.craft import RECIPES, ITEM_NAMES

    if inventory is None:
        inventory = {}

    if depth >= max_depth:
        return []

    recipe = RECIPES.get(recipe_id)
    if not recipe:
        return []

    requires = recipe.get("requires", {})
    if not requires:
        return []

    result = []
    for ing_id, ing_amount in requires.items():
        total_amount = ing_amount * multiplier
        ing_name = ITEM_NAMES.get(ing_id, ing_id)
        have_amount = inventory.get(ing_id, 0)

        # Рекурсивно получаем дочерние ингредиенты
        children = build_ingredient_chain(ing_id, inventory, total_amount, depth + 1, max_depth)

        result.append({
            "id": ing_id,
            "name": ing_name,
            "amount": total_amount,
            "have": have_amount,
            "children": children
        })

    return result


def get_craft_info(profile):
    """
    Возвращает информацию о крафте для профиля.

    Returns:
        dict: {
            "active": str or None,  # Что сейчас крафтится (формат: "Предмет: 3/10")
            "active_id": str or None,  # ID активного рецепта
            "chain": list,  # Цепочка ингредиентов
            "queue": list,  # Очередь автокрафта
            "enabled": bool  # Включен ли автокрафт
        }
    """
    from requests_bot.config import CRAFTABLE_ITEMS

    config = get_config(profile)
    craft_enabled = config.get("iron_craft_enabled", False)
    craft_items = config.get("craft_items", [])

    # Получаем активный крафт из shared_craft_locks.json
    active_craft = None
    active_recipe_id = None
    current_count = 0
    batch_size = 5
    locks_file = os.path.join(os.path.dirname(PROFILES_DIR), "shared_craft_locks.json")

    if os.path.exists(locks_file):
        try:
            import time
            with open(locks_file, "r", encoding="utf-8") as f:
                locks_data = json.load(f)

            # Проверяем есть ли лок для этого профиля
            if profile in locks_data:
                lock_info = locks_data[profile]
                timestamp = lock_info.get("timestamp", 0)
                # Лок активен если не старше 2 часов
                if time.time() - timestamp <= 7200:
                    active_recipe_id = lock_info.get("recipe_id")
                    current_count = lock_info.get("current", 0)
                    batch_size = lock_info.get("batch", 5)
        except Exception as e:
            print(f"[WEB] Ошибка чтения shared_craft_locks: {e}")

    # Формируем очередь автокрафта и ищем batch_size для активного крафта (ручной режим)
    queue = []
    manual_batch_size = None
    for item in craft_items:
        item_id = item.get("item")
        item_batch = item.get("batch_size", 5)
        item_name = CRAFTABLE_ITEMS.get(item_id, item_id)
        queue.append(f"{item_name} x{item_batch}")

        # Если это активный рецепт из ручного списка - используем его batch_size
        if active_recipe_id and item_id == active_recipe_id:
            manual_batch_size = item_batch

    # Формируем строку активного крафта с прогрессом
    if active_recipe_id:
        item_name = CRAFTABLE_ITEMS.get(active_recipe_id, active_recipe_id)

        # Определяем batch_size (приоритет: из лока > из ручного списка > get_optimal_batch_size)
        if batch_size and batch_size > 0:
            final_batch = batch_size
        elif manual_batch_size:
            final_batch = manual_batch_size
        else:
            try:
                from requests_bot.craft_prices import get_optimal_batch_size
                final_batch = get_optimal_batch_size(active_recipe_id)
            except Exception:
                final_batch = 5

        # Формат: "Предмет: 3/10"
        active_craft = f"{item_name}: {current_count}/{final_batch}"

    # Строим цепочку ингредиентов для активного рецепта
    chain = []
    if active_recipe_id:
        # Получаем кэш инвентаря
        inventory = get_craft_inventory_cache(profile)
        chain = build_ingredient_chain(active_recipe_id, inventory)

    return {
        "active": active_craft,
        "active_id": active_recipe_id,
        "chain": chain,
        "queue": queue,
        "enabled": craft_enabled
    }


def reload_profiles():
    """Перезагружает список профилей из файловой системы"""
    global PROFILE_NAMES
    PROFILE_NAMES = {}

    if not os.path.exists(PROFILES_DIR):
        return

    # Сортируем по номеру char (char1, char2, ..., char10, char11)
    folders = []
    for folder in os.listdir(PROFILES_DIR):
        if folder.startswith("char") and os.path.isdir(os.path.join(PROFILES_DIR, folder)):
            try:
                num = int(folder.replace("char", ""))
                folders.append((num, folder))
            except ValueError:
                folders.append((9999, folder))

    folders.sort(key=lambda x: x[0])

    for _, folder in folders:
        config_path = os.path.join(PROFILES_DIR, folder, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                PROFILE_NAMES[folder] = config.get("username", folder)
            except Exception:
                PROFILE_NAMES[folder] = folder


def create_profile(username, password):
    """Создаёт новый профиль"""
    # Находим следующий номер
    existing = [int(p.replace("char", "")) for p in PROFILE_NAMES.keys() if p.startswith("char")]
    next_num = max(existing) + 1 if existing else 1
    profile = f"char{next_num}"

    profile_dir = os.path.join(PROFILES_DIR, profile)
    os.makedirs(profile_dir, exist_ok=True)

    # Создаём конфиг
    config = {
        "name": f"Character {next_num}",
        "description": f"Персонаж {next_num}",
        "username": username,
        "password": password,
        "backpack_threshold": 18,
        "dungeons_enabled": True,
        "arena_enabled": False,
        "event_dungeon_enabled": False,
        "ny_event_dungeon_enabled": False,
        "hell_games_enabled": False,
        "survival_mines_enabled": False,
        "pet_resurrection_enabled": False,
        "iron_craft_enabled": False,
        "craft_mode": "iron",
        "iron_craft_targets": {"ore": 5, "iron": 5, "bars": 5},
        "skill_cooldowns": {},
        "only_dungeons": [],
        "skip_dungeons": [],
        "dungeon_action_limits": {"default": 500},
        "resource_sell": {
            "mineral": {"enabled": False, "stack": 1000, "reserve": 200},
            "skull": {"enabled": False, "stack": 1000, "reserve": 200},
            "sapphire": {"enabled": False, "stack": 100, "reserve": 10},
            "ruby": {"enabled": False, "stack": 100, "reserve": 10},
        }
    }

    config_path = os.path.join(profile_dir, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

    # Создаём пустой cookies.json
    cookies_path = os.path.join(profile_dir, "cookies.json")
    with open(cookies_path, "w") as f:
        json.dump({}, f)

    reload_profiles()
    return profile


def delete_profile(profile):
    """Удаляет профиль"""
    import shutil

    profile_dir = os.path.join(PROFILES_DIR, profile)
    if not os.path.exists(profile_dir):
        return False

    # Останавливаем бота если запущен
    stop_bot(profile)

    # Удаляем папку
    shutil.rmtree(profile_dir)

    reload_profiles()
    return True


# Загружаем профили при старте
reload_profiles()


# ============================================
# Роуты - Страницы
# ============================================

@app.route("/")
@login_required
def index():
    """Главная страница - обзор всех ботов"""
    grouped = get_grouped_stats()
    all_stats = grouped["mains"] + grouped["mules"]

    # Расчёт total_stats для hero-панели
    total_stats = {
        "running": 0,
        "total": len(all_stats),
        "gold": 0,
        "gold_earned": 0,
        "minerals": 0,
        "minerals_earned": 0,
        "skulls": 0,
        "skulls_earned": 0,
        "gold_per_hour": 0.0,
        "total_hours": 0.0,
    }

    for bot in all_stats:
        if bot.get("status") == "running":
            total_stats["running"] += 1
        total_stats["gold"] += bot.get("resources", {}).get("золото", 0)
        total_stats["gold_earned"] += bot.get("earned", {}).get("золото", 0)
        total_stats["minerals"] += bot.get("resources", {}).get("минералы", 0)
        total_stats["minerals_earned"] += bot.get("earned", {}).get("минералы", 0)
        total_stats["skulls"] += bot.get("resources", {}).get("черепа", 0)
        total_stats["skulls_earned"] += bot.get("earned", {}).get("черепа", 0)
        total_stats["total_hours"] += bot.get("hours", 0)

    # Gold per hour (за всю сессию)
    if total_stats["total_hours"] > 0:
        total_stats["gold_per_hour"] = total_stats["gold_earned"] / total_stats["total_hours"]

    return render_template("index.html",
                           mains=grouped["mains"],
                           mules=grouped["mules"],
                           mules_summary=grouped["mules_summary"],
                           best_mule=grouped["best_mule"],
                           mules_sorted=grouped["mules_sorted"],
                           stats=all_stats,
                           total_stats=total_stats,
                           profile_names=PROFILE_NAMES)


@app.route("/stats")
@login_required
def stats_page():
    """Страница статистики с графиками"""
    stats = get_all_stats()
    return render_template("stats.html", stats=stats, profiles=PROFILE_NAMES)


@app.route("/config/<profile>")
@login_required
def config_page(profile):
    """Страница редактирования конфига"""
    if profile not in PROFILE_NAMES:
        return "Профиль не найден", 404

    config = get_config(profile)
    name = PROFILE_NAMES[profile]

    # Названия предметов для крафта
    craftable_items = {
        "iron": "Железо",
        "ironBar": "Железный Слиток",
        "copper": "Медь",
        "copperBar": "Медный Слиток",
        "bronze": "Бронза",
        "bronzeBar": "Бронзовый Слиток",
        "platinum": "Платина",
        "platinumBar": "Платиновый Слиток",
        "thor": "Тор",
        "thorBar": "Слиток Тора",
        "twilightSteel": "Сумеречная Сталь",
        "twilightAnthracite": "Сумеречный Антрацит",
    }

    return render_template("config.html",
                         profile=profile,
                         name=name,
                         config=config,
                         all_dungeons=ALL_DUNGEONS,
                         resource_names=RESOURCE_NAMES_RU,
                         craftable_items=craftable_items)


@app.route("/logs/<profile>")
@login_required
def logs_page(profile):
    """Страница логов"""
    if profile not in PROFILE_NAMES:
        return "Профиль не найден", 404

    name = PROFILE_NAMES[profile]
    logs = get_logs(profile, 200)
    return render_template("logs.html", profile=profile, name=name, logs=logs)


@app.route("/deaths/<profile>")
@login_required
def deaths_page(profile):
    """Страница смертей и сложности данжей"""
    if profile not in PROFILE_NAMES:
        return "Профиль не найден", 404

    name = PROFILE_NAMES[profile]
    config = get_config(profile)
    deaths = get_deaths(profile)

    return render_template("deaths.html",
                         profile=profile,
                         name=name,
                         config=config,
                         deaths=deaths,
                         all_dungeons=ALL_DUNGEONS,
                         difficulties=DIFFICULTIES)


@app.route("/profiles")
@login_required
def profiles_page():
    """Страница управления профилями"""
    profiles_data = []
    for profile, name in PROFILE_NAMES.items():
        config = get_config(profile)
        profiles_data.append({
            "profile": profile,
            "name": name,
            "username": config.get("username", ""),
            "status": get_bot_status(profile),
        })
    return render_template("profiles.html", profiles=profiles_data)


# ============================================
# API роуты
# ============================================

@app.route("/api/stats")
@login_required
def api_stats():
    """API: Статистика всех ботов"""
    return jsonify(get_all_stats())


@app.route("/api/bot/<profile>/start", methods=["POST"])
@login_required
def api_start_bot(profile):
    """API: Запуск бота"""
    success, msg = start_bot(profile)
    return jsonify({"success": success, "message": msg})


@app.route("/api/bot/<profile>/stop", methods=["POST"])
@login_required
def api_stop_bot(profile):
    """API: Остановка бота"""
    success, msg = stop_bot(profile)
    return jsonify({"success": success, "message": msg})


@app.route("/api/bot/<profile>/restart", methods=["POST"])
@login_required
def api_restart_bot(profile):
    """API: Перезапуск бота"""
    stop_bot(profile)
    import time
    time.sleep(1)
    success, msg = start_bot(profile)
    return jsonify({"success": success, "message": msg})


@app.route("/api/bot/start_all", methods=["POST"])
@login_required
def api_start_all():
    """API: Запуск всех ботов"""
    results = []
    for profile, name in PROFILE_NAMES.items():
        success, msg = start_bot(profile)
        results.append({"profile": profile, "name": name, "success": success, "message": msg})
    return jsonify(results)


@app.route("/api/bot/stop_all", methods=["POST"])
@login_required
def api_stop_all():
    """API: Остановка всех ботов"""
    results = []
    for profile, name in PROFILE_NAMES.items():
        success, msg = stop_bot(profile)
        results.append({"profile": profile, "name": name, "success": success, "message": msg})
    return jsonify(results)


# ============================================
# API: Telegram Bot Management
# ============================================

@app.route("/api/telegram_bot/status")
@login_required
def api_telegram_bot_status():
    """API: Статус Telegram бота"""
    try:
        # Ищем только python процессы (не bash обёртки)
        result = subprocess.run(
            ["pgrep", "-f", "python3.*telegram_bot"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            return jsonify({"running": True, "pids": pids, "count": len(pids)})
        return jsonify({"running": False, "pids": [], "count": 0})
    except Exception as e:
        return jsonify({"running": False, "error": str(e)})


@app.route("/api/telegram_bot/start", methods=["POST"])
@login_required
def api_telegram_bot_start():
    """API: Запуск Telegram бота"""
    try:
        # Проверяем, не запущен ли уже
        result = subprocess.run(
            ["pgrep", "-f", "requests_bot.telegram_bot"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return jsonify({"success": False, "error": "Telegram бот уже запущен"})

        # Запускаем
        subprocess.Popen(
            ["python3", "-m", "requests_bot.telegram_bot"],
            cwd=SCRIPT_DIR,
            stdout=open("/tmp/tg_bot.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        return jsonify({"success": True, "message": "Telegram бот запущен"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/telegram_bot/stop", methods=["POST"])
@login_required
def api_telegram_bot_stop():
    """API: Остановка Telegram бота"""
    try:
        result = subprocess.run(
            ["pkill", "-f", "requests_bot.telegram_bot"],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            return jsonify({"success": True, "message": "Telegram бот остановлен"})
        return jsonify({"success": False, "error": "Telegram бот не был запущен"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/telegram_bot/restart", methods=["POST"])
@login_required
def api_telegram_bot_restart():
    """API: Перезапуск Telegram бота"""
    try:
        # Останавливаем
        subprocess.run(
            ["pkill", "-f", "requests_bot.telegram_bot"],
            capture_output=True,
            timeout=10
        )
        import time
        time.sleep(1)

        # Запускаем
        subprocess.Popen(
            ["python3", "-m", "requests_bot.telegram_bot"],
            cwd=SCRIPT_DIR,
            stdout=open("/tmp/tg_bot.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        return jsonify({"success": True, "message": "Telegram бот перезапущен"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/config/<profile>", methods=["GET"])
@login_required
def api_get_config(profile):
    """API: Получить конфиг"""
    return jsonify(get_config(profile))


@app.route("/api/config/<profile>", methods=["POST"])
@login_required
def api_save_config(profile):
    """API: Сохранить конфиг"""
    try:
        config = request.json
        save_config(profile, config)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/config/<profile>/toggle/<setting>", methods=["POST"])
@login_required
def api_toggle_setting(profile, setting):
    """API: Переключить булевую настройку"""
    config = get_config(profile)
    current = config.get(setting, False)
    config[setting] = not current
    save_config(profile, config)
    return jsonify({"success": True, "value": config[setting]})


@app.route("/api/craft_items/<profile>/add", methods=["POST"])
@login_required
def api_craft_items_add(profile):
    """API: Добавить предмет в список автокрафта"""
    from requests_bot.config import CRAFTABLE_ITEMS

    data = request.json
    item = data.get("item")
    batch_size = data.get("batch_size", 5)

    if item not in CRAFTABLE_ITEMS:
        return jsonify({"success": False, "error": "Неизвестный предмет"})

    config = get_config(profile)
    if "craft_items" not in config:
        config["craft_items"] = []

    config["craft_items"].append({
        "item": item,
        "batch_size": int(batch_size)
    })
    save_config(profile, config)
    return jsonify({"success": True})


@app.route("/api/craft_items/<profile>/remove", methods=["POST"])
@login_required
def api_craft_items_remove(profile):
    """API: Удалить предмет из списка автокрафта"""
    data = request.json
    index = data.get("index", 0)

    config = get_config(profile)
    items = config.get("craft_items", [])

    if 0 <= index < len(items):
        items.pop(index)
        config["craft_items"] = items
        save_config(profile, config)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Неверный индекс"})


@app.route("/api/craft_items/<profile>/clear", methods=["POST"])
@login_required
def api_craft_items_clear(profile):
    """API: Очистить список автокрафта"""
    config = get_config(profile)
    config["craft_items"] = []
    save_config(profile, config)
    return jsonify({"success": True})


@app.route("/api/logs/<profile>")
@login_required
def api_logs(profile):
    """API: Получить логи"""
    lines = request.args.get("lines", 100, type=int)
    return jsonify({"logs": get_logs(profile, lines)})


@app.route("/api/deaths/<profile>")
@login_required
def api_get_deaths(profile):
    """API: Получить смерти"""
    return jsonify(get_deaths(profile))


@app.route("/api/deaths/<profile>/reset", methods=["POST"])
@login_required
def api_reset_deaths(profile):
    """API: Сбросить смерти"""
    reset_deaths(profile)
    return jsonify({"success": True})


@app.route("/api/deaths/<profile>/reset_skips", methods=["POST"])
@login_required
def api_reset_skips_profile(profile):
    """API: Сбросить только скипы данжей (сохранить историю смертей)"""
    deaths = get_deaths(profile)
    reset_count = 0
    for dungeon_id, data in deaths.items():
        if data.get("skipped", False):
            data["skipped"] = False
            data["current_difficulty"] = "brutal"
            reset_count += 1
    if reset_count > 0:
        save_deaths(profile, deaths)
    return jsonify({"success": True, "reset": reset_count})


@app.route("/api/deaths/<profile>/set_difficulty", methods=["POST"])
@login_required
def api_set_difficulty(profile):
    """API: Установить сложность данжа"""
    data = request.json
    dungeon_id = data.get("dungeon")
    difficulty = data.get("difficulty")

    config = get_config(profile)
    if "dungeon_difficulties" not in config:
        config["dungeon_difficulties"] = {}

    if difficulty:
        config["dungeon_difficulties"][dungeon_id] = difficulty
    elif dungeon_id in config["dungeon_difficulties"]:
        del config["dungeon_difficulties"][dungeon_id]

    save_config(profile, config)
    return jsonify({"success": True})


@app.route("/api/profiles", methods=["GET"])
@login_required
def api_get_profiles():
    """API: Список профилей"""
    profiles = []
    for profile, name in PROFILE_NAMES.items():
        config = get_config(profile)
        profiles.append({
            "profile": profile,
            "name": name,
            "username": config.get("username", ""),
            "status": get_bot_status(profile),
        })
    return jsonify(profiles)


@app.route("/api/profiles/create", methods=["POST"])
@login_required
def api_create_profile():
    """API: Создать профиль"""
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"success": False, "error": "Введите логин и пароль"})

    profile = create_profile(username, password)
    return jsonify({"success": True, "profile": profile})


@app.route("/api/profiles/<profile>/delete", methods=["POST"])
@login_required
def api_delete_profile(profile):
    """API: Удалить профиль"""
    if delete_profile(profile):
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Профиль не найден"})


# ============================================
# Защищённые предметы
# ============================================

@app.route("/protected")
@login_required
def protected_page():
    """Страница защищённых предметов"""
    items = load_protected_items()
    return render_template("protected.html", items=items, default_items=DEFAULT_PROTECTED_ITEMS)


@app.route("/api/protected", methods=["GET"])
@login_required
def api_get_protected():
    """API: Список защищённых предметов"""
    return jsonify(load_protected_items())


@app.route("/api/protected/add", methods=["POST"])
@login_required
def api_add_protected():
    """API: Добавить защищённый предмет"""
    data = request.json
    item = data.get("item", "").strip()
    if not item:
        return jsonify({"success": False, "error": "Введите название предмета"})

    items = load_protected_items()
    if item not in items:
        items.append(item)
        save_protected_items(items)
    return jsonify({"success": True, "items": items})


@app.route("/api/protected/remove", methods=["POST"])
@login_required
def api_remove_protected():
    """API: Удалить защищённый предмет"""
    data = request.json
    item = data.get("item", "").strip()

    items = load_protected_items()
    if item in items:
        items.remove(item)
        save_protected_items(items)
    return jsonify({"success": True, "items": items})


@app.route("/api/protected/reset", methods=["POST"])
@login_required
def api_reset_protected():
    """API: Сбросить к дефолту"""
    save_protected_items(DEFAULT_PROTECTED_ITEMS.copy())
    return jsonify({"success": True, "items": DEFAULT_PROTECTED_ITEMS})


# ============================================
# Инвентарь
# ============================================

@app.route("/inventory")
@login_required
def inventory_page():
    """Страница инвентаря"""
    return render_template("inventory.html")


@app.route("/api/inventory", methods=["GET"])
@login_required
def api_get_inventory():
    """API: Проверить инвентарь"""
    result = check_inventory()
    return jsonify(result)


# ============================================
# Сброс скипов
# ============================================

@app.route("/api/reset_skips", methods=["POST"])
@login_required
def api_reset_skips():
    """API: Сбросить все скипы данжей"""
    results = reset_all_skips()
    return jsonify({"success": True, "results": results})


# ============================================
# Продажа крафтов
# ============================================

@app.route("/api/sell_crafts", methods=["POST"])
@login_required
def api_sell_crafts():
    """API: Продать все крафты на аукционе у всех персонажей"""
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "-m", "requests_bot.sell_crafts"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=180  # 3 минуты на все профили
        )

        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                return jsonify({"success": True, "results": data})
            except json.JSONDecodeError:
                return jsonify({"success": True, "message": result.stdout.strip()})
        else:
            error = result.stderr.strip() if result.stderr else "Неизвестная ошибка"
            return jsonify({"success": False, "error": error})

    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Таймаут (3 мин)"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================
# AI Debug (Claude)
# ============================================

@app.route("/ai")
@login_required
def ai_page():
    """Страница AI Debug"""
    reload_profiles()
    return render_template("ai.html", profiles=PROFILE_NAMES)


@app.route("/api/ai/debug", methods=["POST"])
@login_required
def api_ai_debug():
    """API: AI анализ логов"""
    # Собираем логи всех ботов
    logs_info = []
    status_info = []

    for profile, name in PROFILE_NAMES.items():
        status = get_bot_status(profile)
        status_info.append(f"{name}: {status}")

        logs = get_logs(profile, lines=50)
        if logs:
            logs_info.append(f"=== {name} ===\n{logs[-500:]}")

    prompt = f"""Ты помощник для дебага VMMO ботов. Проанализируй состояние ботов и дай рекомендации.

Статус ботов:
{chr(10).join(status_info)}

Последние логи:
{chr(10).join(logs_info)}

Что не так с ботами? Если есть проблемы - предложи решение. Отвечай кратко на русском."""

    result = ask_claude(prompt)
    return jsonify(result)


@app.route("/api/ai/ask", methods=["POST"])
@login_required
def api_ai_ask():
    """API: Задать вопрос Claude"""
    data = request.json
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"success": False, "error": "Введите вопрос"})

    result = ask_claude(question)
    return jsonify(result)


# ============================================
# Debug Center API
# ============================================

@app.route("/api/debug/command", methods=["POST"])
@login_required
def api_debug_command():
    """API: Выполнение быстрых команд дебага"""
    data = request.json
    cmd = data.get("command", "")

    if cmd == "status":
        # Статус всех сервисов
        lines = ["=== Статус сервисов ===\n"]

        # Боты персонажей
        for profile, name in PROFILE_NAMES.items():
            status = get_bot_status(profile)
            emoji = "🟢" if status == "running" else "🔴"
            lines.append(f"{emoji} {name} ({profile}): {status}")

        lines.append("")

        # Status.json для каждого бота
        lines.append("=== Текущая активность ===")
        for profile, name in PROFILE_NAMES.items():
            status_file = os.path.join(PROFILES_DIR, profile, "status.json")
            if os.path.exists(status_file):
                try:
                    with open(status_file, "r", encoding="utf-8") as f:
                        status_data = json.load(f)
                    activity = status_data.get("activity", "неизвестно")
                    updated = status_data.get("updated", "")
                    lines.append(f"{name}: {activity} ({updated})")
                except Exception:
                    lines.append(f"{name}: ошибка чтения статуса")
            else:
                lines.append(f"{name}: нет данных")

        return jsonify({"success": True, "title": "Статус сервисов", "output": "\n".join(lines)})

    elif cmd == "errors":
        # Поиск ошибок во всех логах
        lines = ["=== Ошибки за последние логи ===\n"]
        found_errors = False

        for profile, name in PROFILE_NAMES.items():
            log_dir = os.path.join(PROFILES_DIR, profile, "logs")
            if not os.path.exists(log_dir):
                continue

            log_files = sorted([f for f in os.listdir(log_dir) if f.endswith(".log")], reverse=True)
            if not log_files:
                continue

            log_path = os.path.join(log_dir, log_files[0])
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                # Ищем ошибки
                errors = []
                for line in content.split("\n"):
                    if any(kw in line.upper() for kw in ["ERROR", "EXCEPTION", "TRACEBACK", "FAILED"]):
                        errors.append(line)

                if errors:
                    found_errors = True
                    lines.append(f"=== {name} ===")
                    lines.extend(errors[-10:])  # Последние 10 ошибок
                    lines.append("")
            except Exception:
                pass

        if not found_errors:
            lines.append("Ошибок не найдено!")

        return jsonify({"success": True, "title": "Поиск ошибок", "output": "\n".join(lines)})

    elif cmd == "processes":
        # Список Python процессов
        lines = ["=== Python процессы ===\n"]

        for profile, name in PROFILE_NAMES.items():
            lock_file = os.path.join(PROFILES_DIR, profile, ".lock")
            if os.path.exists(lock_file):
                try:
                    with open(lock_file, "r") as f:
                        content = f.read().strip()
                    lines.append(f"{name}: PID {content}")
                except Exception:
                    lines.append(f"{name}: lock существует, но не читается")
            else:
                lines.append(f"{name}: не запущен")

        return jsonify({"success": True, "title": "Процессы", "output": "\n".join(lines)})

    elif cmd == "locks":
        # Lock файлы
        lines = ["=== Lock файлы ===\n"]
        found_locks = False

        for profile, name in PROFILE_NAMES.items():
            lock_file = os.path.join(PROFILES_DIR, profile, ".lock")
            if os.path.exists(lock_file):
                found_locks = True
                try:
                    with open(lock_file, "r") as f:
                        content = f.read().strip()
                    mtime = os.path.getmtime(lock_file)
                    mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                    lines.append(f"{name}: {content} (создан: {mtime_str})")
                except Exception:
                    lines.append(f"{name}: lock существует, ошибка чтения")

        if not found_locks:
            lines.append("Lock файлов нет")

        return jsonify({"success": True, "title": "Lock файлы", "output": "\n".join(lines)})

    return jsonify({"success": False, "error": f"Неизвестная команда: {cmd}"})


@app.route("/api/debug/logs/<profile>")
@login_required
def api_debug_logs(profile):
    """API: Получить логи персонажа"""
    if profile not in PROFILE_NAMES:
        return jsonify({"success": False, "error": f"Профиль {profile} не найден"})

    lines = int(request.args.get("lines", 100))
    lines = min(lines, 1000)  # Максимум 1000 строк

    logs = get_logs(profile, lines)
    name = PROFILE_NAMES.get(profile, profile)

    return jsonify({"success": True, "name": name, "logs": logs})


@app.route("/api/debug/errors/<profile>")
@login_required
def api_debug_errors(profile):
    """API: Получить ошибки из логов персонажа"""
    if profile not in PROFILE_NAMES:
        return jsonify({"success": False, "error": f"Профиль {profile} не найден"})

    name = PROFILE_NAMES.get(profile, profile)
    log_dir = os.path.join(PROFILES_DIR, profile, "logs")

    if not os.path.exists(log_dir):
        return jsonify({"success": True, "name": name, "errors": []})

    log_files = sorted([f for f in os.listdir(log_dir) if f.endswith(".log")], reverse=True)
    if not log_files:
        return jsonify({"success": True, "name": name, "errors": []})

    errors = []
    # Проверяем последние 3 лог-файла
    for log_file in log_files[:3]:
        log_path = os.path.join(log_dir, log_file)
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if any(kw in line.upper() for kw in ["ERROR", "EXCEPTION", "TRACEBACK"]):
                        errors.append(f"[{log_file}] {line.strip()}")
        except Exception:
            pass

    return jsonify({"success": True, "name": name, "errors": errors[-50:]})  # Последние 50


@app.route("/api/debug/diagnose", methods=["POST"])
@login_required
def api_debug_diagnose():
    """API: Диагностика проблемы - сбор информации"""
    data = request.json
    profile = data.get("profile", "")
    problem = data.get("problem", "").strip()

    if not problem:
        return jsonify({"success": False, "error": "Опишите проблему"})

    # Собираем контекст
    context_parts = []
    context_parts.append(f"ПРОБЛЕМА: {problem}\n")

    # Статус ботов
    context_parts.append("=== Статус ботов ===")
    for p, name in PROFILE_NAMES.items():
        status = get_bot_status(p)
        emoji = "🟢" if status == "running" else "🔴"
        context_parts.append(f"{emoji} {name}: {status}")

        # Текущая активность
        status_file = os.path.join(PROFILES_DIR, p, "status.json")
        if os.path.exists(status_file):
            try:
                with open(status_file, "r", encoding="utf-8") as f:
                    status_data = json.load(f)
                activity = status_data.get("activity", "")
                if activity:
                    context_parts.append(f"   └ {activity}")
            except Exception:
                pass

    # Логи (конкретного профиля или всех)
    if profile and profile in PROFILE_NAMES:
        profiles_to_check = [profile]
    else:
        profiles_to_check = list(PROFILE_NAMES.keys())

    # Ошибки - ищем первыми
    errors_found = []
    context_parts.append("\n=== Найденные ошибки ===")
    for p in profiles_to_check:
        name = PROFILE_NAMES.get(p, p)
        log_dir = os.path.join(PROFILES_DIR, p, "logs")
        if os.path.exists(log_dir):
            log_files = sorted([f for f in os.listdir(log_dir) if f.endswith(".log")], reverse=True)
            if log_files:
                log_path = os.path.join(log_dir, log_files[0])
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line_upper = line.upper()
                            if any(kw in line_upper for kw in ["ERROR", "EXCEPTION", "TRACEBACK"]):
                                err_line = f"[{name}] {line.strip()}"
                                errors_found.append(err_line)
                                context_parts.append(err_line)
                except Exception:
                    pass

    if not errors_found:
        context_parts.append("Ошибок не найдено")

    # Последние логи
    context_parts.append("\n=== Последние логи ===")
    for p in profiles_to_check:
        name = PROFILE_NAMES.get(p, p)
        logs = get_logs(p, lines=50)
        if logs and logs != "Нет логов":
            context_parts.append(f"\n--- {name} ---")
            # Берём последние 1500 символов
            context_parts.append(logs[-1500:])

    # Рекомендации на основе ключевых слов проблемы
    context_parts.append("\n=== Возможные причины ===")
    problem_lower = problem.lower()

    if "застр" in problem_lower or "stuck" in problem_lower:
        context_parts.append("• Watchdog сработал - бот мог зависнуть в бою или на загрузке")
        context_parts.append("• Проверь status.json - какое последнее действие")
        context_parts.append("• Решение: перезапустить бота")

    if "лут" in problem_lower or "loot" in problem_lower:
        context_parts.append("• Metronome (heartbeat) мог не запуститься")
        context_parts.append("• Проверь логи на 'metronome' и 'loot'")
        context_parts.append("• Файл: combat.py - функция collect_loot()")

    if "крафт" in problem_lower or "craft" in problem_lower:
        context_parts.append("• Проверь craft_queue в config.json")
        context_parts.append("• Крафт может быть отключен (iron_craft_enabled: false)")
        context_parts.append("• Файл: craft.py - QueueCraftClient")

    if "смерт" in problem_lower or "умир" in problem_lower or "die" in problem_lower:
        context_parts.append("• Проверь deaths.json - счётчик смертей по данжам")
        context_parts.append("• Сложность понижается: brutal → hero → normal → skip")
        context_parts.append("• Решение: /reset_skips или кнопка 'Сброс скипов'")

    if "сессия" in problem_lower or "session" in problem_lower or "cookie" in problem_lower:
        context_parts.append("• Куки могли протухнуть")
        context_parts.append("• Нужен ре-логин через браузер")
        context_parts.append("• Обнови cookies.json для профиля")

    if "connection" in problem_lower or "подключ" in problem_lower or "timeout" in problem_lower:
        context_parts.append("• Проблемы с сетью или сервером игры")
        context_parts.append("• Проверь доступность vmmo.vten.ru")
        context_parts.append("• Может помочь перезапуск бота")

    context = "\n".join(context_parts)
    return jsonify({"success": True, "response": context})


# ============================================
# Крафт
# ============================================

@app.route("/craft")
@login_required
def craft_page():
    """Страница автокрафта"""
    from requests_bot.config import CRAFTABLE_ITEMS

    # Собираем конфиги всех профилей
    configs = {}
    for profile in PROFILE_NAMES.keys():
        config_path = os.path.join(PROFILES_DIR, profile, "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                configs[profile] = json.load(f)

    # Загружаем активные локи крафта
    # Структура файла: {profile: {"recipe_id": "ironBar", "timestamp": 123, "current": 3, "batch": 10}, ...}
    craft_locks = {}
    craft_progress = {}  # {profile: {"current": 3, "batch": 10}}
    locks_file = os.path.join(os.path.dirname(PROFILES_DIR), "shared_craft_locks.json")
    if os.path.exists(locks_file):
        try:
            import time
            from requests_bot.craft_prices import get_optimal_batch_size
            with open(locks_file, "r", encoding="utf-8") as f:
                locks_data = json.load(f)
            # Фильтруем только активные локи (не старше 2 часов)
            now = time.time()
            for profile, lock_info in locks_data.items():
                timestamp = lock_info.get("timestamp", 0)
                if now - timestamp <= 7200:  # LOCK_TTL = 2 часа
                    recipe_id = lock_info.get("recipe_id")
                    if recipe_id:
                        craft_locks[profile] = recipe_id
                        # Получаем прогресс из лока
                        current = lock_info.get("current", 0)
                        batch = lock_info.get("batch", 0)
                        # Если batch не сохранён - используем get_optimal_batch_size
                        if not batch or batch <= 0:
                            try:
                                batch = get_optimal_batch_size(recipe_id)
                            except Exception:
                                batch = 5
                        craft_progress[profile] = {"current": current, "batch": batch}
        except Exception as e:
            print(f"[WEB] Ошибка чтения локов крафта: {e}")

    return render_template("craft.html",
                         profiles=PROFILE_NAMES,
                         configs=configs,
                         craftable_items=CRAFTABLE_ITEMS,
                         craft_locks=craft_locks,
                         craft_progress=craft_progress)


# ============================================
# Цены крафта
# ============================================

@app.route("/craft_prices")
@login_required
def craft_prices_page():
    """Страница цен крафта"""
    return render_template("craft_prices.html", profiles=PROFILE_NAMES)


def load_craft_prices_cache():
    """Загружает кэш цен крафта"""
    if os.path.exists(CRAFT_PRICES_CACHE_FILE):
        try:
            with open(CRAFT_PRICES_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_craft_prices_cache(data):
    """Сохраняет кэш цен крафта"""
    cache_data = {
        "timestamp": datetime.now().isoformat(),
        "data": data
    }
    with open(CRAFT_PRICES_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)


@app.route("/api/craft_prices/cached", methods=["GET"])
@login_required
def api_get_craft_prices_cached():
    """API: Получить кэшированные цены крафта"""
    cache = load_craft_prices_cache()
    if cache:
        # Форматируем время
        try:
            ts = datetime.fromisoformat(cache["timestamp"])
            time_ago = datetime.now() - ts
            hours = time_ago.total_seconds() / 3600
            if hours < 1:
                time_str = f"{int(time_ago.total_seconds() / 60)} мин назад"
            elif hours < 24:
                time_str = f"{int(hours)} ч назад"
            else:
                time_str = ts.strftime("%d.%m %H:%M")
        except Exception:
            time_str = "неизвестно"

        return jsonify({
            "success": True,
            "cached": True,
            "cached_at": time_str,
            **cache["data"]
        })
    return jsonify({"success": False, "cached": False, "error": "Нет кэша"})


@app.route("/api/craft_prices", methods=["POST"])
@login_required
def api_get_craft_prices():
    """API: Получить цены крафта с аукциона (и сохранить в кэш)"""
    import sys
    data = request.json
    profile = data.get("profile", "char1")

    try:
        result = subprocess.run(
            [sys.executable, "-c", f"""
import json
import sys
sys.path.insert(0, '{SCRIPT_DIR}')

from requests_bot.config import load_settings, set_profile, get_credentials
from requests_bot.client import VMMOClient
from requests_bot.craft_prices import CraftPriceChecker

set_profile('{profile}')
load_settings()

client = VMMOClient()
username, password = get_credentials()

if not client.login(username, password):
    print(json.dumps({{"error": "Login failed"}}))
    sys.exit(1)

# use_cache=False для веб-панели - всегда свежие цены
checker = CraftPriceChecker(client, use_cache=False)
prices = checker.get_all_craft_prices()
profits = checker.get_all_profits()

print(json.dumps({{
    "prices": prices,
    "profits": profits
}}, ensure_ascii=False))
"""],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=180  # 3 минуты
        )

        if result.returncode == 0 and result.stdout.strip():
            # Парсим JSON из stdout
            lines = result.stdout.strip().split('\n')
            # Ищем последнюю строку с JSON (результат)
            for line in reversed(lines):
                if line.startswith('{'):
                    data = json.loads(line)
                    # Сохраняем в кэш
                    save_craft_prices_cache(data)
                    return jsonify({"success": True, "cached": False, **data})
            return jsonify({"success": False, "error": "No JSON output"})
        else:
            return jsonify({"success": False, "error": result.stderr or "Unknown error"})

    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Таймаут (3 мин)"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================
# API: Статистика (графики, сессии)
# ============================================

@app.route("/api/stats/chart/<profile>")
@login_required
def api_stats_chart(profile):
    """API: Данные для графика ресурсов"""
    if not RESOURCE_HISTORY_AVAILABLE:
        return jsonify({"success": False, "error": "Resource history not available"})

    period = request.args.get("period", "week")
    mode = request.args.get("mode", "sessions")  # sessions или days
    hours = {'day': 24, 'week': 168, 'month': 720}.get(period, 168)

    resource_keys = ['золото', 'серебро', 'черепа', 'минералы', 'сапфиры', 'рубины']

    def round_timestamp_to_minute(ts_str):
        """Округляет ISO timestamp до минуты и добавляет московский timezone"""
        try:
            dt = datetime.fromisoformat(ts_str.replace('+03:00', '').replace('Z', ''))
            return dt.replace(second=0, microsecond=0).isoformat() + '+03:00'
        except Exception:
            return ts_str

    def add_timezone(ts_str):
        """Добавляет московский timezone к timestamp"""
        if '+' not in ts_str and 'Z' not in ts_str:
            return ts_str + '+03:00'
        return ts_str

    def get_daily_data(profiles_to_check):
        """Агрегирует данные по дням (00:00 каждого дня)"""
        from collections import defaultdict
        from datetime import timedelta

        all_snapshots = []

        for p in profiles_to_check:
            history = get_history(hours, p)
            for snap in history:
                all_snapshots.append({
                    'profile': p,
                    'timestamp': snap['timestamp'],
                    'resources': snap['resources']
                })

        if not all_snapshots:
            return {"timestamps": [], "resources": {r: [] for r in resource_keys}}

        # Группируем снэпшоты по дате
        daily_data = defaultdict(lambda: defaultdict(dict))

        for snap in all_snapshots:
            try:
                ts = snap['timestamp'].replace('+03:00', '').replace('Z', '')
                dt = datetime.fromisoformat(ts)
                date_key = dt.date()
                profile = snap['profile']

                # Берём последний снэпшот за день для каждого профиля
                if profile not in daily_data[date_key] or dt > datetime.fromisoformat(daily_data[date_key][profile]['timestamp'].replace('+03:00', '')):
                    daily_data[date_key][profile] = snap
            except Exception:
                continue

        if not daily_data:
            return {"timestamps": [], "resources": {r: [] for r in resource_keys}}

        # Определяем диапазон дат
        min_date = min(daily_data.keys())
        max_date = max(daily_data.keys())

        # Генерируем все даты в диапазоне
        all_dates = []
        current_date = min_date
        while current_date <= max_date:
            all_dates.append(current_date)
            current_date += timedelta(days=1)

        # Формируем результат с интерполяцией
        timestamps = []
        resources = {r: [] for r in resource_keys}
        last_known = {p: {r: 0 for r in resource_keys} for p in profiles_to_check}

        for date in all_dates:
            # Timestamp на 00:00 этого дня
            dt = datetime(date.year, date.month, date.day, 0, 0, 0)
            timestamps.append(dt.isoformat() + '+03:00')

            # Обновляем last_known если есть данные за этот день
            if date in daily_data:
                for p, snap in daily_data[date].items():
                    for r in resource_keys:
                        last_known[p][r] = snap['resources'].get(r, last_known[p][r])

            # Суммируем все профили (или берём один)
            for r in resource_keys:
                total = sum(last_known[p][r] for p in profiles_to_check)
                resources[r].append(total)

        return {"timestamps": timestamps, "resources": resources}

    def get_daily_earnings(profiles_to_check):
        """Вычисляет заработок по дням (разница между последним и первым снэпшотом каждого дня)"""
        from collections import defaultdict
        from datetime import timedelta

        all_snapshots = []

        for p in profiles_to_check:
            history = get_history(hours, p)
            for snap in history:
                all_snapshots.append({
                    'profile': p,
                    'timestamp': snap['timestamp'],
                    'resources': snap['resources']
                })

        if not all_snapshots:
            return {"timestamps": [], "resources": {r: [] for r in resource_keys}}

        # Группируем снэпшоты по дате и профилю
        # Сохраняем первый и последний снэпшот каждого дня для каждого профиля
        daily_snapshots = defaultdict(lambda: defaultdict(lambda: {'first': None, 'last': None}))

        for snap in all_snapshots:
            try:
                ts = snap['timestamp'].replace('+03:00', '').replace('Z', '')
                dt = datetime.fromisoformat(ts)
                date_key = dt.date()
                profile_name = snap['profile']

                current = daily_snapshots[date_key][profile_name]

                # Первый снэпшот дня
                if current['first'] is None:
                    current['first'] = {'dt': dt, 'resources': snap['resources']}
                elif dt < current['first']['dt']:
                    current['first'] = {'dt': dt, 'resources': snap['resources']}

                # Последний снэпшот дня
                if current['last'] is None:
                    current['last'] = {'dt': dt, 'resources': snap['resources']}
                elif dt > current['last']['dt']:
                    current['last'] = {'dt': dt, 'resources': snap['resources']}
            except Exception:
                continue

        if not daily_snapshots:
            return {"timestamps": [], "resources": {r: [] for r in resource_keys}}

        # Формируем результат - заработок за каждый день
        timestamps = []
        resources = {r: [] for r in resource_keys}

        for date_key in sorted(daily_snapshots.keys()):
            dt = datetime(date_key.year, date_key.month, date_key.day, 12, 0, 0)
            timestamps.append(dt.isoformat() + '+03:00')

            # Суммируем заработок по всем профилям за этот день
            daily_earnings = {r: 0 for r in resource_keys}

            for profile_name in profiles_to_check:
                if profile_name in daily_snapshots[date_key]:
                    snap_data = daily_snapshots[date_key][profile_name]
                    if snap_data['first'] and snap_data['last']:
                        first_res = snap_data['first']['resources']
                        last_res = snap_data['last']['resources']
                        for r in resource_keys:
                            earned = last_res.get(r, 0) - first_res.get(r, 0)
                            daily_earnings[r] += earned

            for r in resource_keys:
                resources[r].append(daily_earnings[r])

        return {"timestamps": timestamps, "resources": resources}

    # Режим по дням
    if mode == "days":
        if profile == "all":
            profiles_to_check = list(PROFILE_NAMES.keys())
        else:
            if profile not in PROFILE_NAMES:
                return jsonify({"success": False, "error": "Profile not found"})
            profiles_to_check = [profile]

        data = get_daily_data(profiles_to_check)
        return jsonify({"success": True, "data": data})

    # Режим заработка по дням
    if mode == "earnings":
        if profile == "all":
            profiles_to_check = list(PROFILE_NAMES.keys())
        else:
            if profile not in PROFILE_NAMES:
                return jsonify({"success": False, "error": "Profile not found"})
            profiles_to_check = [profile]

        data = get_daily_earnings(profiles_to_check)
        return jsonify({"success": True, "data": data})

    # Если "all" - суммируем ресурсы всех профилей
    if profile == "all":
        # Собираем последние данные каждого профиля
        # Для "all" показываем суммарные ресурсы на каждый уникальный момент времени
        all_data = []

        for p in PROFILE_NAMES.keys():
            history = get_history(hours, p)
            for snap in history:
                all_data.append({
                    'profile': p,
                    'timestamp': snap['timestamp'],
                    'timestamp_rounded': round_timestamp_to_minute(snap['timestamp']),
                    'resources': snap['resources']
                })

        if not all_data:
            return jsonify({"success": True, "data": {"timestamps": [], "resources": {r: [] for r in resource_keys}}})

        # Группируем по округлённому времени
        from collections import defaultdict
        grouped = defaultdict(dict)

        for item in sorted(all_data, key=lambda x: x['timestamp']):
            ts_rounded = item['timestamp_rounded']
            grouped[ts_rounded][item['profile']] = item['resources']

        # Формируем результат - для каждого момента времени суммируем ресурсы всех профилей
        timestamps = []
        resources = {r: [] for r in resource_keys}
        last_known = {p: {r: 0 for r in resource_keys} for p in PROFILE_NAMES.keys()}

        for ts_rounded in sorted(grouped.keys()):
            # Обновляем last_known для профилей с данными в этот момент
            for p, res_data in grouped[ts_rounded].items():
                for r in resource_keys:
                    last_known[p][r] = res_data.get(r, 0)

            # Суммируем все профили
            timestamps.append(ts_rounded)
            for r in resource_keys:
                total = sum(last_known[p][r] for p in PROFILE_NAMES.keys())
                resources[r].append(total)

        return jsonify({
            "success": True,
            "data": {
                "timestamps": timestamps,
                "resources": resources
            }
        })
    else:
        # Один профиль
        if profile not in PROFILE_NAMES:
            return jsonify({"success": False, "error": "Profile not found"})

        history = get_history(hours, profile)

        timestamps = []
        resources = {r: [] for r in resource_keys}

        for snap in sorted(history, key=lambda x: x['timestamp']):
            timestamps.append(add_timezone(snap['timestamp']))
            for res in resource_keys:
                resources[res].append(snap['resources'].get(res, 0))

        return jsonify({
            "success": True,
            "data": {
                "timestamps": timestamps,
                "resources": resources
            }
        })


@app.route("/api/stats/sessions/<profile>")
@login_required
def api_stats_sessions(profile):
    """API: Сессии бота"""
    if not RESOURCE_HISTORY_AVAILABLE:
        return jsonify({"success": False, "error": "Resource history not available"})

    limit = int(request.args.get("limit", 20))

    if profile == "all":
        # Все сессии со всех профилей
        all_sessions = []
        for p in PROFILE_NAMES.keys():
            sessions = get_sessions(limit, p)
            for s in sessions:
                s['profile'] = p
                all_sessions.append(s)

        # Сортируем по времени старта
        all_sessions.sort(key=lambda x: x['start_time'], reverse=True)
        return jsonify({"success": True, "sessions": all_sessions[:limit]})
    else:
        if profile not in PROFILE_NAMES:
            return jsonify({"success": False, "error": "Profile not found"})

        sessions = get_sessions(limit, profile)
        for s in sessions:
            s['profile'] = profile
        return jsonify({"success": True, "sessions": sessions})


@app.route("/api/stats/offline/<profile>")
@login_required
def api_stats_offline(profile):
    """API: Изменения вне бота"""
    if not RESOURCE_HISTORY_AVAILABLE:
        return jsonify({"success": False, "error": "Resource history not available"})

    limit = int(request.args.get("limit", 20))

    if profile == "all":
        # Все offline изменения
        all_changes = []
        for p in PROFILE_NAMES.keys():
            changes = get_offline_changes(limit, p)
            for c in changes:
                c['profile'] = p
                all_changes.append(c)

        all_changes.sort(key=lambda x: x['detected_at'], reverse=True)
        return jsonify({"success": True, "changes": all_changes[:limit]})
    else:
        if profile not in PROFILE_NAMES:
            return jsonify({"success": False, "error": "Profile not found"})

        changes = get_offline_changes(limit, profile)
        for c in changes:
            c['profile'] = profile
        return jsonify({"success": True, "changes": changes})


@app.route("/api/stats/summary/<profile>")
@login_required
def api_stats_summary(profile):
    """API: Итоги за период (разница первого и последнего снэпшота)"""
    if not RESOURCE_HISTORY_AVAILABLE:
        return jsonify({"success": False, "error": "Resource history not available"})

    period = request.args.get("period", "week")
    hours = {'day': 24, 'week': 168, 'month': 720}.get(period, 168)

    resources = ['золото', 'серебро', 'черепа', 'минералы', 'сапфиры', 'рубины']
    summary = {r: 0 for r in resources}

    if profile == "all":
        # Суммируем изменения по всем профилям
        for p in PROFILE_NAMES.keys():
            history = get_history(hours, p)
            if len(history) >= 2:
                first = history[0]['resources']
                last = history[-1]['resources']
                for res in resources:
                    summary[res] += (last.get(res, 0) - first.get(res, 0))
    else:
        if profile not in PROFILE_NAMES:
            return jsonify({"success": False, "error": "Profile not found"})

        history = get_history(hours, profile)
        if len(history) >= 2:
            first = history[0]['resources']
            last = history[-1]['resources']
            for res in resources:
                summary[res] = last.get(res, 0) - first.get(res, 0)

    return jsonify({"success": True, "summary": summary})


# ============================================
# Gold Transfer API
# ============================================

@app.route("/gold_transfer")
@login_required
def gold_transfer_page():
    """Страница трансфера золота"""
    return render_template("gold_transfer.html", profiles=PROFILE_NAMES)


@app.route("/api/gold_balances", methods=["GET"])
@login_required
def api_gold_balances():
    """
    GET /api/gold_balances
    Получает балансы золота всех профилей
    """
    try:
        from .gold_transfer import get_balances
        balances = get_balances()
        return jsonify({"success": True, "balances": balances})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/gold_transfer", methods=["POST"])
@login_required
def api_gold_transfer():
    """
    POST /api/gold_transfer
    {
        "main_profile": "char1",
        "transfers": [
            {"profile": "char2", "amount": 40},
            {"profile": "char3", "amount": 20}
        ]
    }
    """
    try:
        data = request.json
        main_profile = data.get("main_profile")
        transfers = data.get("transfers", [])

        if not main_profile:
            return jsonify({"success": False, "error": "main_profile required"})

        if not transfers:
            return jsonify({"success": False, "error": "transfers required"})

        from .gold_transfer import transfer_gold
        result = transfer_gold(main_profile, transfers)

        return jsonify({"success": True, "result": result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/gold_transfer/stop", methods=["POST"])
@login_required
def api_gold_transfer_stop():
    """
    POST /api/gold_transfer/stop
    Останавливает текущий трансфер золота
    """
    try:
        from .gold_transfer import request_stop
        request_stop()
        return jsonify({"success": True, "message": "Stop requested"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================
# Запуск
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("VMMO Bot Web Panel")
    print("=" * 50)
    print(f"Открой в браузере: http://localhost:5000")
    print(f"Или: http://45.148.117.107:5000")
    print(f"Пароль: {PANEL_PASSWORD}")
    print("=" * 50)

    app.run(host="0.0.0.0", port=5000, debug=False)
