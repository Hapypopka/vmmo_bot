# ============================================
# VMMO Bot - Statistics Module (requests version)
# ============================================

import json
import os
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")

# Текущий файл статистики (устанавливается через set_stats_profile)
_stats_file = None


def set_stats_profile(profile_name):
    """Устанавливает профиль для статистики"""
    global _stats_file
    if profile_name:
        profile_dir = os.path.join(PROFILES_DIR, profile_name)
        _stats_file = os.path.join(profile_dir, "stats.json")
    else:
        _stats_file = os.path.join(SCRIPT_DIR, "stats.json")


def get_stats_file():
    """Возвращает путь к файлу статистики"""
    global _stats_file
    if _stats_file is None:
        _stats_file = os.path.join(SCRIPT_DIR, "stats.json")
    return _stats_file


def load_stats():
    """Загружает статистику из файла"""
    stats_file = get_stats_file()
    if os.path.exists(stats_file):
        try:
            with open(stats_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Дефолтная структура
    return {
        "total_dungeons_completed": 0,
        "total_stages_completed": 0,
        "total_deaths": 0,
        "total_items_auctioned": 0,
        "total_items_disassembled": 0,
        "total_hell_games_time": 0,
        "total_mail_gold": 0,
        "total_mail_silver": 0,
        "dungeons": {},
        "sessions": [],
        "first_run": None,
        "last_run": None,
    }


def save_stats(stats):
    """Сохраняет статистику в файл"""
    stats_file = get_stats_file()
    try:
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[STATS] Ошибка сохранения: {e}")


class BotStats:
    """Класс для отслеживания статистики бота"""

    def __init__(self):
        self.stats = load_stats()
        self.session_start = datetime.now()
        self.session_dungeons = 0
        self.session_stages = 0
        self.session_deaths = 0
        self.session_actions = 0

        # Устанавливаем first_run если это первый запуск
        if self.stats["first_run"] is None:
            self.stats["first_run"] = self.session_start.isoformat()

        self.stats["last_run"] = self.session_start.isoformat()
        save_stats(self.stats)

    def dungeon_completed(self, dungeon_id, dungeon_name=None):
        """Записывает завершение данжена"""
        self.stats["total_dungeons_completed"] += 1
        self.session_dungeons += 1

        # Статистика по конкретному данжену
        if dungeon_id not in self.stats["dungeons"]:
            self.stats["dungeons"][dungeon_id] = {
                "name": dungeon_name or dungeon_id,
                "completed": 0,
                "deaths": 0,
                "last_completed": None,
            }

        self.stats["dungeons"][dungeon_id]["completed"] += 1
        self.stats["dungeons"][dungeon_id]["last_completed"] = datetime.now().isoformat()

        save_stats(self.stats)
        print(f"[STATS] Данжен пройден: {dungeon_name or dungeon_id}")

    def stage_completed(self):
        """Записывает завершение этапа"""
        self.stats["total_stages_completed"] += 1
        self.session_stages += 1
        save_stats(self.stats)

    def death_recorded(self, dungeon_id=None):
        """Записывает смерть"""
        self.stats["total_deaths"] += 1
        self.session_deaths += 1

        if dungeon_id and dungeon_id in self.stats["dungeons"]:
            self.stats["dungeons"][dungeon_id]["deaths"] += 1

        save_stats(self.stats)
        print(f"[STATS] Смерть записана")

    def items_auctioned(self, count):
        """Записывает выставленные на аукцион предметы"""
        self.stats["total_items_auctioned"] += count
        save_stats(self.stats)

    def items_disassembled(self, count):
        """Записывает разобранные предметы"""
        self.stats["total_items_disassembled"] += count
        save_stats(self.stats)

    def hell_games_time(self, seconds):
        """Записывает время в Адских Играх"""
        self.stats["total_hell_games_time"] += seconds
        save_stats(self.stats)

    def mail_money_collected(self, gold=0, silver=0):
        """Записывает деньги, собранные с почты"""
        self.stats["total_mail_gold"] += gold
        self.stats["total_mail_silver"] += silver
        save_stats(self.stats)

    def add_actions(self, count):
        """Добавляет действия"""
        self.session_actions += count

    def end_session(self):
        """Завершает сессию и записывает итоги"""
        session_end = datetime.now()
        session_duration = (session_end - self.session_start).total_seconds()

        session_record = {
            "start": self.session_start.isoformat(),
            "end": session_end.isoformat(),
            "duration_seconds": int(session_duration),
            "dungeons_completed": self.session_dungeons,
            "stages_completed": self.session_stages,
            "deaths": self.session_deaths,
            "actions": self.session_actions,
        }

        # Храним только последние 100 сессий
        self.stats["sessions"].append(session_record)
        if len(self.stats["sessions"]) > 100:
            self.stats["sessions"] = self.stats["sessions"][-100:]

        save_stats(self.stats)

    def get_summary(self):
        """Возвращает текстовую сводку статистики"""
        s = self.stats

        # Форматируем время в Адских Играх
        hell_hours = s["total_hell_games_time"] // 3600
        hell_mins = (s["total_hell_games_time"] % 3600) // 60

        lines = [
            "=" * 50,
            "СТАТИСТИКА БОТА",
            "=" * 50,
            f"Данженов пройдено: {s['total_dungeons_completed']}",
            f"Этапов пройдено: {s['total_stages_completed']}",
            f"Смертей: {s['total_deaths']}",
            f"Выставлено на аукцион: {s['total_items_auctioned']}",
            f"Разобрано предметов: {s['total_items_disassembled']}",
            f"Собрано с почты: {s['total_mail_gold']}g {s['total_mail_silver']}s",
            f"Время в Hell Games: {hell_hours}ч {hell_mins}м",
            "-" * 50,
        ]

        # Топ данженов
        if s["dungeons"]:
            lines.append("ТОП ДАНЖЕНОВ:")
            sorted_dungeons = sorted(
                s["dungeons"].items(),
                key=lambda x: x[1]["completed"],
                reverse=True
            )[:5]
            for dng_id, dng_stats in sorted_dungeons:
                name = dng_stats.get("name", dng_id)
                lines.append(f"   {name}: {dng_stats['completed']} (deaths: {dng_stats['deaths']})")

        lines.append("=" * 50)

        return "\n".join(lines)

    def get_session_summary(self):
        """Возвращает сводку текущей сессии"""
        duration = (datetime.now() - self.session_start).total_seconds()
        mins = int(duration // 60)
        secs = int(duration % 60)

        return (
            f"[SESSION] {self.session_dungeons} данженов, "
            f"{self.session_stages} этапов, "
            f"{self.session_deaths} смертей, "
            f"{self.session_actions} действий "
            f"({mins}м {secs}с)"
        )


# Глобальный экземпляр статистики
_bot_stats = None


def init_stats():
    """Инициализирует глобальную статистику"""
    global _bot_stats
    _bot_stats = BotStats()
    return _bot_stats


def get_stats():
    """Возвращает глобальную статистику"""
    global _bot_stats
    if _bot_stats is None:
        _bot_stats = BotStats()
    return _bot_stats


def print_stats():
    """Выводит статистику в консоль"""
    stats = get_stats()
    print(stats.get_summary())


if __name__ == "__main__":
    # Тест
    print_stats()
