# ============================================
# VMMO Bot - Telegram Management Bot
# ============================================
# Управление ботами через Telegram
# Запуск: python -m requests_bot.telegram_bot
# ============================================

import os
import sys
import json
import subprocess
import signal
import asyncio
from datetime import datetime
from typing import Dict, Optional

# Telegram
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
except ImportError:
    print("Установи python-telegram-bot: pip install python-telegram-bot")
    sys.exit(1)

# Пути
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "telegram_config.json")

# Маппинг profile -> username (для отображения)
# Загружается динамически из profiles/
PROFILE_NAMES = {}

# Обратный маппинг
USERNAME_TO_PROFILE = {}


def reload_profiles():
    """Перезагружает список профилей из файловой системы"""
    global PROFILE_NAMES, USERNAME_TO_PROFILE
    PROFILE_NAMES = {}

    if not os.path.exists(PROFILES_DIR):
        return

    for folder in sorted(os.listdir(PROFILES_DIR)):
        if folder.startswith("char") and os.path.isdir(os.path.join(PROFILES_DIR, folder)):
            config_path = os.path.join(PROFILES_DIR, folder, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    PROFILE_NAMES[folder] = config.get("username", folder)
                except Exception:
                    PROFILE_NAMES[folder] = folder

    # Обновляем обратный маппинг
    USERNAME_TO_PROFILE = {v: k for k, v in PROFILE_NAMES.items()}


# Загружаем профили при импорте модуля
reload_profiles()

# Активные процессы ботов {profile: subprocess.Popen}
bot_processes: Dict[str, subprocess.Popen] = {}

# URL веб-панели для Mini App (HTTPS для Telegram Web App)
WEB_PANEL_URL = "https://faizbot.duckdns.org"

# Конфиг
def load_config():
    """Загружает конфиг телеграм бота"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(config):
    """Сохраняет конфиг"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

config = load_config()
BOT_TOKEN = config.get("bot_token", "")
ALLOWED_USERS = config.get("allowed_users", [])  # Список chat_id

def is_allowed(user_id: int) -> bool:
    """Проверяет доступ пользователя"""
    if not ALLOWED_USERS:
        return True  # Если список пустой - разрешаем всем (для первоначальной настройки)
    return user_id in ALLOWED_USERS


# ============================================
# Управление процессами ботов
# ============================================

def get_bot_status(profile: str) -> str:
    """Возвращает статус бота"""
    # Сначала проверяем через менеджер
    if profile in bot_processes:
        proc = bot_processes[profile]
        if proc.poll() is None:
            return "🟢 Работает"
        else:
            del bot_processes[profile]
            return "🔴 Остановлен (код: {})".format(proc.returncode)

    # Проверяем через pgrep - вдруг запущен не через менеджер
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"requests_bot.bot.*--profile.*{profile}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip().split()[0]
            return f"🟡 Работает (PID: {pid}, не через ТГ)"
    except Exception:
        pass

    return "⚪ Не запущен"

def start_bot(profile: str) -> tuple[bool, str]:
    """Запускает бота"""
    if profile in bot_processes:
        proc = bot_processes[profile]
        if proc.poll() is None:
            return False, "Бот уже запущен"

    try:
        # Создаём папку логов профиля если нет
        log_dir = os.path.join(PROFILES_DIR, profile, "logs")
        os.makedirs(log_dir, exist_ok=True)

        # Файл лога с датой
        log_file = os.path.join(log_dir, f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        # Открываем файл для логов
        log_handle = open(log_file, "w", encoding="utf-8")

        # Запускаем в фоне с выводом в файл
        proc = subprocess.Popen(
            [sys.executable, "-m", "requests_bot.bot", "--profile", profile],
            cwd=SCRIPT_DIR,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True  # Отвязываем от родительского процесса
        )
        bot_processes[profile] = proc
        return True, f"Бот {PROFILE_NAMES.get(profile, profile)} запущен (PID: {proc.pid})\nЛог: {log_file}"
    except Exception as e:
        return False, f"Ошибка запуска: {e}"

def stop_bot(profile: str) -> tuple[bool, str]:
    """Останавливает бота"""
    name = PROFILE_NAMES.get(profile, profile)
    stopped = False

    # Сначала пробуем через менеджер
    if profile in bot_processes:
        proc = bot_processes[profile]
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                stopped = True
            except subprocess.TimeoutExpired:
                proc.kill()
                stopped = True
            except Exception:
                pass
        del bot_processes[profile]

    # Принудительно убиваем все процессы этого профиля через pkill
    try:
        result = subprocess.run(
            ["pkill", "-f", f"requests_bot.bot.*--profile.*{profile}"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            stopped = True
    except Exception:
        pass

    # Удаляем lock-файл если остался
    lock_file = os.path.join(PROFILES_DIR, profile, ".lock")
    try:
        os.remove(lock_file)
    except Exception:
        pass

    if stopped:
        return True, f"Бот {name} остановлен"
    else:
        return False, f"Бот {name} не был запущен"

def restart_bot(profile: str) -> tuple[bool, str]:
    """Перезапускает бота"""
    stop_bot(profile)
    return start_bot(profile)


# ============================================
# Управление веб-панелью
# ============================================

def get_web_panel_status() -> str:
    """Возвращает статус веб-панели"""
    try:
        # Проверяем оба варианта запуска
        result1 = subprocess.run(
            ["pgrep", "-f", "requests_bot.web_panel"],
            capture_output=True,
            text=True,
            timeout=5
        )
        result2 = subprocess.run(
            ["pgrep", "-f", "python3 web_panel.py"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result1.returncode == 0 and result1.stdout.strip():
            pid = result1.stdout.strip().split()[0]
            return f"🟢 Работает (PID: {pid})"
        if result2.returncode == 0 and result2.stdout.strip():
            pid = result2.stdout.strip().split()[0]
            return f"🟢 Работает (PID: {pid})"
    except Exception:
        pass
    return "🔴 Остановлена"


def restart_web_panel() -> tuple[bool, str]:
    """Перезапускает веб-панель"""
    try:
        # Останавливаем оба варианта
        subprocess.run(
            ["pkill", "-f", "requests_bot.web_panel"],
            capture_output=True,
            timeout=10
        )
        subprocess.run(
            ["pkill", "-f", "python3 web_panel.py"],
            capture_output=True,
            timeout=10
        )
        import time
        time.sleep(1)

        # Запускаем как модуль из корневой директории vmmo_bot
        subprocess.Popen(
            ["python3", "-m", "requests_bot.web_panel"],
            cwd=SCRIPT_DIR,
            stdout=open("/tmp/web_panel.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        return True, "Веб-панель перезапущена"
    except Exception as e:
        return False, f"Ошибка: {e}"


def stop_web_panel() -> tuple[bool, str]:
    """Останавливает веб-панель"""
    try:
        # Пробуем оба паттерна - модульный и прямой запуск
        result1 = subprocess.run(
            ["pkill", "-f", "requests_bot.web_panel"],
            capture_output=True,
            timeout=10
        )
        result2 = subprocess.run(
            ["pkill", "-f", "python3 web_panel.py"],
            capture_output=True,
            timeout=10
        )
        if result1.returncode == 0 or result2.returncode == 0:
            return True, "Веб-панель остановлена"
        return False, "Веб-панель не была запущена"
    except Exception as e:
        return False, f"Ошибка: {e}"


def start_web_panel() -> tuple[bool, str]:
    """Запускает веб-панель"""
    try:
        # Проверяем, не запущена ли уже (оба варианта запуска)
        result1 = subprocess.run(
            ["pgrep", "-f", "requests_bot.web_panel"],
            capture_output=True,
            text=True,
            timeout=5
        )
        result2 = subprocess.run(
            ["pgrep", "-f", "python3 web_panel.py"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if (result1.returncode == 0 and result1.stdout.strip()) or \
           (result2.returncode == 0 and result2.stdout.strip()):
            return False, "Веб-панель уже запущена"

        # Запускаем как модуль из корневой директории vmmo_bot
        subprocess.Popen(
            ["python3", "-m", "requests_bot.web_panel"],
            cwd=SCRIPT_DIR,
            stdout=open("/tmp/web_panel.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        return True, "Веб-панель запущена"
    except Exception as e:
        return False, f"Ошибка: {e}"


def get_all_stats_compact() -> str:
    """Возвращает компактную таблицу статистики всех персонажей с рамками"""

    # Собираем данные по всем профилям
    all_data = []
    for profile, name in PROFILE_NAMES.items():
        resources_file = os.path.join(PROFILES_DIR, profile, "resources.json")

        if not os.path.exists(resources_file):
            continue

        try:
            with open(resources_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            session = data.get("current_session")
            if not session or not session.get("start"):
                continue

            start_res = session["start"]
            current_res = session.get("current", start_res)

            # Считаем изменения
            earned = {}
            for key in set(list(start_res.keys()) + list(current_res.keys())):
                diff = current_res.get(key, 0) - start_res.get(key, 0)
                if diff != 0:
                    earned[key] = diff

            # Длительность
            try:
                start_time = datetime.fromisoformat(session.get("start_time", ""))
                duration = datetime.now() - start_time
                hours = duration.total_seconds() / 3600
            except Exception:
                hours = 0

            all_data.append({
                "name": name,
                "hours": hours,
                "current": current_res,
                "earned": earned,
            })
        except Exception:
            continue

    if not all_data:
        return "📊 Нет данных о ресурсах"

    # Ширины колонок (без эмодзи, чтобы всё выравнивалось)
    W_NAME = 8
    W_GOLD = 6
    W_NUM = 5

    def fmt_num(val, width=W_NUM):
        """Форматирует число с выравниванием"""
        if val >= 10000:
            return f"{val//1000}k".rjust(width)
        return str(val).rjust(width)

    def fmt_change(val, width=W_NUM):
        """Форматирует изменение"""
        if val == 0:
            return "-".center(width)
        elif val > 0:
            s = f"+{val}"
        else:
            s = f"{val}"
        if len(s) > width:
            s = f"{val//1000:+d}k"
        return s.rjust(width)

    # Строим таблицу
    lines = ["📊 <b>Статистика всех</b>\n"]
    lines.append("<pre>")

    # Верхняя рамка
    lines.append(f"┌{'─'*W_NAME}┬{'─'*W_GOLD}┬{'─'*W_NUM}┬{'─'*W_NUM}┬{'─'*W_NUM}┬{'─'*W_NUM}┐")

    # Заголовок - текст вместо эмодзи
    lines.append(f"│{'Имя'.center(W_NAME)}│{'Зол'.center(W_GOLD)}│{'Чер'.center(W_NUM)}│{'Мин'.center(W_NUM)}│{'Сап'.center(W_NUM)}│{'Руб'.center(W_NUM)}│")

    # Разделитель после заголовка
    lines.append(f"├{'─'*W_NAME}┼{'─'*W_GOLD}┼{'─'*W_NUM}┼{'─'*W_NUM}┼{'─'*W_NUM}┼{'─'*W_NUM}┤")

    for i, d in enumerate(all_data):
        name = d["name"][:W_NAME].ljust(W_NAME)
        curr = d["current"]
        earned = d["earned"]

        # Текущие значения
        gold = curr.get("золото", 0)
        silver = curr.get("серебро", 0)
        skulls = curr.get("черепа", 0)
        minerals = curr.get("минералы", 0)
        sapphires = curr.get("сапфиры", 0)
        rubies = curr.get("рубины", 0)

        # Форматируем золото
        if gold > 0:
            gold_str = f"{gold}з".rjust(W_GOLD)
        else:
            gold_str = f"{silver}с".rjust(W_GOLD)

        # Строка с текущими значениями
        lines.append(f"│{name}│{gold_str}│{fmt_num(skulls)}│{fmt_num(minerals)}│{fmt_num(sapphires)}│{fmt_num(rubies)}│")

        # Изменения
        e_gold = earned.get("золото", 0)
        e_silver = earned.get("серебро", 0)
        e_skulls = earned.get("черепа", 0)
        e_minerals = earned.get("минералы", 0)
        e_sapphires = earned.get("сапфиры", 0)
        e_rubies = earned.get("рубины", 0)

        # Изменение золота/серебра
        if e_gold != 0:
            gold_chg = f"{e_gold:+d}з".rjust(W_GOLD)
        elif e_silver != 0:
            gold_chg = f"{e_silver:+d}с".rjust(W_GOLD)
        else:
            gold_chg = "-".center(W_GOLD)

        hours_str = f"{d['hours']:.1f}ч".rjust(W_NAME)

        # Строка с изменениями (серым цветом - часы и дельты)
        lines.append(f"│{hours_str}│{gold_chg}│{fmt_change(e_skulls)}│{fmt_change(e_minerals)}│{fmt_change(e_sapphires)}│{fmt_change(e_rubies)}│")

        # Разделитель между персонажами (кроме последнего)
        if i < len(all_data) - 1:
            lines.append(f"├{'─'*W_NAME}┼{'─'*W_GOLD}┼{'─'*W_NUM}┼{'─'*W_NUM}┼{'─'*W_NUM}┼{'─'*W_NUM}┤")

    # Нижняя рамка
    lines.append(f"└{'─'*W_NAME}┴{'─'*W_GOLD}┴{'─'*W_NUM}┴{'─'*W_NUM}┴{'─'*W_NUM}┴{'─'*W_NUM}┘")

    lines.append("</pre>")

    return "\n".join(lines)


def get_stats(profile: str) -> str:
    """Возвращает статистику бота - ресурсы по сессиям"""
    resources_file = os.path.join(PROFILES_DIR, profile, "resources.json")
    name = PROFILE_NAMES.get(profile, profile)

    if not os.path.exists(resources_file):
        return f"📊 {name}: нет данных о ресурсах"

    try:
        with open(resources_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        lines = [f"📊 Статистика {name}:"]

        # Текущая сессия
        session = data.get("current_session")
        if session and session.get("start"):
            start_res = session["start"]
            current_res = session.get("current", start_res)

            # Считаем заработанное
            earned = {}
            for key in set(list(start_res.keys()) + list(current_res.keys())):
                diff = current_res.get(key, 0) - start_res.get(key, 0)
                if diff != 0:
                    earned[key] = diff

            # Длительность
            try:
                start_time = datetime.fromisoformat(session.get("start_time", ""))
                duration = datetime.now() - start_time
                hours = duration.total_seconds() / 3600
                lines.append(f"\n🔸 Текущая сессия ({hours:.1f}ч):")
            except Exception:
                lines.append(f"\n🔸 Текущая сессия:")

            if earned:
                for res, val in earned.items():
                    sign = "+" if val > 0 else ""
                    lines.append(f"  {res}: {sign}{val}")
            else:
                lines.append("  (нет изменений)")

            # Текущие значения
            lines.append(f"\n💰 Сейчас:")
            for res, val in current_res.items():
                lines.append(f"  {res}: {val}")

        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка чтения статистики: {e}"


def get_last_activity(profile: str) -> str:
    """Возвращает текущую активность бота из status.json"""
    name = PROFILE_NAMES.get(profile, profile)
    status_file = os.path.join(PROFILES_DIR, profile, "status.json")

    # Проверяем статус бота
    status = get_bot_status(profile)
    is_running = "🟢" in status or "🟡" in status

    if not os.path.exists(status_file):
        if is_running:
            return f"{name}: 🔄 Запускается..."
        return f"{name}: ⚪ Не запущен"

    try:
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        activity = data.get("activity", "?")
        updated = data.get("updated", "")

        # Считаем время с последнего обновления
        if updated:
            try:
                last_time = datetime.fromisoformat(updated)
                time_ago = datetime.now() - last_time

                if time_ago.total_seconds() < 60:
                    time_str = f"{int(time_ago.total_seconds())}с"
                elif time_ago.total_seconds() < 3600:
                    time_str = f"{int(time_ago.total_seconds() // 60)}м"
                else:
                    time_str = f"{int(time_ago.total_seconds() // 3600)}ч"

                # Если статус устарел более 5 минут и бот не запущен
                if time_ago.total_seconds() > 300 and not is_running:
                    return f"{name}: ⚪ Остановлен ({time_str} назад: {activity})"

                return f"{name}: {activity} ({time_str})"
            except Exception:
                pass

        return f"{name}: {activity}"
    except Exception as e:
        if is_running:
            return f"{name}: 🔄 Работает"
        return f"{name}: ⚪ Не запущен"


# ============================================
# Telegram Handlers
# ============================================

def get_main_keyboard():
    """Возвращает главную клавиатуру"""
    keyboard = [
        [KeyboardButton("📡 Статус"), KeyboardButton("📊 Статистика"), KeyboardButton("📋 Логи")],
        [KeyboardButton("▶️ Запустить"), KeyboardButton("⏹️ Остановить"), KeyboardButton("🔄 Рестарт")],
        [KeyboardButton("⚒️ Крафт"), KeyboardButton("📦 Инвентарь"), KeyboardButton("💰 Продать крафты")],
        [KeyboardButton("🛡️ Защита"), KeyboardButton("🔄 Сброс скипов"), KeyboardButton("⚙️ Настройки")],
        [KeyboardButton("📥 Pull"), KeyboardButton("💬 Спросить AI"), KeyboardButton("➕ Новый")],
        [KeyboardButton("🌐 Веб-панель")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# Режим ожидания вопроса для AI
waiting_for_ai_question: Dict[int, bool] = {}


def ask_claude(prompt: str) -> str:
    """Отправляет запрос к Claude через юзера claude (с полными правами)"""
    try:
        import base64
        # Кодируем промпт в base64 чтобы избежать проблем со спецсимволами
        encoded_prompt = base64.b64encode(prompt.encode('utf-8')).decode('ascii')

        # Запускаем через su - claude, декодируем промпт на сервере
        result = subprocess.run(
            ["su", "-", "claude", "-c",
             f"cd /home/claude/vmmo_bot && echo '{encoded_prompt}' | base64 -d | /home/claude/ask_claude_stdin.sh"],
            capture_output=True,
            text=True,
            timeout=900  # 15 минут на сложные задачи
        )
        output = result.stdout.strip()
        if result.returncode == 0 and output:
            return output
        elif result.stderr:
            return f"Ошибка: {result.stderr}"
        else:
            return "Нет ответа от Claude"
    except subprocess.TimeoutExpired:
        return "Ошибка: таймаут запроса к Claude (15 мин)"
    except Exception as e:
        return f"Ошибка: {e}"


async def cmd_ai_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI Debug - анализ логов через Claude"""
    if not is_allowed(update.effective_user.id):
        return

    await update.message.reply_text("🤖 Собираю информацию для анализа...")

    # Собираем логи всех ботов
    logs_info = []
    for profile, name in PROFILE_NAMES.items():
        activity = get_last_activity(profile)
        logs_info.append(activity)

    # Собираем статус
    status_info = []
    for profile, name in PROFILE_NAMES.items():
        status = get_bot_status(profile)
        status_info.append(f"{name}: {status}")

    # Формируем промпт для Claude
    prompt = f"""Ты помощник для дебага VMMO ботов. Проанализируй состояние ботов и дай рекомендации.

Статус ботов:
{chr(10).join(status_info)}

Последние логи:
{chr(10).join(logs_info)}

Что не так с ботами? Если есть проблемы - предложи решение. Отвечай кратко на русском."""

    await update.message.reply_text("🔄 Отправляю запрос к Claude...")

    # Запрос к Claude в отдельном потоке чтобы не блокировать бота
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, ask_claude, prompt)

    # Обрезаем если слишком длинный
    if len(response) > 4000:
        response = response[:4000] + "..."

    await update.message.reply_text(f"🤖 Claude:\n\n{response}", reply_markup=get_main_keyboard())


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает последнюю активность всех ботов"""
    if not is_allowed(update.effective_user.id):
        return

    lines = ["📋 Последняя активность:\n"]
    for profile in PROFILE_NAMES.keys():
        lines.append(get_last_activity(profile))
        lines.append("")  # Пустая строка между ботами

    await update.message.reply_text("\n".join(lines), reply_markup=get_main_keyboard())


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    reload_profiles()  # Подхватываем новые профили из веб-панели
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text(
            f"⛔ Доступ запрещён\nТвой ID: {user_id}\n"
            "Добавь его в telegram_config.json -> allowed_users"
        )
        return

    await update.message.reply_text(
        "🤖 VMMO Bot Manager\n\nВыбери действие:",
        reply_markup=get_main_keyboard()
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статус всех ботов"""
    if not is_allowed(update.effective_user.id):
        return

    reload_profiles()  # Подхватываем новые профили
    lines = ["📡 Статус ботов:\n"]
    for profile, name in PROFILE_NAMES.items():
        status = get_bot_status(profile)
        lines.append(f"{name}: {status}")

    await update.message.reply_text("\n".join(lines))

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика - показывает кнопки выбора"""
    if not is_allowed(update.effective_user.id):
        return

    keyboard = []
    for profile, name in PROFILE_NAMES.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"stats_{profile}")])
    keyboard.append([InlineKeyboardButton("📊 Все", callback_data="stats_all")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери бота:", reply_markup=reply_markup)

async def cmd_start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск бота - показывает кнопки"""
    if not is_allowed(update.effective_user.id):
        return

    keyboard = []
    for profile, name in PROFILE_NAMES.items():
        keyboard.append([InlineKeyboardButton(f"▶️ {name}", callback_data=f"start_{profile}")])
    keyboard.append([InlineKeyboardButton("▶️ Всех", callback_data="start_all")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Запустить бота:", reply_markup=reply_markup)

async def cmd_stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Остановка бота - показывает кнопки"""
    if not is_allowed(update.effective_user.id):
        return

    keyboard = []
    for profile, name in PROFILE_NAMES.items():
        keyboard.append([InlineKeyboardButton(f"⏹️ {name}", callback_data=f"stop_{profile}")])
    keyboard.append([InlineKeyboardButton("⏹️ Всех", callback_data="stop_all")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Остановить бота:", reply_markup=reply_markup)

async def cmd_restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перезапуск бота - показывает кнопки"""
    if not is_allowed(update.effective_user.id):
        return

    keyboard = []
    for profile, name in PROFILE_NAMES.items():
        keyboard.append([InlineKeyboardButton(f"🔄 {name}", callback_data=f"restart_{profile}")])
    keyboard.append([InlineKeyboardButton("🔄 Всех", callback_data="restart_all")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Перезапустить бота:", reply_markup=reply_markup)

async def cmd_stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Остановить всех ботов"""
    if not is_allowed(update.effective_user.id):
        return

    results = []
    for profile, name in PROFILE_NAMES.items():
        success, msg = stop_bot(profile)
        results.append(f"{name}: {msg}")

    await update.message.reply_text("⏹️ Остановка всех:\n" + "\n".join(results))

async def cmd_restart_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перезапустить всех ботов"""
    if not is_allowed(update.effective_user.id):
        return

    results = []
    for profile, name in PROFILE_NAMES.items():
        success, msg = restart_bot(profile)
        results.append(f"{name}: {msg}")

    await update.message.reply_text("🔄 Перезапуск всех:\n" + "\n".join(results))


# ============================================
# Крафт
# ============================================

def get_craft_config(profile: str) -> dict:
    """Получает настройки крафта из конфига профиля"""
    config_path = os.path.join(PROFILES_DIR, profile, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return {
                "enabled": cfg.get("iron_craft_enabled", False),
                "mode": cfg.get("craft_mode", "iron"),
                "iron_targets": cfg.get("iron_craft_targets", {"ore": 5, "iron": 5, "bars": 5}),
                "bronze_targets": cfg.get("bronze_craft_targets", {})
            }
    return {"enabled": False, "mode": "iron", "iron_targets": {}, "bronze_targets": {}}

def set_craft_targets(profile: str, ore: int, iron: int, bars: int) -> bool:
    """Устанавливает цели крафта для профиля"""
    config_path = os.path.join(PROFILES_DIR, profile, "config.json")
    if not os.path.exists(config_path):
        return False

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg["iron_craft_targets"] = {"ore": ore, "iron": iron, "bars": bars}

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

    return True

def format_craft_status(profile: str) -> str:
    """Форматирует статус крафта для профиля"""
    name = PROFILE_NAMES.get(profile, profile)
    craft = get_craft_config(profile)

    if not craft["enabled"]:
        return f"⚪ {name}: крафт отключен"

    mode = craft["mode"]
    if mode == "iron":
        t = craft["iron_targets"]
        return f"⚒️ {name}: руда={t.get('ore', 0)}, железо={t.get('iron', 0)}, слитки={t.get('bars', 0)}"
    elif mode == "bronze":
        t = craft["bronze_targets"]
        return f"🥉 {name}: медн.руда={t.get('copper_ore', 0)}, жел.руда={t.get('raw_ore', 0)}, медь={t.get('copper', 0)}, бронза={t.get('bronze', 0)}"
    else:
        return f"⚒️ {name}: режим {mode}"

async def cmd_craft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать настройки крафта"""
    if not is_allowed(update.effective_user.id):
        return

    lines = ["⚒️ Настройки крафта:\n"]
    for profile in PROFILE_NAMES.keys():
        lines.append(format_craft_status(profile))

    lines.append("\n📝 Чтобы изменить:")
    lines.append("/craft char1 5 5 5 - руда/железо/слитки")

    keyboard = []
    for profile, name in PROFILE_NAMES.items():
        keyboard.append([InlineKeyboardButton(f"⚒️ {name}", callback_data=f"craft_{profile}")])

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить инвентарь крафта у всех персонажей"""
    if not is_allowed(update.effective_user.id):
        return

    await update.message.reply_text("📦 Проверяю инвентарь всех персонажей...\n(это займёт 30-60 сек)")

    try:
        # Запускаем скрипт проверки инвентаря
        result = subprocess.run(
            [sys.executable, "-m", "requests_bot.check_inventory", "--telegram"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=120  # 2 минуты на все профили
        )

        if result.returncode == 0 and result.stdout.strip():
            await update.message.reply_text(result.stdout.strip(), reply_markup=get_main_keyboard())
        else:
            error = result.stderr.strip() if result.stderr else "Неизвестная ошибка"
            await update.message.reply_text(f"❌ Ошибка: {error}", reply_markup=get_main_keyboard())

    except subprocess.TimeoutExpired:
        await update.message.reply_text("❌ Таймаут (2 мин)", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard())


async def cmd_sell_crafts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продать все крафты на аукционе у всех персонажей"""
    if not is_allowed(update.effective_user.id):
        return

    await update.message.reply_text("💰 Продаю крафты на аукционе у всех персонажей...\n(это займёт 1-2 мин)")

    try:
        # Запускаем скрипт продажи крафтов
        result = subprocess.run(
            [sys.executable, "-m", "requests_bot.sell_crafts", "--telegram"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=180  # 3 минуты на все профили
        )

        if result.returncode == 0 and result.stdout.strip():
            await update.message.reply_text(result.stdout.strip(), reply_markup=get_main_keyboard())
        else:
            error = result.stderr.strip() if result.stderr else "Неизвестная ошибка"
            await update.message.reply_text(f"❌ Ошибка: {error}", reply_markup=get_main_keyboard())

    except subprocess.TimeoutExpired:
        await update.message.reply_text("❌ Таймаут (3 мин)", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard())


async def cmd_reset_skips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбросить все скипы данжей у всех персонажей"""
    if not is_allowed(update.effective_user.id):
        return

    results = []
    for profile in PROFILE_NAMES.keys():
        deaths_file = os.path.join(PROFILES_DIR, profile, "deaths.json")
        name = PROFILE_NAMES.get(profile, profile)

        if os.path.exists(deaths_file):
            try:
                with open(deaths_file, "r", encoding="utf-8") as f:
                    deaths = json.load(f)

                # Считаем сколько скипов было
                skipped_count = sum(1 for d in deaths.values() if d.get("skipped", False))

                if skipped_count > 0:
                    # Сбрасываем все скипы
                    for dungeon_id, data in deaths.items():
                        if data.get("skipped", False):
                            data["skipped"] = False
                            data["current_difficulty"] = "brutal"

                    with open(deaths_file, "w", encoding="utf-8") as f:
                        json.dump(deaths, f, ensure_ascii=False, indent=2)

                    results.append(f"✅ {name}: сброшено {skipped_count} скипов")
                else:
                    results.append(f"⚪ {name}: нет скипов")
            except Exception as e:
                results.append(f"❌ {name}: ошибка - {e}")
        else:
            results.append(f"⚪ {name}: нет deaths.json")

    await update.message.reply_text(
        "🔄 Сброс скипов данжей:\n\n" + "\n".join(results) +
        "\n\n⚠️ Перезапусти ботов чтобы применить!",
        reply_markup=get_main_keyboard()
    )


async def cmd_craft_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить цели крафта: /craft char1 5 5 5"""
    if not is_allowed(update.effective_user.id):
        return

    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "❌ Формат: `/craft char1 5 5 5`\n"
            "(профиль, руда, железо, слитки)",
            parse_mode="Markdown"
        )
        return

    profile = args[0]
    if profile not in PROFILE_NAMES:
        await update.message.reply_text(f"❌ Профиль {profile} не найден")
        return

    try:
        ore = int(args[1])
        iron = int(args[2])
        bars = int(args[3])
    except ValueError:
        await update.message.reply_text("❌ Значения должны быть числами")
        return

    if set_craft_targets(profile, ore, iron, bars):
        name = PROFILE_NAMES[profile]
        await update.message.reply_text(
            f"✅ {name}: руда={ore}, железо={iron}, слитки={bars}\n"
            f"⚠️ Перезапусти бота чтобы применить!"
        )
    else:
        await update.message.reply_text("❌ Ошибка сохранения")


async def cmd_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить кулдауны скиллов: /cd char1 15 30 45 60..."""
    if not is_allowed(update.effective_user.id):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Формат: /cd char1 15 30 [45 60 ...]\n"
            "(профиль, кулдаун1, кулдаун2, ...)"
        )
        return

    profile = args[0]
    if profile not in PROFILE_NAMES:
        await update.message.reply_text(f"❌ Профиль {profile} не найден")
        return

    # Парсим все кулдауны (от 1 до N)
    cooldowns = {}
    try:
        for i, cd_str in enumerate(args[1:], start=1):
            cooldowns[str(i)] = float(cd_str) + 0.5
    except ValueError:
        await update.message.reply_text("❌ Кулдауны должны быть числами")
        return

    if not cooldowns:
        await update.message.reply_text("❌ Укажите хотя бы один кулдаун")
        return

    # Загружаем и обновляем конфиг
    cfg = get_user_settings(profile)
    if not cfg:
        await update.message.reply_text(f"❌ Профиль {profile} не найден")
        return

    cfg["skill_cooldowns"] = cooldowns

    if save_user_settings(profile, cfg):
        name = PROFILE_NAMES[profile]
        cd_list = ", ".join([f"{k}={v-0.5}с" for k, v in cooldowns.items()])
        await update.message.reply_text(
            f"✅ {name}: {cd_list}\n"
            f"⚠️ Перезапусти бота чтобы применить!"
        )
    else:
        await update.message.reply_text("❌ Ошибка сохранения")


# ============================================
# Настройки персонажей
# ============================================

def get_user_settings(profile: str) -> dict:
    """Получает все настройки персонажа"""
    config_path = os.path.join(PROFILES_DIR, profile, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_user_settings(profile: str, settings: dict) -> bool:
    """Сохраняет настройки персонажа"""
    config_path = os.path.join(PROFILES_DIR, profile, "config.json")
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False

def toggle_setting(profile: str, setting: str) -> tuple:
    """Переключает настройку (вкл/выкл)"""
    # Дефолты должны совпадать с шаблоном config.html
    SETTING_DEFAULTS = {
        "dungeons_enabled": True,
        "auto_select_craft": True,
        "sell_crafts_on_startup": True,
        "arena_enabled": False,
        "hell_games_enabled": False,
        "valentine_event_enabled": False,
        "party_dungeon_enabled": False,
        "survival_mines_enabled": False,
        "iron_craft_enabled": False,
        "pet_resurrection_enabled": False,
        "is_light_side": False,
    }
    settings = get_user_settings(profile)
    if not settings:
        return False, "Профиль не найден"

    current = settings.get(setting, SETTING_DEFAULTS.get(setting, False))
    settings[setting] = not current

    if save_user_settings(profile, settings):
        # При отключении автовыбора крафта — сбрасываем лок
        if setting == "auto_select_craft" and not settings[setting]:
            try:
                from requests_bot.craft_prices import release_craft_lock
                release_craft_lock(profile)
            except Exception:
                pass
        return True, settings[setting]
    return False, "Ошибка сохранения"

def format_user_settings(profile: str) -> str:
    """Форматирует настройки пользователя"""
    name = PROFILE_NAMES.get(profile, profile)
    cfg = get_user_settings(profile)

    if not cfg:
        return f"❌ {name}: профиль не найден"

    # Основные настройки
    dungeons = "✅" if cfg.get("dungeons_enabled", True) else "❌"
    hell = "✅" if cfg.get("hell_games_enabled", False) else "❌"
    arena = "✅" if cfg.get("arena_enabled", False) else "❌"
    valentine = "✅" if cfg.get("valentine_event_enabled", False) else "❌"
    party_dng = "✅" if cfg.get("party_dungeon_enabled", False) else "❌"
    craft = "✅" if cfg.get("iron_craft_enabled", False) else "❌"
    mines = "✅" if cfg.get("survival_mines_enabled", False) else "❌"

    # Кулдауны скиллов
    cooldowns = cfg.get("skill_cooldowns", {})
    if cooldowns:
        cd_list = ", ".join([f"{k}={v}с" for k, v in sorted(cooldowns.items(), key=lambda x: int(x[0]))])
    else:
        cd_list = "не заданы"

    return (
        f"⚙️ {name}\n\n"
        f"🏰 Данжи: {dungeons}\n"
        f"🔥 Адские игры: {hell}\n"
        f"⚔️ Арена: {arena}\n"
        f"💘 Валентин: {valentine}\n"
        f"👥 Пати-данж: {party_dng}\n"
        f"⚒️ Крафт: {craft}\n"
        f"⛏️ Шахта: {mines}\n\n"
        f"⏱️ Кулдауны: {cd_list}"
    )

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать настройки персонажей"""
    if not is_allowed(update.effective_user.id):
        return

    keyboard = []
    for profile, name in PROFILE_NAMES.items():
        keyboard.append([InlineKeyboardButton(f"⚙️ {name}", callback_data=f"settings_{profile}")])

    await update.message.reply_text(
        "⚙️ Выберите персонажа для настройки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def get_settings_keyboard(profile: str):
    """Возвращает клавиатуру настроек для профиля"""
    cfg = get_user_settings(profile)

    def icon(key, default=False):
        return "✅" if cfg.get(key, default) else "❌"

    # Иконка для светлый/тёмный
    side_icon = "☀️" if cfg.get("is_light_side", False) else "🌙"
    side_text = "Светлый" if cfg.get("is_light_side", False) else "Тёмный"

    # Дополнительные значения
    arena_max = cfg.get("arena_max_fights", 50)
    backpack_th = cfg.get("backpack_threshold", 18)

    keyboard = [
        [
            InlineKeyboardButton(f"{icon('dungeons_enabled', True)} Данжи", callback_data=f"toggle_{profile}_dungeons_enabled"),
            InlineKeyboardButton("📋 Выбор", callback_data=f"dungeons_list_{profile}")
        ],
        [
            InlineKeyboardButton(f"{icon('hell_games_enabled')} Адские игры", callback_data=f"toggle_{profile}_hell_games_enabled"),
            InlineKeyboardButton(f"{side_icon} {side_text}", callback_data=f"toggle_{profile}_is_light_side")
        ],
        [
            InlineKeyboardButton(f"{icon('arena_enabled')} Арена", callback_data=f"toggle_{profile}_arena_enabled"),
            InlineKeyboardButton(f"🎯 {arena_max} боёв", callback_data=f"arena_max_{profile}")
        ],
        [InlineKeyboardButton(f"{icon('valentine_event_enabled')} 💘 Валентин ивент", callback_data=f"toggle_{profile}_valentine_event_enabled")],
        [InlineKeyboardButton(f"{icon('party_dungeon_enabled')} 👥 Пати-данж", callback_data=f"toggle_{profile}_party_dungeon_enabled")],
        [
            InlineKeyboardButton(f"{icon('iron_craft_enabled')} Крафт", callback_data=f"toggle_{profile}_iron_craft_enabled"),
            InlineKeyboardButton("⚙️ Настр.", callback_data=f"craft_settings_{profile}")
        ],
        [
            InlineKeyboardButton(f"{icon('survival_mines_enabled')} Шахта", callback_data=f"toggle_{profile}_survival_mines_enabled"),
            InlineKeyboardButton("⚙️ Настр.", callback_data=f"mines_settings_{profile}")
        ],
        [InlineKeyboardButton(f"{icon('pet_resurrection_enabled')} Воскр. питомца", callback_data=f"toggle_{profile}_pet_resurrection_enabled")],
        [InlineKeyboardButton("💎 Продажа ресурсов", callback_data=f"sell_resources_{profile}")],
        [InlineKeyboardButton(f"🎒 Рюкзак: {backpack_th} слотов", callback_data=f"backpack_th_{profile}")],
        [InlineKeyboardButton("⏱️ Кулдауны скиллов", callback_data=f"cooldowns_{profile}")],
        [InlineKeyboardButton("🎯 HP пороги скиллов", callback_data=f"hp_thresholds_{profile}")],
        [InlineKeyboardButton("☠️ Смерти/Сложность", callback_data=f"deaths_list_{profile}")],
        [InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_{profile}"), InlineKeyboardButton("◀️ Назад", callback_data="settings_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


# Данжи по вкладкам
DUNGEONS_TAB2 = {
    # Tab 2: 50+ уровень (по умолчанию)
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

DUNGEONS_TAB3 = {
    # Tab 3: 30-39 уровень
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

# Маппинг данжен -> таб (для автоматического добавления табов)
DUNGEON_TO_TAB = {}
for dng_id in DUNGEONS_TAB2:
    DUNGEON_TO_TAB[dng_id] = "tab2"
for dng_id in DUNGEONS_TAB3:
    DUNGEON_TO_TAB[dng_id] = "tab3"

# Сложности данжей
DIFFICULTY_LEVELS = ["brutal", "hero", "normal"]
DIFFICULTY_NAMES = {
    "brutal": "🔥 Брутал",
    "hero": "⚔️ Героик",
    "normal": "🟢 Нормал",
    "skip": "⛔ Скип",
}


def is_dungeon_enabled(cfg: dict, dungeon_id: str) -> bool:
    """Проверяет включён ли данж для профиля"""
    only_dungeons = cfg.get("only_dungeons", [])

    # Если only_dungeons задан - смотрим есть ли там данж
    if only_dungeons:
        return dungeon_id in only_dungeons

    # Если only_dungeons пустой - по умолчанию все выключены
    return False


def get_dungeons_keyboard(profile: str):
    """Возвращает клавиатуру выбора данжей"""
    cfg = get_user_settings(profile)

    keyboard = []
    for dng_id, dng_name in ALL_DUNGEONS.items():
        enabled = is_dungeon_enabled(cfg, dng_id)
        icon = "✅" if enabled else "❌"
        keyboard.append([InlineKeyboardButton(f"{icon} {dng_name}", callback_data=f"dng_{profile}_{dng_id}")])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"settings_{profile}")])
    return InlineKeyboardMarkup(keyboard)


def toggle_dungeon(profile: str, dungeon_id: str) -> bool:
    """Переключает данж - добавляет/убирает из only_dungeons и автоматически управляет dungeon_tabs"""
    cfg = get_user_settings(profile)
    if not cfg:
        return False

    only_dungeons = cfg.get("only_dungeons", [])
    dungeon_tabs = cfg.get("dungeon_tabs", ["tab2"])

    # Переключаем
    if dungeon_id in only_dungeons:
        only_dungeons.remove(dungeon_id)
    else:
        only_dungeons.append(dungeon_id)
        # Автоматически добавляем нужный таб если его нет
        tab = DUNGEON_TO_TAB.get(dungeon_id)
        if tab and tab not in dungeon_tabs:
            dungeon_tabs.append(tab)

    # Проверяем, нужны ли табы - убираем неиспользуемые
    tabs_needed = set()
    for dng in only_dungeons:
        tab = DUNGEON_TO_TAB.get(dng)
        if tab:
            tabs_needed.add(tab)

    # Оставляем только нужные табы (но всегда оставляем tab2 по умолчанию)
    if tabs_needed:
        dungeon_tabs = list(tabs_needed)
    else:
        dungeon_tabs = ["tab2"]

    cfg["only_dungeons"] = only_dungeons
    cfg["dungeon_tabs"] = dungeon_tabs
    cfg["skip_dungeons"] = []

    return save_user_settings(profile, cfg)


# ============================================
# Deaths.json Management
# ============================================

def get_deaths_file(profile: str) -> str:
    """Путь к deaths.json профиля"""
    return os.path.join(PROFILES_DIR, profile, "deaths.json")


def load_deaths(profile: str) -> dict:
    """Загружает deaths.json профиля"""
    path = get_deaths_file(profile)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_deaths(profile: str, deaths: dict) -> bool:
    """Сохраняет deaths.json профиля"""
    path = get_deaths_file(profile)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(deaths, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def get_dungeon_difficulty(profile: str, dungeon_id: str) -> str:
    """Получает текущую сложность данжа из deaths.json"""
    deaths = load_deaths(profile)
    if dungeon_id in deaths:
        return deaths[dungeon_id].get("current_difficulty", "brutal")

    # Проверяем dungeon_difficulties из конфига
    cfg = get_user_settings(profile)
    difficulties = cfg.get("dungeon_difficulties", {})
    if dungeon_id in difficulties:
        return difficulties[dungeon_id]

    return "brutal"  # По умолчанию


def set_dungeon_difficulty(profile: str, dungeon_id: str, difficulty: str) -> bool:
    """Устанавливает сложность данжа"""
    deaths = load_deaths(profile)

    if dungeon_id not in deaths:
        deaths[dungeon_id] = {
            "name": ALL_DUNGEONS.get(dungeon_id, dungeon_id),
            "deaths": [],
            "current_difficulty": difficulty,
        }
    else:
        deaths[dungeon_id]["current_difficulty"] = difficulty

    # Убираем skipped если ставим не skip
    if difficulty != "skip" and deaths[dungeon_id].get("skipped"):
        del deaths[dungeon_id]["skipped"]

    return save_deaths(profile, deaths)


def reset_deaths(profile: str, dungeon_id: str = None) -> bool:
    """Сбрасывает deaths.json (весь или для одного данжа)"""
    if dungeon_id:
        deaths = load_deaths(profile)
        if dungeon_id in deaths:
            del deaths[dungeon_id]
            return save_deaths(profile, deaths)
        return True
    else:
        # Сбросить весь файл
        return save_deaths(profile, {})


def get_deaths_keyboard(profile: str):
    """Клавиатура для просмотра deaths.json"""
    deaths = load_deaths(profile)

    keyboard = []

    if not deaths:
        keyboard.append([InlineKeyboardButton("📭 История смертей пуста", callback_data="noop")])
    else:
        for dng_id, data in deaths.items():
            name = data.get("name", dng_id.replace("dng:", ""))
            diff = data.get("current_difficulty", "brutal")
            death_count = len(data.get("deaths", []))
            icon = DIFFICULTY_NAMES.get(diff, diff)

            # Обрезаем длинные названия
            if len(name) > 18:
                name = name[:15] + "..."

            keyboard.append([
                InlineKeyboardButton(f"{name}: {icon} ({death_count}☠️)", callback_data=f"death_info_{profile}_{dng_id}")
            ])

    keyboard.append([InlineKeyboardButton("🗑️ Сбросить всё", callback_data=f"reset_all_deaths_{profile}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"settings_{profile}")])

    return InlineKeyboardMarkup(keyboard)


def get_difficulty_keyboard(profile: str, dungeon_id: str):
    """Клавиатура выбора сложности для данжа"""
    current_diff = get_dungeon_difficulty(profile, dungeon_id)

    keyboard = []
    for diff in DIFFICULTY_LEVELS:
        icon = "✅ " if diff == current_diff else ""
        name = DIFFICULTY_NAMES.get(diff, diff)
        keyboard.append([InlineKeyboardButton(f"{icon}{name}", callback_data=f"set_diff_{profile}_{dungeon_id}_{diff}")])

    keyboard.append([InlineKeyboardButton("🗑️ Сбросить запись", callback_data=f"reset_death_{profile}_{dungeon_id}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"deaths_list_{profile}")])

    return InlineKeyboardMarkup(keyboard)


# ============================================
# Craft Settings Management
# ============================================

# Словарь крафтовых предметов
CRAFTABLE_ITEMS = {
    "iron": "Железо",
    "ironBar": "Жел.Слиток",
    "copper": "Медь",
    "copperBar": "Мед.Слиток",
    "bronze": "Бронза",
    "platinum": "Платина",
}


def get_craft_settings_keyboard(profile: str):
    """Клавиатура настроек автокрафта"""
    cfg = get_user_settings(profile)
    items = cfg.get("craft_items", [])

    keyboard = []

    # Показать текущий список
    if items:
        keyboard.append([InlineKeyboardButton("📋 Автокрафт:", callback_data="noop")])
        for i, item_cfg in enumerate(items):
            item_name = CRAFTABLE_ITEMS.get(item_cfg["item"], item_cfg["item"])
            batch_size = item_cfg["batch_size"]
            text = f"  {i+1}. {item_name} (партия: {batch_size} шт)"
            keyboard.append([
                InlineKeyboardButton(text, callback_data="noop"),
                InlineKeyboardButton("❌", callback_data=f"cq_del_{profile}_{i}")
            ])
    else:
        keyboard.append([InlineKeyboardButton("📋 Список пуст", callback_data="noop")])

    # Кнопки добавления предметов
    keyboard.append([InlineKeyboardButton("➕ Добавить:", callback_data="noop")])
    row1 = [
        InlineKeyboardButton("🔩 Железо", callback_data=f"cq_add_{profile}_iron"),
        InlineKeyboardButton("📊 Слиток", callback_data=f"cq_add_{profile}_ironBar"),
    ]
    row2 = [
        InlineKeyboardButton("🔶 Медь", callback_data=f"cq_add_{profile}_copper"),
        InlineKeyboardButton("🟠 Мед.Слиток", callback_data=f"cq_add_{profile}_copperBar"),
    ]
    row3 = [
        InlineKeyboardButton("🥉 Бронза", callback_data=f"cq_add_{profile}_bronze"),
        InlineKeyboardButton("💎 Платина", callback_data=f"cq_add_{profile}_platinum"),
    ]
    keyboard.append(row1)
    keyboard.append(row2)
    keyboard.append(row3)

    # Очистить список
    if items:
        keyboard.append([InlineKeyboardButton("🗑️ Очистить список", callback_data=f"cq_clear_{profile}")])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"settings_{profile}")])

    return InlineKeyboardMarkup(keyboard)


def get_craft_count_keyboard(profile: str, item_id: str):
    """Клавиатура для выбора количества крафта"""
    item_name = CRAFTABLE_ITEMS.get(item_id, item_id)

    keyboard = []
    keyboard.append([InlineKeyboardButton(f"➕ {item_name} - сколько?", callback_data="noop")])

    # Быстрый выбор количества
    row1 = [
        InlineKeyboardButton("5", callback_data=f"cq_cnt_{profile}_{item_id}_5"),
        InlineKeyboardButton("10", callback_data=f"cq_cnt_{profile}_{item_id}_10"),
        InlineKeyboardButton("15", callback_data=f"cq_cnt_{profile}_{item_id}_15"),
    ]
    row2 = [
        InlineKeyboardButton("20", callback_data=f"cq_cnt_{profile}_{item_id}_20"),
        InlineKeyboardButton("30", callback_data=f"cq_cnt_{profile}_{item_id}_30"),
        InlineKeyboardButton("50", callback_data=f"cq_cnt_{profile}_{item_id}_50"),
    ]
    keyboard.append(row1)
    keyboard.append(row2)

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"craft_settings_{profile}")])

    return InlineKeyboardMarkup(keyboard)


def get_craft_targets_keyboard(profile: str):
    """Клавиатура для настройки целей крафта"""
    cfg = get_user_settings(profile)
    mode = cfg.get("craft_mode", "iron")

    keyboard = []

    if mode == "iron":
        targets = cfg.get("iron_craft_targets", {"ore": 5, "iron": 5, "bars": 5})
        keyboard.append([InlineKeyboardButton(f"📦 Руда: {targets.get('ore', 5)}", callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton("-5", callback_data=f"craft_adj_{profile}_ore_-5"),
            InlineKeyboardButton("-1", callback_data=f"craft_adj_{profile}_ore_-1"),
            InlineKeyboardButton("+1", callback_data=f"craft_adj_{profile}_ore_+1"),
            InlineKeyboardButton("+5", callback_data=f"craft_adj_{profile}_ore_+5"),
        ])
        keyboard.append([InlineKeyboardButton(f"🔩 Железо: {targets.get('iron', 5)}", callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton("-5", callback_data=f"craft_adj_{profile}_iron_-5"),
            InlineKeyboardButton("-1", callback_data=f"craft_adj_{profile}_iron_-1"),
            InlineKeyboardButton("+1", callback_data=f"craft_adj_{profile}_iron_+1"),
            InlineKeyboardButton("+5", callback_data=f"craft_adj_{profile}_iron_+5"),
        ])
        keyboard.append([InlineKeyboardButton(f"📊 Слитки: {targets.get('bars', 5)}", callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton("-5", callback_data=f"craft_adj_{profile}_bars_-5"),
            InlineKeyboardButton("-1", callback_data=f"craft_adj_{profile}_bars_-1"),
            InlineKeyboardButton("+1", callback_data=f"craft_adj_{profile}_bars_+1"),
            InlineKeyboardButton("+5", callback_data=f"craft_adj_{profile}_bars_+5"),
        ])

    elif mode == "bronze":
        targets = cfg.get("bronze_craft_targets", {"copper_ore": 5, "raw_ore": 5, "copper": 5, "bronze": 5})
        keyboard.append([InlineKeyboardButton(f"🪨 Медн.руда: {targets.get('copper_ore', 5)}", callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton("-5", callback_data=f"craft_adj_{profile}_copper_ore_-5"),
            InlineKeyboardButton("-1", callback_data=f"craft_adj_{profile}_copper_ore_-1"),
            InlineKeyboardButton("+1", callback_data=f"craft_adj_{profile}_copper_ore_+1"),
            InlineKeyboardButton("+5", callback_data=f"craft_adj_{profile}_copper_ore_+5"),
        ])
        keyboard.append([InlineKeyboardButton(f"📦 Жел.руда: {targets.get('raw_ore', 5)}", callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton("-5", callback_data=f"craft_adj_{profile}_raw_ore_-5"),
            InlineKeyboardButton("-1", callback_data=f"craft_adj_{profile}_raw_ore_-1"),
            InlineKeyboardButton("+1", callback_data=f"craft_adj_{profile}_raw_ore_+1"),
            InlineKeyboardButton("+5", callback_data=f"craft_adj_{profile}_raw_ore_+5"),
        ])
        keyboard.append([InlineKeyboardButton(f"🔶 Медь: {targets.get('copper', 5)}", callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton("-5", callback_data=f"craft_adj_{profile}_copper_-5"),
            InlineKeyboardButton("-1", callback_data=f"craft_adj_{profile}_copper_-1"),
            InlineKeyboardButton("+1", callback_data=f"craft_adj_{profile}_copper_+1"),
            InlineKeyboardButton("+5", callback_data=f"craft_adj_{profile}_copper_+5"),
        ])
        keyboard.append([InlineKeyboardButton(f"🥉 Бронза: {targets.get('bronze', 5)}", callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton("-5", callback_data=f"craft_adj_{profile}_bronze_-5"),
            InlineKeyboardButton("-1", callback_data=f"craft_adj_{profile}_bronze_-1"),
            InlineKeyboardButton("+1", callback_data=f"craft_adj_{profile}_bronze_+1"),
            InlineKeyboardButton("+5", callback_data=f"craft_adj_{profile}_bronze_+5"),
        ])

    elif mode == "platinum":
        targets = cfg.get("platinum_craft_targets", {"raw_ore": 5, "platinum": 5})
        keyboard.append([InlineKeyboardButton(f"📦 Жел.руда: {targets.get('raw_ore', 5)}", callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton("-5", callback_data=f"craft_adj_{profile}_raw_ore_-5"),
            InlineKeyboardButton("-1", callback_data=f"craft_adj_{profile}_raw_ore_-1"),
            InlineKeyboardButton("+1", callback_data=f"craft_adj_{profile}_raw_ore_+1"),
            InlineKeyboardButton("+5", callback_data=f"craft_adj_{profile}_raw_ore_+5"),
        ])
        keyboard.append([InlineKeyboardButton(f"💎 Платина: {targets.get('platinum', 5)}", callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton("-5", callback_data=f"craft_adj_{profile}_platinum_-5"),
            InlineKeyboardButton("-1", callback_data=f"craft_adj_{profile}_platinum_-1"),
            InlineKeyboardButton("+1", callback_data=f"craft_adj_{profile}_platinum_+1"),
            InlineKeyboardButton("+5", callback_data=f"craft_adj_{profile}_platinum_+5"),
        ])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"craft_settings_{profile}")])

    return InlineKeyboardMarkup(keyboard)


def adjust_craft_target(profile: str, resource: str, delta: int) -> bool:
    """Изменяет цель крафта на delta"""
    cfg = get_user_settings(profile)
    mode = cfg.get("craft_mode", "iron")

    # Определяем ключ targets
    if mode == "iron":
        key = "iron_craft_targets"
        defaults = {"ore": 5, "iron": 5, "bars": 5}
    elif mode == "bronze":
        key = "bronze_craft_targets"
        defaults = {"copper_ore": 5, "raw_ore": 5, "copper": 5, "bronze": 5}
    elif mode == "platinum":
        key = "platinum_craft_targets"
        defaults = {"raw_ore": 5, "platinum": 5}
    else:
        return False

    targets = cfg.get(key, defaults.copy())
    current = targets.get(resource, defaults.get(resource, 0))
    new_val = max(0, current + delta)  # Не меньше 0
    targets[resource] = new_val
    cfg[key] = targets

    return save_user_settings(profile, cfg)


def set_craft_mode(profile: str, mode: str) -> bool:
    """Устанавливает режим крафта"""
    cfg = get_user_settings(profile)
    cfg["craft_mode"] = mode
    return save_user_settings(profile, cfg)


# ============================================
# Cooldowns Management
# ============================================

def get_cooldowns_keyboard(profile: str):
    """Клавиатура для настройки кулдаунов скиллов"""
    cfg = get_user_settings(profile)
    cooldowns = cfg.get("skill_cooldowns", {})

    keyboard = []

    # Показываем до 5 скиллов
    for skill_num in range(1, 6):
        skill_key = str(skill_num)
        current_cd = cooldowns.get(skill_key, 0)

        if current_cd > 0:
            # Скилл настроен - показываем значение
            keyboard.append([
                InlineKeyboardButton(f"⏱️ Скилл {skill_num}: {current_cd}с", callback_data=f"cd_edit_{profile}_{skill_num}"),
                InlineKeyboardButton(f"🗑️", callback_data=f"cd_del_{profile}_{skill_num}"),
            ])
        else:
            # Скилл не настроен - кнопка добавить
            keyboard.append([
                InlineKeyboardButton(f"➕ Скилл {skill_num}", callback_data=f"cd_edit_{profile}_{skill_num}"),
            ])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"settings_{profile}")])

    return InlineKeyboardMarkup(keyboard)


# Ожидание ввода кулдауна: {user_id: {"profile": "char1", "skill": 2}}
waiting_for_cooldown: Dict[int, dict] = {}

# Ожидание ввода числовых настроек: {user_id: {"profile": "char1", "setting": "arena_max_fights"}}
waiting_for_number_input: Dict[int, dict] = {}


def set_cooldown(profile: str, skill_num: int, value: float) -> bool:
    """Устанавливает кулдаун скилла"""
    cfg = get_user_settings(profile)
    cooldowns = cfg.get("skill_cooldowns", {})

    skill_key = str(skill_num)
    if value > 0:
        cooldowns[skill_key] = value
    elif skill_key in cooldowns:
        del cooldowns[skill_key]

    cfg["skill_cooldowns"] = cooldowns
    return save_user_settings(profile, cfg)


def delete_cooldown(profile: str, skill_num: int) -> bool:
    """Удаляет кулдаун скилла"""
    cfg = get_user_settings(profile)
    cooldowns = cfg.get("skill_cooldowns", {})

    skill_key = str(skill_num)
    if skill_key in cooldowns:
        del cooldowns[skill_key]

    cfg["skill_cooldowns"] = cooldowns
    return save_user_settings(profile, cfg)


# ============================================
# Mines Settings (Шахта)
# ============================================

def get_mines_settings_keyboard(profile: str):
    """Клавиатура настроек шахты"""
    cfg = get_user_settings(profile)
    max_wave = cfg.get("survival_mines_max_wave", 31)
    max_level = cfg.get("survival_mines_max_level", None)

    keyboard = [
        [InlineKeyboardButton(f"🌊 Макс волна: {max_wave}", callback_data=f"mines_wave_{profile}")],
        [InlineKeyboardButton(f"📊 Макс уровень: {max_level or 'не задан'}", callback_data=f"mines_level_{profile}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"settings_{profile}")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================
# Resource Selling Settings (Продажа ресурсов)
# ============================================

# Названия ресурсов для UI
RESOURCE_NAMES_RU = {
    "mineral": "Минерал",
    "skull": "Череп",
    "sapphire": "Сапфир",
    "ruby": "Рубин",
}

# Дефолтные настройки
DEFAULT_SELL_SETTINGS = {
    "mineral": {"enabled": False, "stack": 1000, "reserve": 200},
    "skull": {"enabled": False, "stack": 1000, "reserve": 200},
    "sapphire": {"enabled": False, "stack": 100, "reserve": 10},
    "ruby": {"enabled": False, "stack": 100, "reserve": 10},
}


def get_sell_resources_keyboard(profile: str):
    """Клавиатура настроек продажи ресурсов"""
    cfg = get_user_settings(profile)
    sell_cfg = cfg.get("resource_sell", {})

    keyboard = []

    for res_key, rus_name in RESOURCE_NAMES_RU.items():
        defaults = DEFAULT_SELL_SETTINGS[res_key]
        res_settings = sell_cfg.get(res_key, defaults)

        enabled = res_settings.get("enabled", defaults["enabled"])
        stack = res_settings.get("stack", defaults["stack"])
        reserve = res_settings.get("reserve", defaults["reserve"])

        icon = "✅" if enabled else "❌"
        keyboard.append([
            InlineKeyboardButton(f"{icon} {rus_name}", callback_data=f"sell_toggle_{profile}_{res_key}"),
            InlineKeyboardButton(f"📦 {stack}", callback_data=f"sell_stack_{profile}_{res_key}"),
            InlineKeyboardButton(f"💾 {reserve}", callback_data=f"sell_reserve_{profile}_{res_key}"),
        ])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"settings_{profile}")])
    return InlineKeyboardMarkup(keyboard)


def toggle_sell_resource(profile: str, resource_key: str) -> bool:
    """Переключает продажу ресурса"""
    cfg = get_user_settings(profile)
    sell_cfg = cfg.get("resource_sell", {})

    defaults = DEFAULT_SELL_SETTINGS.get(resource_key, {})
    res_settings = sell_cfg.get(resource_key, defaults.copy())

    res_settings["enabled"] = not res_settings.get("enabled", False)
    sell_cfg[resource_key] = res_settings
    cfg["resource_sell"] = sell_cfg

    return save_user_settings(profile, cfg)


def set_sell_stack(profile: str, resource_key: str, value: int) -> bool:
    """Устанавливает размер стака для продажи"""
    cfg = get_user_settings(profile)
    sell_cfg = cfg.get("resource_sell", {})

    defaults = DEFAULT_SELL_SETTINGS.get(resource_key, {})
    res_settings = sell_cfg.get(resource_key, defaults.copy())

    res_settings["stack"] = value
    sell_cfg[resource_key] = res_settings
    cfg["resource_sell"] = sell_cfg

    return save_user_settings(profile, cfg)


def set_sell_reserve(profile: str, resource_key: str, value: int) -> bool:
    """Устанавливает резерв (сколько оставлять)"""
    cfg = get_user_settings(profile)
    sell_cfg = cfg.get("resource_sell", {})

    defaults = DEFAULT_SELL_SETTINGS.get(resource_key, {})
    res_settings = sell_cfg.get(resource_key, defaults.copy())

    res_settings["reserve"] = value
    sell_cfg[resource_key] = res_settings
    cfg["resource_sell"] = sell_cfg

    return save_user_settings(profile, cfg)


# Ожидание ввода для продажи ресурсов
waiting_for_sell_input: Dict[int, dict] = {}


# ============================================
# HP Thresholds (Пороги HP для скиллов)
# ============================================

def get_hp_thresholds_keyboard(profile: str):
    """Клавиатура настроек HP порогов"""
    cfg = get_user_settings(profile)
    thresholds = cfg.get("skill_hp_threshold", {})

    keyboard = []

    # Показываем до 5 скиллов
    for skill_num in range(1, 6):
        skill_key = str(skill_num)
        current_hp = thresholds.get(skill_key, 0)

        if current_hp > 0:
            # Порог настроен
            keyboard.append([
                InlineKeyboardButton(f"❤️ Скилл {skill_num}: {current_hp} HP", callback_data=f"hp_edit_{profile}_{skill_num}"),
                InlineKeyboardButton(f"🗑️", callback_data=f"hp_del_{profile}_{skill_num}"),
            ])
        else:
            # Не настроен
            keyboard.append([
                InlineKeyboardButton(f"➕ Скилл {skill_num}: без порога", callback_data=f"hp_edit_{profile}_{skill_num}"),
            ])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"settings_{profile}")])
    return InlineKeyboardMarkup(keyboard)


# Ожидание ввода HP порога
waiting_for_hp_threshold: Dict[int, dict] = {}


def set_hp_threshold(profile: str, skill_num: int, value: int) -> bool:
    """Устанавливает HP порог для скилла"""
    cfg = get_user_settings(profile)
    thresholds = cfg.get("skill_hp_threshold", {})

    skill_key = str(skill_num)
    if value > 0:
        thresholds[skill_key] = value
    elif skill_key in thresholds:
        del thresholds[skill_key]

    cfg["skill_hp_threshold"] = thresholds
    return save_user_settings(profile, cfg)


def delete_hp_threshold(profile: str, skill_num: int) -> bool:
    """Удаляет HP порог для скилла"""
    cfg = get_user_settings(profile)
    thresholds = cfg.get("skill_hp_threshold", {})

    skill_key = str(skill_num)
    if skill_key in thresholds:
        del thresholds[skill_key]

    cfg["skill_hp_threshold"] = thresholds
    return save_user_settings(profile, cfg)


# ============================================
# Protected Items Management
# ============================================

PROTECTED_ITEMS_FILE = os.path.join(SCRIPT_DIR, "protected_items.json")

# Дефолтные защищённые предметы (из config.py)
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


def load_protected_items() -> list:
    """Загружает список защищённых предметов"""
    if os.path.exists(PROTECTED_ITEMS_FILE):
        try:
            with open(PROTECTED_ITEMS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_PROTECTED_ITEMS.copy()


def save_protected_items(items: list) -> bool:
    """Сохраняет список защищённых предметов"""
    try:
        with open(PROTECTED_ITEMS_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def add_protected_item(item_name: str) -> bool:
    """Добавляет предмет в защищённые"""
    items = load_protected_items()
    if item_name not in items:
        items.append(item_name)
        return save_protected_items(items)
    return True  # Уже есть


def remove_protected_item(item_name: str) -> bool:
    """Удаляет предмет из защищённых"""
    items = load_protected_items()
    if item_name in items:
        items.remove(item_name)
        return save_protected_items(items)
    return True  # И так нет


def get_protected_items_keyboard(page: int = 0, items_per_page: int = 10):
    """Клавиатура для просмотра защищённых предметов с пагинацией"""
    items = load_protected_items()
    total_pages = (len(items) + items_per_page - 1) // items_per_page

    start = page * items_per_page
    end = min(start + items_per_page, len(items))
    page_items = items[start:end]

    keyboard = []

    for item in page_items:
        # Обрезаем длинные названия
        display_name = item if len(item) <= 25 else item[:22] + "..."
        keyboard.append([InlineKeyboardButton(f"❌ {display_name}", callback_data=f"prot_rm_{item[:50]}")])

    # Навигация по страницам
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"prot_page_{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"prot_page_{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("➕ Добавить предмет", callback_data="prot_add")])
    keyboard.append([InlineKeyboardButton("🔄 Сбросить к дефолту", callback_data="prot_reset")])

    return InlineKeyboardMarkup(keyboard)


# Состояние добавления предмета
waiting_for_protected_item: Dict[int, bool] = {}


def delete_profile(profile: str) -> bool:
    """Удаляет профиль персонажа"""
    import shutil
    profile_dir = os.path.join(PROFILES_DIR, profile)

    if not os.path.exists(profile_dir):
        return False

    try:
        # Сначала останавливаем бота если запущен
        stop_bot(profile)

        # Удаляем папку профиля
        shutil.rmtree(profile_dir)

        # Удаляем из словарей
        if profile in PROFILE_NAMES:
            username = PROFILE_NAMES[profile]
            del PROFILE_NAMES[profile]
            if username in USERNAME_TO_PROFILE:
                del USERNAME_TO_PROFILE[username]

        return True
    except Exception as e:
        print(f"[DELETE] Ошибка удаления профиля {profile}: {e}")
        return False


# ============================================
# Создание нового персонажа
# ============================================

# Состояние создания нового персонажа
new_user_state: Dict[int, dict] = {}

async def cmd_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать создание нового персонажа"""
    if not is_allowed(update.effective_user.id):
        return

    user_id = update.effective_user.id

    # Находим следующий свободный номер
    existing = [int(p.replace("char", "")) for p in PROFILE_NAMES.keys() if p.startswith("char")]
    next_num = max(existing) + 1 if existing else 1

    new_user_state[user_id] = {
        "step": "username",
        "profile": f"char{next_num}"
    }

    await update.message.reply_text(
        f"➕ Создание нового персонажа (char{next_num})\n\n"
        "Введите username (логин в игре):"
    )

async def handle_new_user_input(update: Update, user_id: int, text: str):
    """Обработка ввода при создании персонажа"""
    state = new_user_state.get(user_id)
    if not state:
        return False

    step = state["step"]
    profile = state["profile"]

    if step == "username":
        state["username"] = text
        state["step"] = "password"
        await update.message.reply_text("Введите пароль:")
        return True

    elif step == "password":
        state["password"] = text
        state["step"] = "skill_count"
        await update.message.reply_text("Сколько скиллов у персонажа? (2-6):")
        return True

    elif step == "skill_count":
        try:
            count = int(text)
            if count < 1 or count > 10:
                await update.message.reply_text("❌ Укажите от 1 до 10 скиллов")
                return True
            state["skill_count"] = count
            state["cooldowns"] = {}
            state["current_skill"] = 1
            state["step"] = "skill_cd"
            await update.message.reply_text(f"Введите кулдаун скилла 1 (например 15):")
            return True
        except Exception:
            await update.message.reply_text("❌ Введите число!")
            return True

    elif step == "skill_cd":
        try:
            cd = float(text)
            current = state["current_skill"]
            state["cooldowns"][str(current)] = cd + 0.5

            if current < state["skill_count"]:
                state["current_skill"] = current + 1
                await update.message.reply_text(f"Введите кулдаун скилла {current + 1}:")
                return True
            else:
                # Все кулдауны введены - создаём профиль
                success = create_new_profile(
                    profile,
                    state["username"],
                    state["password"],
                    state["cooldowns"]
                )

                del new_user_state[user_id]

                if success:
                    PROFILE_NAMES[profile] = state["username"]
                    USERNAME_TO_PROFILE[state["username"]] = profile

                    cd_list = ", ".join([f"{k}={v-0.5}с" for k, v in state["cooldowns"].items()])
                    await update.message.reply_text(
                        f"✅ Персонаж создан!\n\n"
                        f"Профиль: {profile}\n"
                        f"Username: {state['username']}\n"
                        f"Скиллы: {cd_list}\n\n"
                        f"Запустите бота: /start_bot {profile}",
                        reply_markup=get_main_keyboard()
                    )
                else:
                    await update.message.reply_text("❌ Ошибка создания профиля", reply_markup=get_main_keyboard())
                return True
        except Exception:
            await update.message.reply_text("❌ Введите число!")
            return True

    return False

def create_new_profile(profile: str, username: str, password: str, cooldowns: dict) -> bool:
    """Создаёт новый профиль"""
    profile_dir = os.path.join(PROFILES_DIR, profile)

    try:
        os.makedirs(profile_dir, exist_ok=True)

        config = {
            "name": f"Character {profile}",
            "description": f"Персонаж {username}",
            "username": username,
            "password": password,
            "backpack_threshold": 15,
            "dungeons_enabled": True,
            "only_dungeons": ["dng:dSanctuary", "dng:dHellRuins"],
            "arena_enabled": False,
            "valentine_event_enabled": False,
            "party_dungeon_enabled": False,
            "hell_games_enabled": False,
            "survival_mines_enabled": False,
            "iron_craft_enabled": True,
            "craft_mode": "iron",
            "iron_craft_targets": {
                "ore": 5,
                "iron": 5,
                "bars": 5
            },
            "skill_cooldowns": cooldowns,
            "skip_dungeons": [],
            "dungeon_action_limits": {
                "default": 500
            }
        }

        config_path = os.path.join(profile_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        cookies_path = os.path.join(profile_dir, "cookies.json")
        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump([], f)

        return True
    except Exception as e:
        print(f"Error creating profile: {e}")
        return False


async def cmd_pull(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Git pull"""
    if not is_allowed(update.effective_user.id):
        return

    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout + result.stderr
        await update.message.reply_text(f"📥 Git pull:\n```\n{output}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback кнопок"""
    query = update.callback_query
    await query.answer()

    if not is_allowed(query.from_user.id):
        return

    data = query.data

    # Web panel control
    if data == "wp_start":
        success, msg = start_web_panel()
        status = get_web_panel_status()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть веб-панель", url=WEB_PANEL_URL)],
            [
                InlineKeyboardButton("▶️ Запустить", callback_data="wp_start"),
                InlineKeyboardButton("⏹️ Стоп", callback_data="wp_stop"),
                InlineKeyboardButton("🔄 Рестарт", callback_data="wp_restart")
            ]
        ])
        await query.edit_message_text(
            f"🌐 Веб-панель\n\n"
            f"{'✅' if success else '❌'} {msg}\n"
            f"Статус: {status}\n"
            f"URL: {WEB_PANEL_URL}",
            reply_markup=keyboard
        )

    elif data == "wp_stop":
        success, msg = stop_web_panel()
        status = get_web_panel_status()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть веб-панель", url=WEB_PANEL_URL)],
            [
                InlineKeyboardButton("▶️ Запустить", callback_data="wp_start"),
                InlineKeyboardButton("⏹️ Стоп", callback_data="wp_stop"),
                InlineKeyboardButton("🔄 Рестарт", callback_data="wp_restart")
            ]
        ])
        await query.edit_message_text(
            f"🌐 Веб-панель\n\n"
            f"{'✅' if success else '❌'} {msg}\n"
            f"Статус: {status}\n"
            f"URL: {WEB_PANEL_URL}",
            reply_markup=keyboard
        )

    elif data == "wp_restart":
        success, msg = restart_web_panel()
        status = get_web_panel_status()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть веб-панель", url=WEB_PANEL_URL)],
            [
                InlineKeyboardButton("▶️ Запустить", callback_data="wp_start"),
                InlineKeyboardButton("⏹️ Стоп", callback_data="wp_stop"),
                InlineKeyboardButton("🔄 Рестарт", callback_data="wp_restart")
            ]
        ])
        await query.edit_message_text(
            f"🌐 Веб-панель\n\n"
            f"{'✅' if success else '❌'} {msg}\n"
            f"Статус: {status}\n"
            f"URL: {WEB_PANEL_URL}",
            reply_markup=keyboard
        )

    # Stats
    elif data.startswith("stats_"):
        profile = data[6:]
        if profile == "all":
            text = get_all_stats_compact()
            await query.edit_message_text(text, parse_mode="HTML")
        else:
            await query.edit_message_text(get_stats(profile))

    # Start
    elif data.startswith("start_"):
        profile = data[6:]
        if profile == "all":
            results = []
            for p, name in PROFILE_NAMES.items():
                success, msg = start_bot(p)
                results.append(f"{name}: {msg}")
            await query.edit_message_text("▶️ Запуск:\n" + "\n".join(results))
        else:
            success, msg = start_bot(profile)
            await query.edit_message_text(msg)

    # Stop
    elif data.startswith("stop_"):
        profile = data[5:]
        if profile == "all":
            results = []
            for p, name in PROFILE_NAMES.items():
                success, msg = stop_bot(p)
                results.append(f"{name}: {msg}")
            await query.edit_message_text("⏹️ Остановка:\n" + "\n".join(results))
        else:
            success, msg = stop_bot(profile)
            await query.edit_message_text(msg)

    # Restart
    elif data.startswith("restart_"):
        profile = data[8:]
        if profile == "all":
            results = []
            for p, name in PROFILE_NAMES.items():
                success, msg = restart_bot(p)
                results.append(f"{name}: {msg}")
            await query.edit_message_text("🔄 Перезапуск:\n" + "\n".join(results))
        else:
            success, msg = restart_bot(profile)
            await query.edit_message_text(msg)

    # Cooldowns - настройки кулдаунов
    elif data.startswith("cooldowns_"):
        profile = data[10:]  # cooldowns_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)

        await query.edit_message_text(
            f"⏱️ Кулдауны скиллов для {name}\n\n"
            f"Нажми на скилл чтобы задать кулдаун.\n"
            f"⚠️ После изменения перезапусти бота!",
            reply_markup=get_cooldowns_keyboard(profile)
        )

    # Cooldown edit - ввод нового значения
    elif data.startswith("cd_edit_"):
        # cd_edit_char1_2
        parts = data.split("_")
        if len(parts) >= 4:
            profile = parts[2]
            skill_num = int(parts[3])
            name = PROFILE_NAMES.get(profile, profile)

            # Запоминаем что ждём ввод
            user_id = query.from_user.id
            waiting_for_cooldown[user_id] = {"profile": profile, "skill": skill_num}

            # Текущее значение
            cfg = get_user_settings(profile)
            cooldowns = cfg.get("skill_cooldowns", {})
            current = cooldowns.get(str(skill_num), 0)

            example = f"Текущее: {current}с" if current > 0 else "Сейчас не задан"

            await query.edit_message_text(
                f"⏱️ Скилл {skill_num} для {name}\n\n"
                f"{example}\n\n"
                f"Введи кулдаун в секундах:\n"
                f"Примеры: 15, 30, 45.5, 60",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data=f"cooldowns_{profile}")
                ]])
            )

    # Cooldown delete - удалить кулдаун скилла
    elif data.startswith("cd_del_"):
        # cd_del_char1_2
        parts = data.split("_")
        if len(parts) >= 4:
            profile = parts[2]
            skill_num = int(parts[3])
            name = PROFILE_NAMES.get(profile, profile)

            delete_cooldown(profile, skill_num)

            await query.edit_message_text(
                f"⏱️ Кулдауны скиллов для {name}\n\n"
                f"✅ Скилл {skill_num} удалён\n\n"
                f"Нажми на скилл чтобы задать кулдаун.\n"
                f"⚠️ После изменения перезапусти бота!",
                reply_markup=get_cooldowns_keyboard(profile)
            )

    # Arena max fights - макс боёв на арене
    elif data.startswith("arena_max_"):
        profile = data[10:]  # arena_max_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)
        cfg = get_user_settings(profile)
        current = cfg.get("arena_max_fights", 50)

        user_id = query.from_user.id
        waiting_for_number_input[user_id] = {"profile": profile, "setting": "arena_max_fights", "name": "Макс боёв на арене"}

        await query.edit_message_text(
            f"🎯 Макс боёв на арене для {name}\n\n"
            f"Текущее: {current}\n\n"
            f"Введи число (например: 30, 50, 100):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data=f"settings_{profile}")
            ]])
        )

    # Backpack threshold - порог очистки рюкзака
    elif data.startswith("backpack_th_"):
        profile = data[12:]  # backpack_th_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)
        cfg = get_user_settings(profile)
        current = cfg.get("backpack_threshold", 18)

        user_id = query.from_user.id
        waiting_for_number_input[user_id] = {"profile": profile, "setting": "backpack_threshold", "name": "Порог рюкзака"}

        await query.edit_message_text(
            f"🎒 Порог очистки рюкзака для {name}\n\n"
            f"Текущее: {current} слотов\n"
            f"(Рюкзак очищается когда занято >= этого числа)\n\n"
            f"Введи число (например: 15, 18, 20):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data=f"settings_{profile}")
            ]])
        )

    # Mines settings - настройки шахты
    elif data.startswith("mines_settings_"):
        profile = data[15:]  # mines_settings_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)

        await query.edit_message_text(
            f"⛏️ Настройки шахты для {name}\n\n"
            f"🌊 Макс волна - на какой волне выходить\n"
            f"📊 Макс уровень - на каком уровне остановить бота\n",
            reply_markup=get_mines_settings_keyboard(profile)
        )

    # Mines max wave
    elif data.startswith("mines_wave_"):
        profile = data[11:]  # mines_wave_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)
        cfg = get_user_settings(profile)
        current = cfg.get("survival_mines_max_wave", 31)

        user_id = query.from_user.id
        waiting_for_number_input[user_id] = {"profile": profile, "setting": "survival_mines_max_wave", "name": "Макс волна шахты"}

        await query.edit_message_text(
            f"🌊 Макс волна шахты для {name}\n\n"
            f"Текущее: {current}\n"
            f"(Бот выходит из шахты после этой волны)\n\n"
            f"Введи число (например: 20, 31, 50):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data=f"mines_settings_{profile}")
            ]])
        )

    # Mines max level
    elif data.startswith("mines_level_"):
        profile = data[12:]  # mines_level_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)
        cfg = get_user_settings(profile)
        current = cfg.get("survival_mines_max_level", None)

        user_id = query.from_user.id
        waiting_for_number_input[user_id] = {"profile": profile, "setting": "survival_mines_max_level", "name": "Макс уровень шахты", "allow_none": True}

        await query.edit_message_text(
            f"📊 Макс уровень для {name}\n\n"
            f"Текущее: {current or 'не задан'}\n"
            f"(Бот остановится когда достигнет этого уровня)\n\n"
            f"Введи число или 0 чтобы отключить:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data=f"mines_settings_{profile}")
            ]])
        )

    # Sell Resources - настройки продажи ресурсов
    elif data.startswith("sell_resources_"):
        profile = data[15:]  # sell_resources_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)

        await query.edit_message_text(
            f"💎 Продажа ресурсов для {name}\n\n"
            f"✅/❌ - включить/выключить продажу\n"
            f"📦 - размер стака (сколько продавать за раз)\n"
            f"💾 - резерв (сколько оставлять)\n\n"
            f"Логика: если ресурсов >= резерв + стак,\n"
            f"продаём (ресурсов - резерв) // стак лотов",
            reply_markup=get_sell_resources_keyboard(profile)
        )

    # Toggle sell resource
    elif data.startswith("sell_toggle_"):
        # sell_toggle_char1_mineral
        parts = data.split("_")
        if len(parts) >= 4:
            profile = parts[2]
            resource = parts[3]
            name = PROFILE_NAMES.get(profile, profile)

            toggle_sell_resource(profile, resource)
            rus_name = RESOURCE_NAMES_RU.get(resource, resource)

            await query.edit_message_text(
                f"💎 Продажа ресурсов для {name}\n\n"
                f"✅ {rus_name} переключён\n\n"
                f"✅/❌ - включить/выключить продажу\n"
                f"📦 - размер стака\n"
                f"💾 - резерв",
                reply_markup=get_sell_resources_keyboard(profile)
            )

    # Edit sell stack
    elif data.startswith("sell_stack_"):
        # sell_stack_char1_mineral
        parts = data.split("_")
        if len(parts) >= 4:
            profile = parts[2]
            resource = parts[3]
            name = PROFILE_NAMES.get(profile, profile)
            rus_name = RESOURCE_NAMES_RU.get(resource, resource)

            user_id = query.from_user.id
            waiting_for_sell_input[user_id] = {"profile": profile, "resource": resource, "type": "stack"}

            cfg = get_user_settings(profile)
            sell_cfg = cfg.get("resource_sell", {})
            defaults = DEFAULT_SELL_SETTINGS.get(resource, {})
            current = sell_cfg.get(resource, defaults).get("stack", defaults.get("stack", 1000))

            await query.edit_message_text(
                f"📦 Размер стака для {rus_name} ({name})\n\n"
                f"Текущее: {current}\n\n"
                f"Введи число (например: 100, 500, 1000):",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data=f"sell_resources_{profile}")
                ]])
            )

    # Edit sell reserve
    elif data.startswith("sell_reserve_"):
        # sell_reserve_char1_mineral
        parts = data.split("_")
        if len(parts) >= 4:
            profile = parts[2]
            resource = parts[3]
            name = PROFILE_NAMES.get(profile, profile)
            rus_name = RESOURCE_NAMES_RU.get(resource, resource)

            user_id = query.from_user.id
            waiting_for_sell_input[user_id] = {"profile": profile, "resource": resource, "type": "reserve"}

            cfg = get_user_settings(profile)
            sell_cfg = cfg.get("resource_sell", {})
            defaults = DEFAULT_SELL_SETTINGS.get(resource, {})
            current = sell_cfg.get(resource, defaults).get("reserve", defaults.get("reserve", 200))

            await query.edit_message_text(
                f"💾 Резерв для {rus_name} ({name})\n\n"
                f"Текущее: {current}\n"
                f"(Столько ресурсов оставлять, не продавать)\n\n"
                f"Введи число (например: 100, 200, 500):",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data=f"sell_resources_{profile}")
                ]])
            )

    # HP Thresholds - пороги HP для скиллов
    elif data.startswith("hp_thresholds_"):
        profile = data[14:]  # hp_thresholds_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)

        await query.edit_message_text(
            f"🎯 HP пороги скиллов для {name}\n\n"
            f"Скилл используется только если HP врага > порога.\n"
            f"Полезно для экономии сильных скиллов.\n\n"
            f"Нажми на скилл чтобы задать порог:",
            reply_markup=get_hp_thresholds_keyboard(profile)
        )

    # HP threshold edit
    elif data.startswith("hp_edit_"):
        # hp_edit_char1_2
        parts = data.split("_")
        if len(parts) >= 4:
            profile = parts[2]
            skill_num = int(parts[3])
            name = PROFILE_NAMES.get(profile, profile)

            user_id = query.from_user.id
            waiting_for_hp_threshold[user_id] = {"profile": profile, "skill": skill_num}

            cfg = get_user_settings(profile)
            thresholds = cfg.get("skill_hp_threshold", {})
            current = thresholds.get(str(skill_num), 0)

            example = f"Текущее: {current} HP" if current > 0 else "Сейчас без порога"

            await query.edit_message_text(
                f"❤️ HP порог для скилла {skill_num} ({name})\n\n"
                f"{example}\n\n"
                f"Введи минимум HP врага для использования:\n"
                f"Примеры: 10000, 20000, 50000",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data=f"hp_thresholds_{profile}")
                ]])
            )

    # HP threshold delete
    elif data.startswith("hp_del_"):
        # hp_del_char1_2
        parts = data.split("_")
        if len(parts) >= 4:
            profile = parts[2]
            skill_num = int(parts[3])
            name = PROFILE_NAMES.get(profile, profile)

            delete_hp_threshold(profile, skill_num)

            await query.edit_message_text(
                f"🎯 HP пороги скиллов для {name}\n\n"
                f"✅ Порог для скилла {skill_num} удалён\n\n"
                f"Нажми на скилл чтобы задать порог:",
                reply_markup=get_hp_thresholds_keyboard(profile)
            )

    # Craft settings - настройки крафта (должен быть ПЕРЕД craft_)
    elif data.startswith("craft_settings_"):
        profile = data[15:]  # craft_settings_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)
        cfg = get_user_settings(profile)
        items = cfg.get("craft_items", [])

        if items:
            items_text = "\n".join([
                f"  {i+1}. {CRAFTABLE_ITEMS.get(item['item'], item['item'])} (партия: {item['batch_size']} шт)"
                for i, item in enumerate(items)
            ])
            text = f"⚒️ Автокрафт для {name}\n\n{items_text}"
        else:
            text = f"⚒️ Автокрафт для {name}\n\nСписок пуст"

        await query.edit_message_text(
            text,
            reply_markup=get_craft_settings_keyboard(profile)
        )

    # Craft queue - добавить предмет (показать выбор количества)
    elif data.startswith("cq_add_"):
        # cq_add_char1_iron
        parts = data.split("_")  # ['cq', 'add', 'char1', 'iron']
        if len(parts) >= 4:
            profile = parts[2]
            item_id = parts[3]
            name = PROFILE_NAMES.get(profile, profile)
            item_name = CRAFTABLE_ITEMS.get(item_id, item_id)

            await query.edit_message_text(
                f"⚒️ {name}: добавить {item_name}\n\nВыбери количество:",
                reply_markup=get_craft_count_keyboard(profile, item_id)
            )

    # Craft queue - выбрано количество, добавить в список
    elif data.startswith("cq_cnt_"):
        # cq_cnt_char1_iron_10
        parts = data.split("_")  # ['cq', 'cnt', 'char1', 'iron', '10']
        if len(parts) >= 5:
            profile = parts[2]
            item_id = parts[3]
            batch_size = int(parts[4])
            name = PROFILE_NAMES.get(profile, profile)
            item_name = CRAFTABLE_ITEMS.get(item_id, item_id)

            # Добавить в список автокрафта
            cfg = get_user_settings(profile)
            items = cfg.get("craft_items", [])
            items.append({"item": item_id, "batch_size": batch_size})
            cfg["craft_items"] = items
            save_user_settings(profile, cfg)

            await query.edit_message_text(
                f"✅ {name}: добавлено {item_name} (партия: {batch_size} шт)",
                reply_markup=get_craft_settings_keyboard(profile)
            )

    # Craft queue - удалить элемент из списка
    elif data.startswith("cq_del_"):
        # cq_del_char1_0
        parts = data.split("_")  # ['cq', 'del', 'char1', '0']
        if len(parts) >= 4:
            profile = parts[2]
            index = int(parts[3])
            name = PROFILE_NAMES.get(profile, profile)

            cfg = get_user_settings(profile)
            items = cfg.get("craft_items", [])
            if 0 <= index < len(items):
                removed = items.pop(index)
                cfg["craft_items"] = items
                save_user_settings(profile, cfg)
                item_name = CRAFTABLE_ITEMS.get(removed["item"], removed["item"])

                await query.edit_message_text(
                    f"✅ {name}: удалено {item_name} (партия: {removed['batch_size']} шт)",
                    reply_markup=get_craft_settings_keyboard(profile)
                )

    # Craft queue - очистить весь список
    elif data.startswith("cq_clear_"):
        profile = data[9:]  # cq_clear_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)

        cfg = get_user_settings(profile)
        cfg["craft_items"] = []
        save_user_settings(profile, cfg)

        await query.edit_message_text(
            f"✅ {name}: список автокрафта очищен",
            reply_markup=get_craft_settings_keyboard(profile)
        )

    # Craft mode - изменить режим крафта (должен быть ПЕРЕД craft_) - DEPRECATED
    elif data.startswith("craft_mode_"):
        # craft_mode_char1_bronze
        parts = data.split("_", 3)  # ['craft', 'mode', 'char1', 'bronze']
        if len(parts) == 4:
            profile = parts[2]
            mode = parts[3]
            name = PROFILE_NAMES.get(profile, profile)

            if set_craft_mode(profile, mode):
                mode_name = {"iron": "Железо", "bronze": "Бронза", "platinum": "Платина", "copperBar": "Медный Слиток"}.get(mode, mode)
                await query.edit_message_text(
                    f"✅ {name}: режим крафта изменён на {mode_name}\n\n"
                    f"⚠️ Перезапусти бота чтобы применить!",
                    reply_markup=get_craft_settings_keyboard(profile)
                )

    # Craft targets - показать настройку целей (должен быть ПЕРЕД craft_) - DEPRECATED
    elif data.startswith("craft_targets_"):
        profile = data[14:]  # craft_targets_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)
        cfg = get_user_settings(profile)
        mode = cfg.get("craft_mode", "iron")

        await query.edit_message_text(
            f"🔢 Цели крафта для {name}\n\n"
            f"Режим: {mode.upper()}\n"
            f"Используй кнопки +/- для изменения:",
            reply_markup=get_craft_targets_keyboard(profile)
        )

    # Craft adjust - изменить цель крафта (должен быть ПЕРЕД craft_) - DEPRECATED
    elif data.startswith("craft_adj_"):
        # craft_adj_char1_ore_+5
        parts = data.split("_")  # ['craft', 'adj', 'char1', 'ore', '+5']
        if len(parts) >= 5:
            profile = parts[2]
            resource = parts[3]
            delta_str = parts[4]

            try:
                delta = int(delta_str)
            except Exception:
                delta = 0

            if adjust_craft_target(profile, resource, delta):
                # Обновляем клавиатуру
                name = PROFILE_NAMES.get(profile, profile)
                cfg = get_user_settings(profile)
                mode = cfg.get("craft_mode", "iron")

                await query.edit_message_text(
                    f"🔢 Цели крафта для {name}\n\n"
                    f"Режим: {mode.upper()}\n"
                    f"Используй кнопки +/- для изменения:",
                    reply_markup=get_craft_targets_keyboard(profile)
                )

    # Craft (старый callback из меню крафта) - ПОСЛЕ более специфичных
    elif data.startswith("craft_"):
        profile = data[6:]
        name = PROFILE_NAMES.get(profile, profile)
        craft = get_craft_config(profile)

        if not craft["enabled"]:
            text = f"⚪ {name}: крафт отключен"
        else:
            mode = craft["mode"]
            if mode == "iron":
                t = craft["iron_targets"]
                text = (
                    f"⚒️ {name} - железо\n\n"
                    f"📦 Руда: {t.get('ore', 0)}\n"
                    f"🔩 Железо: {t.get('iron', 0)}\n"
                    f"📊 Слитки: {t.get('bars', 0)}\n\n"
                    f"Изменить: /craft {profile} руда железо слитки"
                )
            elif mode == "bronze":
                t = craft["bronze_targets"]
                text = (
                    f"🥉 {name} - бронза\n\n"
                    f"🪨 Медная руда: {t.get('copper_ore', 0)}\n"
                    f"📦 Жел.руда: {t.get('raw_ore', 0)}\n"
                    f"🔶 Медь: {t.get('copper', 0)}\n"
                    f"🥉 Бронза: {t.get('bronze', 0)}"
                )
            else:
                text = f"⚒️ {name}: режим {mode}"

        await query.edit_message_text(text)

    # Settings - показать настройки персонажа
    elif data.startswith("settings_"):
        if data == "settings_back":
            # Вернуться к списку персонажей
            keyboard = []
            for profile, name in PROFILE_NAMES.items():
                keyboard.append([InlineKeyboardButton(f"⚙️ {name}", callback_data=f"settings_{profile}")])
            await query.edit_message_text(
                "⚙️ Выберите персонажа для настройки:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            profile = data[9:]  # settings_char1 -> char1
            text = format_user_settings(profile)
            await query.edit_message_text(text, reply_markup=get_settings_keyboard(profile))

    # Toggle - переключить настройку
    elif data.startswith("toggle_"):
        # toggle_char1_dungeons_enabled
        parts = data.split("_", 2)  # ['toggle', 'char1', 'dungeons_enabled']
        if len(parts) == 3:
            profile = parts[1]
            setting = parts[2]
            success, new_value = toggle_setting(profile, setting)
            if success:
                # Обновляем клавиатуру
                text = format_user_settings(profile)
                await query.edit_message_text(text, reply_markup=get_settings_keyboard(profile))

    # Delete - удаление персонажа (с подтверждением)
    elif data.startswith("delete_"):
        profile = data[7:]  # delete_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)

        # Показываем подтверждение
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{profile}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"settings_{profile}")
            ]
        ]
        await query.edit_message_text(
            f"⚠️ Удалить персонажа {name}?\n\n"
            f"Это удалит:\n"
            f"• Конфигурацию\n"
            f"• Cookies\n"
            f"• Логи\n"
            f"• Статистику\n\n"
            f"Действие необратимо!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # Confirm delete - подтверждение удаления
    elif data.startswith("confirm_delete_"):
        profile = data[15:]  # confirm_delete_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)

        if delete_profile(profile):
            await query.edit_message_text(f"✅ Персонаж {name} удалён")
        else:
            await query.edit_message_text(f"❌ Ошибка удаления {name}")

    # Dungeons list - показать список данжей
    elif data.startswith("dungeons_list_"):
        profile = data[14:]  # dungeons_list_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)
        await query.edit_message_text(
            f"🏰 Данжи для {name}\n\n"
            f"✅ = посещается\n"
            f"❌ = пропускается",
            reply_markup=get_dungeons_keyboard(profile)
        )

    # Toggle dungeon - переключить конкретный данж
    elif data.startswith("dng_"):
        # dng_char1_dng:dSanctuary
        parts = data.split("_", 2)  # ['dng', 'char1', 'dng:dSanctuary']
        if len(parts) == 3:
            profile = parts[1]
            dungeon_id = parts[2]
            name = PROFILE_NAMES.get(profile, profile)

            if toggle_dungeon(profile, dungeon_id):
                await query.edit_message_text(
                    f"🏰 Данжи для {name}\n\n"
                    f"✅ = посещается\n"
                    f"❌ = пропускается",
                    reply_markup=get_dungeons_keyboard(profile)
                )

    # Deaths list - показать список смертей/сложностей
    elif data.startswith("deaths_list_"):
        profile = data[12:]  # deaths_list_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)
        await query.edit_message_text(
            f"☠️ Смерти и сложность данжей для {name}\n\n"
            f"Нажми на данж чтобы изменить сложность\n"
            f"или сбросить историю смертей.",
            reply_markup=get_deaths_keyboard(profile)
        )

    # Death info - показать информацию о смерти в данже
    elif data.startswith("death_info_"):
        # death_info_char1_dng:RestMonastery
        parts = data.split("_", 3)  # ['death', 'info', 'char1', 'dng:RestMonastery']
        if len(parts) == 4:
            profile = parts[2]
            dungeon_id = parts[3]
            name = PROFILE_NAMES.get(profile, profile)
            dng_name = ALL_DUNGEONS.get(dungeon_id, dungeon_id)

            deaths_data = load_deaths(profile)
            if dungeon_id in deaths_data:
                d = deaths_data[dungeon_id]
                death_count = len(d.get("deaths", []))
                current_diff = d.get("current_difficulty", "brutal")
                diff_name = DIFFICULTY_NAMES.get(current_diff, current_diff)

                text = (
                    f"☠️ {dng_name}\n\n"
                    f"Текущая сложность: {diff_name}\n"
                    f"Смертей: {death_count}\n\n"
                    f"Выбери новую сложность:"
                )
            else:
                text = f"☠️ {dng_name}\n\nНет данных о смертях.\nВыбери сложность:"

            await query.edit_message_text(text, reply_markup=get_difficulty_keyboard(profile, dungeon_id))

    # Set difficulty - установить сложность данжа
    elif data.startswith("set_diff_"):
        # set_diff_char1_dng:RestMonastery_hero
        parts = data.split("_", 4)  # ['set', 'diff', 'char1', 'dng:RestMonastery', 'hero']
        if len(parts) == 5:
            profile = parts[2]
            dungeon_id = parts[3]
            difficulty = parts[4]
            name = PROFILE_NAMES.get(profile, profile)
            dng_name = ALL_DUNGEONS.get(dungeon_id, dungeon_id)

            if set_dungeon_difficulty(profile, dungeon_id, difficulty):
                diff_name = DIFFICULTY_NAMES.get(difficulty, difficulty)
                await query.edit_message_text(
                    f"✅ {dng_name}: сложность изменена на {diff_name}\n\n"
                    f"⚠️ Перезапусти бота чтобы применить!",
                    reply_markup=get_difficulty_keyboard(profile, dungeon_id)
                )

    # Reset death - сбросить историю смертей для одного данжа
    elif data.startswith("reset_death_"):
        # reset_death_char1_dng:RestMonastery
        parts = data.split("_", 3)  # ['reset', 'death', 'char1', 'dng:RestMonastery']
        if len(parts) == 4:
            profile = parts[2]
            dungeon_id = parts[3]
            name = PROFILE_NAMES.get(profile, profile)
            dng_name = ALL_DUNGEONS.get(dungeon_id, dungeon_id)

            if reset_deaths(profile, dungeon_id):
                await query.edit_message_text(
                    f"✅ {dng_name}: история смертей сброшена\n"
                    f"Сложность сброшена на брутал\n\n"
                    f"⚠️ Перезапусти бота чтобы применить!",
                    reply_markup=get_deaths_keyboard(profile)
                )

    # Reset all deaths - сбросить всю историю смертей
    elif data.startswith("reset_all_deaths_"):
        profile = data[17:]  # reset_all_deaths_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)

        # Показываем подтверждение
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, сбросить всё", callback_data=f"confirm_reset_deaths_{profile}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"deaths_list_{profile}")
            ]
        ]
        await query.edit_message_text(
            f"⚠️ Сбросить всю историю смертей для {name}?\n\n"
            f"Все данжи будут на брутал сложности.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # Confirm reset all deaths
    elif data.startswith("confirm_reset_deaths_"):
        profile = data[21:]  # confirm_reset_deaths_char1 -> char1
        name = PROFILE_NAMES.get(profile, profile)

        if reset_deaths(profile):
            await query.edit_message_text(
                f"✅ {name}: вся история смертей сброшена\n"
                f"Все данжи теперь на брутал сложности.\n\n"
                f"⚠️ Перезапусти бота чтобы применить!",
                reply_markup=get_deaths_keyboard(profile)
            )

    # Protected items - пагинация
    elif data.startswith("prot_page_"):
        page = int(data[10:])
        items = load_protected_items()
        await query.edit_message_text(
            f"🛡️ Защищённые предметы ({len(items)} шт)\n\n"
            f"Эти предметы НЕ продаются и НЕ разбираются.\n"
            f"Нажми на предмет чтобы удалить.",
            reply_markup=get_protected_items_keyboard(page)
        )

    # Protected items - удалить предмет
    elif data.startswith("prot_rm_"):
        item_name = data[8:]
        if remove_protected_item(item_name):
            items = load_protected_items()
            await query.edit_message_text(
                f"✅ Удалено: {item_name}\n\n"
                f"🛡️ Защищённые предметы ({len(items)} шт)\n"
                f"⚠️ Перезапусти ботов чтобы применить!",
                reply_markup=get_protected_items_keyboard(0)
            )

    # Protected items - добавить предмет
    elif data == "prot_add":
        user_id = query.from_user.id
        waiting_for_protected_item[user_id] = True
        await query.edit_message_text(
            "➕ Введите название предмета для защиты:\n\n"
            "(Можно вводить частичное название,\n"
            "например 'Оберегов' для всех ларцов)"
        )

    # Protected items - сброс к дефолту
    elif data == "prot_reset":
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, сбросить", callback_data="prot_reset_confirm"),
                InlineKeyboardButton("❌ Отмена", callback_data="prot_page_0")
            ]
        ]
        await query.edit_message_text(
            "⚠️ Сбросить список защищённых предметов к значениям по умолчанию?\n\n"
            "Все ваши добавленные предметы будут удалены!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # Protected items - подтверждение сброса
    elif data == "prot_reset_confirm":
        if save_protected_items(DEFAULT_PROTECTED_ITEMS.copy()):
            items = load_protected_items()
            await query.edit_message_text(
                f"✅ Список сброшен к значениям по умолчанию!\n\n"
                f"🛡️ Защищённые предметы ({len(items)} шт)\n"
                f"⚠️ Перезапусти ботов чтобы применить!",
                reply_markup=get_protected_items_keyboard(0)
            )

    # Noop - пустой callback для информационных кнопок
    elif data == "noop":
        pass


async def handle_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых кнопок"""
    if not is_allowed(update.effective_user.id):
        return

    text = update.message.text

    if text == "📡 Статус":
        await cmd_status(update, context)

    elif text == "📊 Статистика":
        await cmd_stats(update, context)

    elif text == "📥 Pull":
        await cmd_pull(update, context)

    elif text == "📋 Логи":
        await cmd_logs(update, context)

    elif text == "▶️ Запустить":
        await cmd_start_bot(update, context)

    elif text == "⏹️ Остановить":
        await cmd_stop_bot(update, context)

    elif text == "🔄 Рестарт":
        await cmd_restart_bot(update, context)

    elif text == "⚒️ Крафт":
        await cmd_craft(update, context)

    elif text == "📦 Инвентарь":
        await cmd_inventory(update, context)

    elif text == "💰 Продать крафты":
        await cmd_sell_crafts(update, context)

    elif text == "⚙️ Настройки":
        await cmd_settings(update, context)

    elif text == "➕ Новый":
        await cmd_new_user(update, context)

    elif text == "🤖 AI Debug":
        await cmd_ai_debug(update, context)

    elif text == "💬 Спросить AI":
        user_id = update.effective_user.id
        waiting_for_ai_question[user_id] = True
        await update.message.reply_text(
            "💬 Напиши свой вопрос для Claude:\n\n"
            "(Или нажми любую другую кнопку для отмены)"
        )

    elif text == "🔄 Сброс скипов":
        await cmd_reset_skips(update, context)

    elif text == "🛡️ Защита":
        items = load_protected_items()
        await update.message.reply_text(
            f"🛡️ Защищённые предметы ({len(items)} шт)\n\n"
            f"Эти предметы НЕ продаются и НЕ разбираются.\n"
            f"Нажми на предмет чтобы удалить.",
            reply_markup=get_protected_items_keyboard(0)
        )

    elif text == "🌐 Веб-панель":
        # Показываем статус и кнопки управления веб-панелью
        status = get_web_panel_status()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть веб-панель", url=WEB_PANEL_URL)],
            [
                InlineKeyboardButton("▶️ Запустить", callback_data="wp_start"),
                InlineKeyboardButton("⏹️ Стоп", callback_data="wp_stop"),
                InlineKeyboardButton("🔄 Рестарт", callback_data="wp_restart")
            ]
        ])
        await update.message.reply_text(
            f"🌐 Веб-панель управления ботами\n\n"
            f"Статус: {status}\n"
            f"URL: {WEB_PANEL_URL}",
            reply_markup=keyboard
        )

    # Обработка ввода нового защищённого предмета
    elif waiting_for_protected_item.get(update.effective_user.id, False):
        user_id = update.effective_user.id
        waiting_for_protected_item[user_id] = False

        item_name = text.strip()
        if item_name:
            if add_protected_item(item_name):
                items = load_protected_items()
                await update.message.reply_text(
                    f"✅ Добавлено: {item_name}\n\n"
                    f"🛡️ Защищённые предметы ({len(items)} шт)\n"
                    f"⚠️ Перезапусти ботов чтобы применить!",
                    reply_markup=get_protected_items_keyboard(0)
                )
            else:
                await update.message.reply_text("❌ Ошибка добавления", reply_markup=get_main_keyboard())
        else:
            await update.message.reply_text("❌ Пустое название", reply_markup=get_main_keyboard())

    # Обработка ввода нового пользователя
    elif new_user_state.get(update.effective_user.id):
        await handle_new_user_input(update, update.effective_user.id, text)

    # Обработка ввода числовых настроек (арена, рюкзак, шахта и т.д.)
    elif update.effective_user.id in waiting_for_number_input:
        user_id = update.effective_user.id
        input_data = waiting_for_number_input.pop(user_id)
        profile = input_data["profile"]
        setting = input_data["setting"]
        setting_name = input_data["name"]
        allow_none = input_data.get("allow_none", False)
        name = PROFILE_NAMES.get(profile, profile)

        try:
            value = int(text)

            cfg = get_user_settings(profile)

            # Если allow_none и значение 0 - убираем настройку
            if allow_none and value == 0:
                if setting in cfg:
                    del cfg[setting]
                save_user_settings(profile, cfg)
                await update.message.reply_text(
                    f"✅ {name}: {setting_name} отключён\n\n"
                    f"⚠️ Перезапусти бота чтобы применить!",
                    reply_markup=get_settings_keyboard(profile)
                )
            elif value <= 0:
                raise ValueError("Должно быть > 0")
            else:
                cfg[setting] = value
                save_user_settings(profile, cfg)
                await update.message.reply_text(
                    f"✅ {name}: {setting_name} = {value}\n\n"
                    f"⚠️ Перезапусти бота чтобы применить!",
                    reply_markup=get_settings_keyboard(profile)
                )
        except ValueError:
            msg = "❌ Введи целое число > 0" if not allow_none else "❌ Введи целое число (0 для отключения)"
            await update.message.reply_text(msg, reply_markup=get_settings_keyboard(profile))

    # Обработка ввода HP порога
    elif update.effective_user.id in waiting_for_hp_threshold:
        user_id = update.effective_user.id
        hp_data = waiting_for_hp_threshold.pop(user_id)
        profile = hp_data["profile"]
        skill_num = hp_data["skill"]
        name = PROFILE_NAMES.get(profile, profile)

        try:
            value = int(text)
            if value < 0:
                raise ValueError("Должно быть >= 0")

            if value == 0:
                delete_hp_threshold(profile, skill_num)
                await update.message.reply_text(
                    f"✅ {name}: HP порог для скилла {skill_num} удалён\n\n"
                    f"⚠️ Перезапусти бота чтобы применить!",
                    reply_markup=get_hp_thresholds_keyboard(profile)
                )
            else:
                set_hp_threshold(profile, skill_num, value)
                await update.message.reply_text(
                    f"✅ {name}: Скилл {skill_num} используется при HP > {value}\n\n"
                    f"⚠️ Перезапусти бота чтобы применить!",
                    reply_markup=get_hp_thresholds_keyboard(profile)
                )
        except ValueError:
            await update.message.reply_text(
                f"❌ Введи число (например: 10000, 20000). 0 для удаления.",
                reply_markup=get_hp_thresholds_keyboard(profile)
            )

    # Обработка ввода для продажи ресурсов
    elif update.effective_user.id in waiting_for_sell_input:
        user_id = update.effective_user.id
        sell_data = waiting_for_sell_input.pop(user_id)
        profile = sell_data["profile"]
        resource = sell_data["resource"]
        input_type = sell_data["type"]  # "stack" or "reserve"
        name = PROFILE_NAMES.get(profile, profile)
        rus_name = RESOURCE_NAMES_RU.get(resource, resource)

        try:
            value = int(text)
            if value <= 0:
                raise ValueError("Должно быть > 0")

            if input_type == "stack":
                set_sell_stack(profile, resource, value)
                await update.message.reply_text(
                    f"✅ {name}: {rus_name} стак = {value}\n\n"
                    f"⚠️ Перезапусти бота чтобы применить!",
                    reply_markup=get_sell_resources_keyboard(profile)
                )
            else:  # reserve
                set_sell_reserve(profile, resource, value)
                await update.message.reply_text(
                    f"✅ {name}: {rus_name} резерв = {value}\n\n"
                    f"⚠️ Перезапусти бота чтобы применить!",
                    reply_markup=get_sell_resources_keyboard(profile)
                )
        except ValueError:
            await update.message.reply_text(
                f"❌ Введи целое число > 0",
                reply_markup=get_sell_resources_keyboard(profile)
            )

    # Обработка ввода кулдауна
    elif update.effective_user.id in waiting_for_cooldown:
        user_id = update.effective_user.id
        cd_data = waiting_for_cooldown.pop(user_id)
        profile = cd_data["profile"]
        skill_num = cd_data["skill"]
        name = PROFILE_NAMES.get(profile, profile)

        try:
            value = float(text.replace(",", "."))
            if value <= 0:
                raise ValueError("Должно быть > 0")

            set_cooldown(profile, skill_num, value)

            await update.message.reply_text(
                f"✅ {name}: Скилл {skill_num} = {value}с\n\n"
                f"⚠️ Перезапусти бота чтобы применить!",
                reply_markup=get_cooldowns_keyboard(profile)
            )
        except ValueError:
            await update.message.reply_text(
                f"❌ Неверный формат. Введи число (например: 15 или 45.5)",
                reply_markup=get_cooldowns_keyboard(profile)
            )

    elif waiting_for_ai_question.get(update.effective_user.id, False):
        # Пользователь написал вопрос для AI
        user_id = update.effective_user.id
        waiting_for_ai_question[user_id] = False

        await update.message.reply_text("🤖 Отправляю вопрос к Claude, подожди...")

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, ask_claude, text)

        if len(response) > 4000:
            response = response[:4000] + "..."
        await update.message.reply_text(f"🤖 Claude:\n\n{response}", reply_markup=get_main_keyboard())


# ============================================
# Уведомления (для вызова из других модулей)
# ============================================

_telegram_app: Optional[Application] = None
_chat_id: Optional[int] = None

async def send_notification(message: str):
    """Отправляет уведомление в Telegram"""
    global _telegram_app, _chat_id
    if _telegram_app and _chat_id:
        try:
            await _telegram_app.bot.send_message(chat_id=_chat_id, text=message)
        except Exception as e:
            print(f"[TELEGRAM] Ошибка отправки: {e}")

def notify_sync(message: str):
    """Синхронная отправка уведомления (для вызова из других модулей)"""
    if not BOT_TOKEN or not ALLOWED_USERS:
        return

    import requests
    try:
        for chat_id in ALLOWED_USERS:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=10)
    except Exception as e:
        print(f"[TELEGRAM] Ошибка отправки: {e}")


# ============================================
# Main
# ============================================

def main():
    global _telegram_app, _chat_id

    if not BOT_TOKEN:
        print("=" * 50)
        print("Telegram бот не настроен!")
        print("1. Создай бота через @BotFather")
        print("2. Получи токен")
        print("3. Создай telegram_config.json:")
        print(json.dumps({
            "bot_token": "YOUR_BOT_TOKEN",
            "allowed_users": [123456789]
        }, indent=2))
        print("=" * 50)

        # Создаём пример конфига
        if not os.path.exists(CONFIG_FILE):
            save_config({
                "bot_token": "YOUR_BOT_TOKEN_HERE",
                "allowed_users": []
            })
            print(f"Создан {CONFIG_FILE} - заполни его!")
        return

    print(f"[TELEGRAM] Запуск бота...")
    print(f"[TELEGRAM] Allowed users: {ALLOWED_USERS}")

    # Создаём приложение
    app = Application.builder().token(BOT_TOKEN).build()
    _telegram_app = app
    if ALLOWED_USERS:
        _chat_id = ALLOWED_USERS[0]

    # Регистрируем handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("start_bot", cmd_start_bot))
    app.add_handler(CommandHandler("stop_bot", cmd_stop_bot))
    app.add_handler(CommandHandler("restart_bot", cmd_restart_bot))
    app.add_handler(CommandHandler("stop_all", cmd_stop_all))
    app.add_handler(CommandHandler("restart_all", cmd_restart_all))
    app.add_handler(CommandHandler("pull", cmd_pull))
    app.add_handler(CommandHandler("craft", cmd_craft_set))
    app.add_handler(CommandHandler("cd", cmd_cooldown))
    app.add_handler(CallbackQueryHandler(callback_handler))
    # Обработчик текстовых кнопок
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_text))

    # Запуск
    print("[TELEGRAM] Бот запущен! Жду команды...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
