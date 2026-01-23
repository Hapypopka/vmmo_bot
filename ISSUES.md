# VMMO Bot - Найденные проблемы и косяки

Файл для фиксации проблем при аудите кода. Разберём позже.

---

## config.py

### 1. [КРИТИЧНО] Хардкод `is_event_dungeon_enabled()` = False
**Строка:** 233-235
```python
def is_event_dungeon_enabled():
    # Временно отключён - ивент закончился
    return False
```
**Проблема:** Забыли убрать после ивента Сталкер. Функция игнорирует конфиг профиля.

### 2. [MINOR] Дублирование global в одной функции
**Строки:** 157 и 191
```python
global SKIP_DUNGEONS, DUNGEON_ACTION_LIMITS  # строка 157
global SKIP_DUNGEONS, ONLY_DUNGEONS         # строка 191
```
**Проблема:** SKIP_DUNGEONS объявляется global дважды. Работает, но некрасиво.

### 3. [MINOR] bare except глотает ошибки
**Строки:** 101, 136
```python
except:
    pass
```
**Проблема:** Молча глотает все ошибки, включая системные.

---

## client.py

### 4. [СРЕДНЕ] POST не обрабатывает "обновление сервера"
**Строки:** 111-122
```python
def post(self, url, **kwargs):
    resp = self.session.post(url, **kwargs)
    # Нет вызова _handle_server_update()!
```
**Проблема:** GET обрабатывает обновление сервера (ждёт), POST - нет. Может зависнуть или сломаться во время обновления.

### 5. [MINOR] Дублирование import re
**Строки:** 9 и 350
```python
import re  # Глобально вверху файла
...
def repair_equipment(self):
    import re  # Зачем повторно внутри функции?
```
**Проблема:** Бессмысленный повторный импорт.

### 6. [СРЕДНЕ] _repair_equipment_legacy() не работает
**Строки:** 463-464
```python
print(f"[REPAIR] Прочность {percent}%, но ремонт через legacy метод невозможен")
return False
```
**Проблема:** Фолбек метод ничего не делает, просто печатает и выходит. Если Vue API недоступен - ремонт не произойдёт.

### 7. [MINOR] bare except
**Строка:** 455
```python
except:
    print(f"[REPAIR] Не удалось распарсить процент: {percent_text}")
```

### 8. [MINOR] Хардкод таймаутов вместо config
**Строки:** 22-23
```python
SERVER_UPDATE_MAX_RETRIES = 30
SERVER_UPDATE_RETRY_DELAY = 10
```
**Проблема:** Должно быть в config.py для единообразия.

---

## bot.py

### 9. [СРЕДНЕ] Дублирование логики крафта
**Строки:** 566-628
```python
if craft_mode in ("bronze", "platinum"):
    log_debug(f"[CRAFT] Режим {craft_mode}, пропускаем дублирующую проверку")
else:
    # 60+ строк дублирующей логики для железа
```
**Проблема:** Огромный блок дублирует `do_iron_craft_step()`. Метод уже обрабатывает все режимы, но тут ещё раз руками.

### 10. [MINOR] Хардкод MIN_FIGHTS_LEFT
**Строка:** 182
```python
if fights <= 5:  # MIN_FIGHTS_LEFT из arena.py
```
**Проблема:** Комментарий ссылается на arena.py, но значение захардкожено в bot.py.

### 11. [MINOR] TODO остался в коде
**Строка:** 440-441
```python
# TODO: улучшить - пока возвращаем фиксированное время
return 600, "Unknown"  # 10 минут по умолчанию
```
**Проблема:** Реальный КД не парсится, всегда 600 сек.

### 12. [MINOR] bare except (множество)
**Строки:** 73, 839, 930, 996
```python
except:
    pass
```
**Проблема:** Молчаливое подавление всех ошибок.

### 13. [MINOR] telegram_notify заглушка без лога
**Строки:** 52-55
```python
except ImportError:
    telegram_notify = lambda msg: None
```
**Проблема:** Если модуль недоступен - молча игнорирует все уведомления без лога.

---

## run_dungeon.py

### 14. [MINOR] Debug код в продакшене
**Строки:** 173-179
```python
DungeonRunner._ajax_debug_count += 1
if DungeonRunner._ajax_debug_count <= 3:
    debug_path = os.path.join(SCRIPT_DIR, f"debug_ajax_{DungeonRunner._ajax_debug_count}.xml")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(ajax_text)
```
**Проблема:** Всегда записывает первые 3 AJAX ответа в файлы. Мусорит на диске.

### 15. [MINOR] Дефолтные КД скиллов захардкожены
**Строки:** 893-899
```python
SKILL_CDS = {
    1: 15.5, 2: 24.5, 3: 39.5, 4: 54.5, 5: 42.5,
}
```
**Проблема:** Должно быть в config.py для единообразия и удобства изменения.

### 16. [MINOR] Магические числа без констант
**Строки:** 882-884, 1023, 1029
```python
GCD = 2.0              # Глобальный КД
ATTACK_CD = 0.6        # Задержка атак
consecutive_no_units >= 40  # Watchdog порог
```
**Проблема:** Локальные константы вместо config.py.

### 17. [MINOR] bare except
**Строки:** 103-105, 802
```python
except:
    html = None
```

---

## combat.py

**Чистый файл!** Проблем не обнаружено.

---

## event_dungeon.py

### 18. [СРЕДНЕ] Три клиента с дублированием логики
**Классы:** EventDungeonClient, NYEventDungeonClient, GenericEventDungeonClient
```python
class EventDungeonClient:      # Старый Сталкер
class NYEventDungeonClient:    # NY ивент
class GenericEventDungeonClient:  # Универсальный
```
**Проблема:** Логика `enter_dungeon()` почти одинаковая во всех трёх. `GenericEventDungeonClient` должен был заменить остальные, но они остались. Код раздут ~3x.

### 19. [MINOR] Три разных механизма кэширования КД
**Строки:** 27-28, 63
```python
_event_cooldown_until = 0      # Старый Сталкер
_ny_event_cooldown_until = 0   # NY ивент
_event_cooldowns = {}          # Generic (dict)
```
**Проблема:** Несогласованность. Должен быть один dict.

### 20. [MINOR] Хардкод дефолтного КД 1800 в нескольких местах
**Строки:** 405, 452, 455, 654, 672, 708
```python
_ny_event_cooldown_until = now + 1800  # 30 мин
_event_cooldowns[self.dungeon_key] = now + 1800
return True, 1800
```
**Проблема:** Магическое число 1800 (30 мин) повторяется 6 раз. Должна быть константа.

### 21. [MINOR] Debug файл в продакшене
**Строки:** 648-652
```python
debug_path = os.path.join(SCRIPT_DIR, "debug_dungeons_page.html")
if not os.path.exists(debug_path):
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(html)
```

---

## backpack.py

**Относительно чистый файл.**

### 22. [MINOR] Магические числа в циклах
**Строки:** 346, 385, 435, 476
```python
for _ in range(50):  # Защита от бесконечного цикла
for _ in range(100):  # Защита
```
**Проблема:** Должны быть константы типа MAX_BACKPACK_ITERATIONS.

---

## auction.py

**Относительно чистый файл.**

### 23. [MINOR] Дублирование логики разборки
**Строки:** 301-317 и 321-337
```python
# Два почти идентичных блока разборки вместо:
self.backpack.disassemble_item(item)
```
**Проблема:** Копипаста логики разборки. Метод `disassemble_item()` уже есть в backpack.py.

---

## telegram_bot.py

**Относительно чистый файл** (3003 строки) - хорошо структурирован.

### 24. [MINOR] Много глобальных словарей для состояний
**Строки:** 110-116
```python
waiting_for_protected_item = {}
waiting_for_cooldown = {}
waiting_for_hp_threshold = {}
waiting_for_number_input = {}
waiting_for_sell_input = {}
waiting_for_ai_question = {}
new_user_state = {}
```
**Проблема:** 7 словарей для tracking user input. Работает, но можно объединить в один dataclass.

### 25. [MINOR] bare except при парсинге delta
**Строка:** 2355
```python
try:
    delta = int(delta_str)
except:
    delta = 0
```

---

## web_panel.py

**Относительно чистый файл** (1173 строки).

### 26. [MINOR] Хардкод secret_key
**Строка:** 30
```python
app.secret_key = "vmmo_bot_secret_key_change_me"
```
**Проблема:** Потенциальная проблема безопасности.

### 27. [MINOR] Пароль в открытом виде
**Строка:** 34
```python
PANEL_PASSWORD = "1616"
```
**Проблема:** Пароль также выводится в консоль при запуске (строка 1170).

### 28. [MINOR] bare except (множество)
**Строки:** 312, 369-370, 373, 415, 474, 584
```python
except:
    pass
```

### 29. [СРЕДНЕ] PROFILE_NAMES рассинхронизированы
**web_panel.py строки 56-63 vs telegram_bot.py**
- web_panel: char3=Arilyn, char5=Хеппипопка, char6=Faizka
- telegram_bot: char3=Lovelioness, char5=Fireglass, char6=Diverion

**Примечание:** web_panel использует `reload_profiles()` из файлов, так что это может быть OK.

---

## hell_games.py

**Относительно чистый файл** (527 строк).

### 30. [MINOR] Дублирование DEFAULT_SKILL_CDS
**Строки:** 15-21
```python
DEFAULT_SKILL_CDS = {
    1: 15.5, 2: 24.5, 3: 39.5, 4: 54.5, 5: 42.5,
}
```
**Проблема:** Те же значения что в run_dungeon.py. Должно быть в config.py.

---

## arena.py

**Хорошо структурированный файл** (709 строк) с документацией.

### 31. [MINOR] Debug файлы в продакшене
**Строки:** 90, 117, 309, 532
```python
with open("arena_debug.html", "w", encoding="utf-8") as f:
    f.write(html)
```
**Проблема:** Записывает debug файлы при каждой ошибке.

---

## survival_mines.py

**Относительно чистый файл** (512 строк).

### 32. [MINOR] Дублирование import re внутри функции
**Строки:** 47-48
```python
def get_character_level(self):
    ...
    import re  # Уже импортирован глобально в строке 7
```

### 33. [MINOR] Debug файл в продакшене
**Строки:** 188-196
```python
debug_path = os.path.join(..., "debug_mines_lobby.html")
with open(debug_path, "w", encoding="utf-8") as f:
    f.write(self.client.current_page or "")
```

---

## iron_craft.py

**Большой, но структурированный файл** (1150 строк).

### 34. [MINOR] Дублирование ITEM_NAMES, RECIPES
**Строки:** 29-40, 44-102
**Проблема:** Эти константы используются только в iron_craft.py, но могли бы быть в config.py для единообразия.

---

## sell_resources.py

**Чистый файл** (448 строк).

### 35. [MINOR] Хардкод пути кэша цен
**Строка:** 26
```python
PRICE_CACHE_FILE = "/home/claude/vmmo_bot/price_cache.json"
```
**Проблема:** Абсолютный путь Linux. Не работает локально на Windows.

---

## resources.py

**Чистый файл** (297 строк) - без явных проблем.

---

## Статистика

| Уровень | Количество |
|---------|------------|
| КРИТИЧНО | 1 |
| СРЕДНЕ | 5 |
| MINOR | 30 |

---

*Последнее обновление: полный аудит всех файлов*
