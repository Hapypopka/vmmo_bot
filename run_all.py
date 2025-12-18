# ============================================
# VMMO Bot - Run All Profiles
# ============================================
# Запускает бота для всех профилей параллельно
# Usage: python run_all.py
# ============================================

import os
import sys
import subprocess
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")
BOT_SCRIPT = os.path.join(SCRIPT_DIR, "requests_bot", "bot.py")


def get_all_profiles():
    """Возвращает список всех профилей"""
    profiles = []
    if os.path.exists(PROFILES_DIR):
        for name in os.listdir(PROFILES_DIR):
            profile_path = os.path.join(PROFILES_DIR, name)
            config_path = os.path.join(profile_path, "config.json")
            if os.path.isdir(profile_path) and os.path.exists(config_path):
                profiles.append(name)
    return sorted(profiles)


def main():
    profiles = get_all_profiles()

    if not profiles:
        print("[ERROR] No profiles found in profiles/")
        return

    print(f"[*] Found {len(profiles)} profiles: {', '.join(profiles)}")
    print()

    processes = []

    for profile in profiles:
        print(f"[*] Starting bot for profile: {profile}")

        # Запускаем в новом процессе
        cmd = [sys.executable, BOT_SCRIPT, "--profile", profile]

        # На Windows создаём новое окно для каждого профиля
        if sys.platform == "win32":
            proc = subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            # На Linux запускаем в фоне
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

        processes.append((profile, proc))
        print(f"    PID: {proc.pid}")

        # Небольшая пауза между запусками
        time.sleep(2)

    print()
    print(f"[OK] Started {len(processes)} bots")
    print()
    print("Press Ctrl+C to stop all bots...")

    try:
        # Ждём завершения всех процессов
        for profile, proc in processes:
            proc.wait()
    except KeyboardInterrupt:
        print("\n[*] Stopping all bots...")
        for profile, proc in processes:
            proc.terminate()
        print("[OK] All bots stopped")


if __name__ == "__main__":
    main()
