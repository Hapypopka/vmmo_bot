# ============================================
# Skill Cooldown Observer
# ============================================
# Наблюдает за скиллами и записывает реальные КД
# Измеряет время между использованиями одного скилла
# ============================================

import os
import sys
import json
import time
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests_bot.client import VMMOClient
from requests_bot.combat import CombatParser

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "skill_cd_log.json")
REPORT_FILE = os.path.join(SCRIPT_DIR, "skill_cd_report.txt")


class SkillCDObserver:
    """Наблюдает за кулдаунами скиллов"""

    def __init__(self, client: VMMOClient):
        self.client = client
        self.combat_url = None

        # Логирование КД - теперь записываем интервалы между использованиями
        self.skill_log = []  # [{pos, prev_use, curr_use, interval_sec}]
        self.last_use_time = {}  # {pos: timestamp} - время последнего использования

    def _make_ajax_request(self, url):
        """AJAX запрос для боя"""
        base_path = self.combat_url.split("?")[0].replace("https://vmmo.vten.ru", "") if self.combat_url else ""

        headers = {
            "Wicket-Ajax": "true",
            "Wicket-Ajax-BaseURL": base_path.lstrip("/"),
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml, text/xml, */*; q=0.01",
            "Referer": self.combat_url or self.client.current_url,
        }
        return self.client.session.get(url, headers=headers)

    def load_combat(self, url="/basin/combat"):
        """Загружает страницу боя"""
        resp = self.client.get(url)
        self.combat_url = resp.url
        return CombatParser(self.client.current_page, resp.url)

    def enter_hell_games(self):
        """Входит в Адские Игры"""
        print("[*] Entering Hell Games...")

        # 1. Переходим на страницу Адских Игр
        resp = self.client.get("/basin/combat")

        # Проверяем - может уже в бою?
        parser = CombatParser(self.client.current_page, resp.url)
        if parser.is_battle_active():
            print("[OK] Already in battle!")
            self.combat_url = resp.url
            return True

        # 2. Ищем кнопку входа (может быть лендинг)
        html = self.client.current_page

        # Паттерн для кнопки "Вступить в бой" или подобной
        enter_patterns = [
            r'href=["\']([^"\']*ppAction=combat[^"\']*)["\']',
            r'href=["\']([^"\']*enterCombat[^"\']*)["\']',
            r'href=["\']([^"\']*ILinkListener[^"\']*)["\'].*?(?:Вступить|Начать|Enter)',
        ]

        for pattern in enter_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                enter_url = match.group(1).replace("&amp;", "&")
                print(f"[*] Found enter button, clicking...")
                resp = self.client.get(enter_url)

                # Проверяем результат
                parser = CombatParser(self.client.current_page, resp.url)
                if parser.is_battle_active():
                    print("[OK] Entered Hell Games!")
                    self.combat_url = resp.url
                    return True

        # 3. Пробуем найти Wicket AJAX ссылку
        wicket_match = re.search(r'"u":"([^"]*(?:enterCombat|startCombat)[^"]*)"', html)
        if wicket_match:
            ajax_url = wicket_match.group(1)
            print(f"[*] Found Wicket enter link...")

            headers = {
                "Wicket-Ajax": "true",
                "Wicket-Ajax-BaseURL": "basin/combat",
                "X-Requested-With": "XMLHttpRequest",
            }
            resp = self.client.session.get(ajax_url, headers=headers)

            # Перезагружаем страницу
            resp = self.client.get("/basin/combat")
            parser = CombatParser(self.client.current_page, resp.url)
            if parser.is_battle_active():
                print("[OK] Entered Hell Games!")
                self.combat_url = resp.url
                return True

        print("[ERR] Could not enter Hell Games")
        return False

    def observe_loop(self, duration_minutes=10, check_interval=0.5):
        """
        Основной цикл наблюдения.

        Измеряет ИНТЕРВАЛ между использованиями одного скилла.
        Это точнее чем "когда заметили что готов".
        """
        print(f"\n{'='*60}")
        print(f"SKILL COOLDOWN OBSERVER v2")
        print(f"Measures interval between skill uses")
        print(f"Duration: {duration_minutes} minutes")
        print(f"{'='*60}\n")

        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)

        parser = self.load_combat()

        if not parser.is_battle_active():
            print("[!] No active battle, trying to enter Hell Games...")
            if not self.enter_hell_games():
                print("[ERR] Could not enter Hell Games!")
                return
            parser = CombatParser(self.client.current_page, self.combat_url)

        print("[OK] Battle active, starting observation...\n")

        action_count = 0
        last_status_time = 0
        no_units_count = 0

        while time.time() < end_time:
            # Обновляем парсер
            parser = CombatParser(self.client.current_page, self.client.current_url)

            if not parser.is_battle_active():
                print("[!] Battle ended, reloading...")
                parser = self.load_combat()
                if not parser.is_battle_active():
                    print("[ERR] No battle found")
                    break
                continue

            now = time.time()

            # Проверяем наличие врагов (Hell Games)
            units = parser.get_units_info()
            if not units:
                no_units_count += 1
                if no_units_count >= 3:
                    # Ищем вражеский источник (light)
                    enemy_idx, enemy_url = parser.find_enemy_source()
                    if enemy_url:
                        print(f"[!] No units, switching to enemy source {enemy_idx}...")
                        headers = {
                            "Wicket-Ajax": "true",
                            "Wicket-Ajax-BaseURL": "basin/combat",
                            "X-Requested-With": "XMLHttpRequest",
                        }
                        resp = self.client.session.get(enemy_url, headers=headers)
                        if resp.status_code == 200:
                            print(f"[SOURCE] Switched to source {enemy_idx}")
                            no_units_count = 0
                            self.client.get(self.combat_url)
                            time.sleep(1.0)
                    else:
                        # Все источники наши (dark) - просто ждём
                        sources_info = parser.get_sources_info()
                        light_count = sum(1 for s in sources_info if s["is_light"])
                        dark_count = sum(1 for s in sources_info if s["is_dark"])
                        print(f"[WAIT] No enemy sources (light={light_count}, dark={dark_count}), waiting...")
                        no_units_count = 0  # Сбрасываем чтобы не спамить
                        time.sleep(3.0)  # Ждём подольше
                time.sleep(check_interval)
                continue

            no_units_count = 0

            # Используем первый готовый скилл
            ready_skills = parser.get_ready_skills()
            skill_used = False

            for skill in ready_skills:
                pos = skill["pos"]
                # Используем скилл
                resp = self._make_ajax_request(skill["url"])
                if resp.status_code == 200:
                    use_time = time.time()
                    use_time_str = datetime.fromtimestamp(use_time).strftime("%H:%M:%S")

                    # Если это НЕ первое использование - записываем интервал
                    if pos in self.last_use_time:
                        prev_time = self.last_use_time[pos]
                        interval = use_time - prev_time
                        prev_time_str = datetime.fromtimestamp(prev_time).strftime("%H:%M:%S")

                        entry = {
                            "pos": pos,
                            "prev_use": prev_time_str,
                            "curr_use": use_time_str,
                            "interval_sec": round(interval, 2),
                        }
                        self.skill_log.append(entry)

                        print(f"[SKILL {pos}] {use_time_str} (interval: {interval:.1f}s)")
                    else:
                        print(f"[SKILL {pos}] {use_time_str} (first use)")

                    # Записываем время использования
                    self.last_use_time[pos] = use_time
                    action_count += 1
                    skill_used = True

                    # Обновляем страницу
                    self.client.get(self.combat_url)
                    time.sleep(2.0)  # GCD
                    break

            if skill_used:
                continue

            # Атакуем между скиллами
            attack_url = parser.get_attack_url()
            if attack_url:
                resp = self._make_ajax_request(attack_url)
                if resp.status_code == 200:
                    action_count += 1
                    self.client.get(self.combat_url)

            # Статус каждые 30 секунд
            if now - last_status_time > 30:
                elapsed = (now - start_time) / 60
                remaining = (end_time - now) / 60
                print(f"\n[STATUS] {elapsed:.1f}m elapsed, {remaining:.1f}m remaining")
                print(f"         Actions: {action_count}, Logged intervals: {len(self.skill_log)}\n")
                last_status_time = now

            time.sleep(check_interval)

        # Финальный отчёт
        self._save_and_report()

    def _save_and_report(self):
        """Сохраняет лог и выводит статистику"""
        report_lines = []

        def out(line=""):
            print(line)
            report_lines.append(line)

        out(f"\n{'='*60}")
        out("OBSERVATION COMPLETE")
        out(f"{'='*60}\n")

        if not self.skill_log:
            out("[!] No skill intervals were recorded")
            return

        # Сохраняем JSON лог
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.skill_log, f, indent=2, ensure_ascii=False)
        out(f"[OK] Log saved to: {LOG_FILE}\n")

        # Статистика по скиллам
        from collections import defaultdict
        stats = defaultdict(list)

        for entry in self.skill_log:
            stats[entry["pos"]].append(entry["interval_sec"])

        out("SKILL COOLDOWN STATISTICS (interval between uses):")
        out("-" * 50)

        skill_cds = {}
        for pos in sorted(stats.keys()):
            intervals = stats[pos]
            min_interval = min(intervals)
            avg_interval = sum(intervals) / len(intervals)
            max_interval = max(intervals)

            # Реальный КД ≈ минимальный интервал - GCD(2сек)
            estimated_cd = min_interval - 2.0

            skill_cds[pos] = round(estimated_cd)

            out(f"Skill {pos}:")
            out(f"  Samples:     {len(intervals)}")
            out(f"  Min interval: {min_interval:.1f}s")
            out(f"  Avg interval: {avg_interval:.1f}s")
            out(f"  Max interval: {max_interval:.1f}s")
            out(f"  Est. CD:      ~{estimated_cd:.0f}s (min - 2s GCD)")
            out(f"  All: {intervals}")
            out()

        # Рекомендации
        out("=" * 50)
        out("RECOMMENDED SKILL_CD values:")
        out("-" * 50)
        for pos, cd in sorted(skill_cds.items()):
            out(f"  Skill {pos}: {cd}s")

        out("\nFor run_dungeon.py:")
        out("SKILL_COOLDOWNS = {")
        for pos, cd in sorted(skill_cds.items()):
            out(f"    {pos}: {cd},")
        out("}")

        # Сохраняем отчёт в файл
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        print(f"\n[OK] Report saved to: {REPORT_FILE}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Observe skill cooldowns")
    parser.add_argument("--duration", "-d", type=int, default=10,
                        help="Observation duration in minutes (default: 10)")
    parser.add_argument("--interval", "-i", type=float, default=0.5,
                        help="Check interval in seconds (default: 0.5)")
    args = parser.parse_args()

    print("=" * 60)
    print("VMMO Skill Cooldown Observer v2")
    print("=" * 60)

    # Авторизуемся
    client = VMMOClient()
    client.load_cookies()

    if not client.is_logged_in():
        print("[*] Logging in...")
        if not client.login():
            print("[ERR] Login failed")
            return

    print("[OK] Logged in")

    # Запускаем наблюдение
    observer = SkillCDObserver(client)
    observer.observe_loop(duration_minutes=args.duration, check_interval=args.interval)


if __name__ == "__main__":
    main()
