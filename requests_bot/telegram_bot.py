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
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
except ImportError:
    print("Установи python-telegram-bot: pip install python-telegram-bot")
    sys.exit(1)

# Пути
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "telegram_config.json")

# Маппинг profile -> username (для отображения)
PROFILE_NAMES = {
    "char1": "nza",
    "char2": "Happypoq",
    "char3": "Arilyn"
}

# Обратный маппинг
USERNAME_TO_PROFILE = {v: k for k, v in PROFILE_NAMES.items()}

# Активные процессы ботов {profile: subprocess.Popen}
bot_processes: Dict[str, subprocess.Popen] = {}

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
    if profile in bot_processes:
        proc = bot_processes[profile]
        if proc.poll() is None:
            return "🟢 Работает"
        else:
            return "🔴 Остановлен (код: {})".format(proc.returncode)
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
    if profile not in bot_processes:
        return False, "Бот не запущен через менеджер"

    proc = bot_processes[profile]
    if proc.poll() is not None:
        del bot_processes[profile]
        return False, "Бот уже остановлен"

    try:
        proc.terminate()
        proc.wait(timeout=5)
        del bot_processes[profile]
        return True, f"Бот {PROFILE_NAMES.get(profile, profile)} остановлен"
    except subprocess.TimeoutExpired:
        proc.kill()
        del bot_processes[profile]
        return True, f"Бот {PROFILE_NAMES.get(profile, profile)} убит (kill)"
    except Exception as e:
        return False, f"Ошибка остановки: {e}"

def restart_bot(profile: str) -> tuple[bool, str]:
    """Перезапускает бота"""
    stop_bot(profile)
    return start_bot(profile)

def get_stats(profile: str) -> str:
    """Возвращает статистику бота"""
    # Статистика хранится в папке профиля
    stats_file = os.path.join(PROFILES_DIR, profile, "stats.json")

    if not os.path.exists(stats_file):
        return f"📊 {PROFILE_NAMES.get(profile, profile)}: нет данных"

    try:
        with open(stats_file, "r", encoding="utf-8") as f:
            stats = json.load(f)

        name = PROFILE_NAMES.get(profile, profile)

        # Форматируем время Hell Games
        hell_time = stats.get('total_hell_games_time', 0)
        hell_hours = hell_time // 3600
        hell_mins = (hell_time % 3600) // 60
        hell_str = f"{hell_hours}ч {hell_mins}м" if hell_time > 0 else "0"

        lines = [f"📊 Статистика {name}:"]
        lines.append(f"├ Данжей: {stats.get('total_dungeons_completed', 0)}")
        lines.append(f"├ Смертей: {stats.get('total_deaths', 0)}")
        lines.append(f"├ Этапов: {stats.get('total_stages_completed', 0)}")
        lines.append(f"├ Hell Games: {hell_str}")
        lines.append(f"├ Аукцион: {stats.get('total_items_auctioned', 0)}")
        lines.append(f"└ Разобрано: {stats.get('total_items_disassembled', 0)}")
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка чтения статистики: {e}"


def get_last_activity(profile: str) -> str:
    """Возвращает последнюю активность бота из лога"""
    log_dir = os.path.join(PROFILES_DIR, profile, "logs")
    name = PROFILE_NAMES.get(profile, profile)

    if not os.path.exists(log_dir):
        return f"📋 {name}: нет логов"

    # Находим последний лог файл
    log_files = [f for f in os.listdir(log_dir) if f.endswith('.log')]
    if not log_files:
        return f"📋 {name}: нет логов"

    log_files.sort(reverse=True)
    last_log = os.path.join(log_dir, log_files[0])

    try:
        # Читаем последние строки лога
        with open(last_log, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            return f"📋 {name}: лог пуст"

        # Берём последние 5 непустых строк
        recent_lines = [l.strip() for l in lines[-10:] if l.strip()][-5:]

        # Время модификации файла
        mtime = os.path.getmtime(last_log)
        last_modified = datetime.fromtimestamp(mtime)
        time_ago = datetime.now() - last_modified

        if time_ago.total_seconds() < 60:
            time_str = f"{int(time_ago.total_seconds())}с назад"
        elif time_ago.total_seconds() < 3600:
            time_str = f"{int(time_ago.total_seconds() // 60)}м назад"
        else:
            time_str = f"{int(time_ago.total_seconds() // 3600)}ч {int((time_ago.total_seconds() % 3600) // 60)}м назад"

        result = [f"📋 {name} (обновлён {time_str}):"]
        for line in recent_lines:
            # Обрезаем длинные строки
            if len(line) > 60:
                line = line[:57] + "..."
            result.append(f"  {line}")

        return "\n".join(result)
    except Exception as e:
        return f"📋 {name}: ошибка чтения ({e})"


# ============================================
# Telegram Handlers
# ============================================

def get_main_keyboard():
    """Возвращает главную клавиатуру"""
    keyboard = [
        [KeyboardButton("📡 Статус"), KeyboardButton("📊 Статистика"), KeyboardButton("📋 Логи")],
        [KeyboardButton("▶️ Запустить"), KeyboardButton("⏹️ Остановить"), KeyboardButton("🔄 Рестарт")],
        [KeyboardButton("📥 Pull"), KeyboardButton("🤖 AI Debug"), KeyboardButton("💬 Спросить AI")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# Режим ожидания вопроса для AI
waiting_for_ai_question: Dict[int, bool] = {}


def ask_claude(prompt: str) -> str:
    """Отправляет запрос к Claude локально"""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/root"
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"Ошибка: {result.stderr}"
    except subprocess.TimeoutExpired:
        return "Ошибка: таймаут запроса к Claude (2 мин)"
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

    # Stats
    if data.startswith("stats_"):
        profile = data[6:]
        if profile == "all":
            texts = [get_stats(p) for p in PROFILE_NAMES.keys()]
            await query.edit_message_text("\n\n".join(texts))
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

    elif text == "🤖 AI Debug":
        await cmd_ai_debug(update, context)

    elif text == "💬 Спросить AI":
        user_id = update.effective_user.id
        waiting_for_ai_question[user_id] = True
        await update.message.reply_text(
            "💬 Напиши свой вопрос для Claude:\n\n"
            "(Или нажми любую другую кнопку для отмены)"
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
    app.add_handler(CallbackQueryHandler(callback_handler))
    # Обработчик текстовых кнопок
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_text))

    # Запуск
    print("[TELEGRAM] Бот запущен! Жду команды...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
