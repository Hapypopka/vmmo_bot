# ============================================
# VMMO Requests Bot - Main Entry Point
# ============================================
# Экспериментальный бот на requests (без браузера)
# Тестирование боя в Адских Играх
# ============================================

import os
import sys
import time
import argparse

# Добавляем путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient
from requests_bot.combat import CombatClient, CombatParser


def log(msg):
    """Логирование с временем"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")


def run_hell_games(combat, max_attacks=100, delay=1.5):
    """Бой в Адских Играх"""
    log("Starting Hell Games fight loop...")

    attacks = 0
    skills_used = 0
    no_units_count = 0

    while attacks < max_attacks:
        parser = combat.parser

        if not parser or not parser.is_battle_active():
            log("Battle not active, reloading...")
            combat.load_combat_page("/basin/combat")
            parser = combat.parser
            if not parser.is_battle_active():
                log("Still no battle - exiting")
                break

        # Проверяем юнитов
        units = parser.get_units_info()
        if not units:
            no_units_count += 1
            if no_units_count >= 5:
                log("No units for 5 checks - looking for source...")
                # Переключаем источник
                sources = parser.get_source_urls()
                if sources:
                    # Ищем источник с врагами (light)
                    # Пока просто переключаем на следующий
                    for idx in sources:
                        success, msg = combat.switch_source(idx)
                        if success:
                            log(f"Switched to source {idx}")
                            no_units_count = 0
                            break
            time.sleep(delay)
            combat.load_combat_page("/basin/combat")
            continue

        no_units_count = 0

        # Используем скилл если есть готовый
        ready_skills = parser.get_ready_skills()
        if ready_skills:
            skill = ready_skills[0]
            success, msg = combat.use_skill(skill["pos"])
            if success:
                log(f"Skill {skill['pos']} used")
                skills_used += 1
                attacks += 1
                time.sleep(delay)
                continue

        # Атакуем
        success, msg = combat.attack()
        if success:
            attacks += 1
            if attacks % 10 == 0:
                log(f"Attacks: {attacks}, Skills: {skills_used}")
            time.sleep(delay)
        else:
            log(f"Attack error: {msg}")
            time.sleep(delay * 2)
            combat.load_combat_page("/basin/combat")

    log(f"Fight finished: {attacks} attacks, {skills_used} skills")
    return attacks, skills_used


def main():
    parser = argparse.ArgumentParser(description="VMMO Requests Bot")
    parser.add_argument("--attacks", type=int, default=50, help="Max attacks (default: 50)")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay between actions (default: 1.5)")
    parser.add_argument("--loop", action="store_true", help="Run in loop mode")
    args = parser.parse_args()

    print("=" * 50)
    print("VMMO Requests Bot v0.1")
    print("Experimental - requests only, no browser")
    print("=" * 50)

    # Авторизуемся
    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        log("Cookies expired, logging in...")
        if not client.login():
            log("Login failed!")
            return

    log("Logged in successfully")

    # Создаём боевой клиент
    combat = CombatClient(client)

    # Загружаем страницу боя
    log("Loading Hell Games...")
    combat.load_combat_page("/basin/combat")

    if not combat.parser.is_battle_active():
        log("No active battle found")
        log("Make sure you're in Hell Games (Playwright bot can enter)")
        return

    log("Battle active - starting fight!")

    if args.loop:
        # Бесконечный цикл
        total_attacks = 0
        total_skills = 0
        try:
            while True:
                attacks, skills = run_hell_games(combat, args.attacks, args.delay)
                total_attacks += attacks
                total_skills += skills
                log(f"Total: {total_attacks} attacks, {total_skills} skills")
                time.sleep(5)  # Пауза между циклами
        except KeyboardInterrupt:
            log("\nStopped by user")
            log(f"Final total: {total_attacks} attacks, {total_skills} skills")
    else:
        # Один цикл
        run_hell_games(combat, args.attacks, args.delay)


if __name__ == "__main__":
    main()
