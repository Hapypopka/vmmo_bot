# VMMO Bot - Контекст разработки

## Обзор проекта
Бот для автоматизации игры VMMO (vmmo.vten.ru). Использует Playwright для управления браузером.

## Структура файлов

### Основные модули:
- **main.py** — точка входа, основной цикл бота
- **combat.py** — боевая логика (атака, скиллы, Адские Игры)
- **dungeon.py** — управление подземельями (вход, выход, переходы)
- **backpack.py** — работа с рюкзаком (аукцион, разбор, бонусы, крафт)
- **config.py** — конфигурация (URL, селекторы, настройки)
- **dungeon_config.py** — конфигурация подземелий
- **utils.py** — утилиты (задержки, логирование, клики)
- **navigation.py** — навигация и определение локации
- **popups.py** — закрытие попапов
- **stats.py** — статистика сессии
- **event_dungeon.py** — ивентовое подземелье "Сталкер Адского Кладбища"
- **mail.py** — проверка и сбор почты
- **api_client.py** — API клиент для КД (не в git, тестируется)

## Последние изменения (2025-12-10)

### 1. Защита железа (backpack.py)
- `PROTECTED_ITEMS = ["Железо", "Железная Руда"]`
- Функция `is_protected_item()` проверяет защищённые предметы
- `find_item_with_auction_button()` — пропускает защищённые
- `disassemble_or_drop_item()` — не трогает защищённые
- **Коммит:** `6f244c6`

### 2. Автоповтор крафта (backpack.py)
- `check_craft_ready(page)` — ищет блок "Готово" + кнопка "Повторить"
- `repeat_craft_if_ready(page)` — нажимает "Повторить" если крафт готов
- Проверка: если "Готово" есть, но кнопки "Повторить" нет — пропускает
- Вызывается в `main.py:172` при старте и в `dungeon.py:317` после каждого данжена
- **Коммит:** `6f244c6`

### 3. Shadow Guard — умираем на боссе (popups.py)
- Закомментирован вызов `check_shadow_guard_tutorial()` в `priority_checks()`
- Теперь бот НЕ выходит при "Голос Джека" — бьётся до смерти
- **Коммит:** `f775fd8`

### 4. Оптимизация памяти Chromium (main.py) — НЕ ЗАПУШЕНО
- Добавлены безопасные флаги для экономии памяти (строки 125-131):
  - `--js-flags=--max-old-space-size=256`
  - `--disable-logging`
  - `--disable-breakpad`
  - `--disable-component-update`
  - `--disable-client-side-phishing-detection`
  - `--disable-hang-monitor`

### 5. API Client (api_client.py) — НЕ ЗАПУШЕНО
- Request-based проверка КД данженов без браузера
- Использует `section_id` параметр (не `section`)
- API URL: `section_id=2` для tab2 (9 данженов на lvl 29)
- Структура ответа: `data.section.dungeons`
- Возвращает КД в миллисекундах

## Git

- **Репо:** https://github.com/Hapypopka/vmmo_bot.git
- **Ветка:** main
- **Последние коммиты:**
  - `f775fd8` — Shadow Guard: умираем на боссе
  - `6f244c6` — Защита железа + автоповтор крафта
  - `b0cf1cc` — Bot stuck detection, dungeon entry improvements

## Проблемы и решения

### Память 1GB на сервере
**Варианты решения:**
1. **Swap файл** (рекомендую первым):
   ```bash
   sudo fallocate -l 1G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```
2. undetected-chromedriver (меньше памяти ~400-500MB)
3. DrissionPage (гибрид requests + браузер)
4. VPS с 2GB RAM

### Wicket stateful URLs (почему нельзя полностью на requests)
- Бой через requests невозможен — URL типа `257-1.IBehaviorListener.0-attackLink` меняется каждый раз
- Page ID генерируется при каждой загрузке страницы
- Без JS нельзя узнать новый ID
- **Вывод:** Гибридный подход — requests для КД/аукциона, Playwright для боя

### Что можно через requests:
- ✅ Логин
- ✅ Проверка КД данженов
- ⚠️ Аукцион (нужен form action из HTML)
- ⚠️ Крафт
- ❌ Бой (атака, скиллы)
- ❌ Вход в данжен

## Команды сервера

```bash
# Запуск бота в screen
screen -S bot
xvfb-run python3 main.py --server

# Отключиться от screen (бот продолжит работать)
Ctrl+A, D

# Вернуться к боту
screen -r bot

# Убить зависший Xvfb
pkill -9 Xvfb
rm -f /tmp/.X99-lock
```

## Ключевые селекторы

### Аукцион:
- Предупреждение о низкой цене: `span.feedbackPanelERROR`
- Поля цены: `input[name='bidGold']`, `input[name='bidSilver']`

### Крафт:
- Блок крафта: `div.info-box`
- Текст "Готово" в блоке
- Кнопка "Повторить": `a.go-btn` с текстом "Повторить"

### Shadow Guard:
- Туториал: `div.battlefield-lore-inner` с текстом "голос джека"
- Кнопка выхода: `a.go-btn span.go-btn-in` с текстом "Покинуть банду"

## Настройки (settings.json)

```json
{
  "backpack_threshold": 15,
  "max_no_units": 5,
  "restart_interval": 7200,
  "start_dungeon_index": 0
}
```

## Запуск

### Windows (локально):
```bash
python main.py
```

### Linux сервер:
```bash
xvfb-run python3 main.py --server
```

### Аргументы:
- `--headless` — без GUI
- `--server` — режим сервера (headless + Chromium + без клавиатуры)
- `--chromium` — использовать Chromium вместо Firefox

---

## АРХИТЕКТУРА: Решение проблемы застреваний (TODO)

### Текущие механизмы защиты (разрозненные)

| Механизм | Файл | Как работает | Проблема |
|----------|------|--------------|----------|
| Watchdog | `utils.py:62` | 120 сек без `reset_watchdog()` → `emergency_unstuck()` | Сбрасывается при любой активности |
| no_units_attempts | `main.py:333` | 5 раз нет врагов → `smart_recovery()` | Только для боя |
| consecutive_attacks | `main.py:315` | 60 атак без смены статуса → `emergency_unstuck()` | Только для боя |
| emergency_unstuck | `popups.py:222` | Ищет кнопки, потом `goto(/dungeons)` | Может не найти кнопку |

### Проблема
Бот не понимает **где он находится**. Механизмы работают реактивно — ждут пока что-то пойдёт не так.

### Предлагаемое решение: Progress Tracker

**Идея:** отслеживать не "активность", а **реальный прогресс**:
```
Прогресс = изменение состояния игры:
- HP врага уменьшился
- Юнит исчез (убит)
- Появился лут
- URL изменился
- Появилась новая кнопка
- Пройден этап данжена
```

**Если за 2-3 минуты НИЧЕГО не изменилось → hard reset на /dungeons**

### Нюансы для учёта

| Ситуация | Почему простой таймер не работает |
|----------|-----------------------------------|
| Долгий бой в данже | Враг HP много, бой 2-3 мин норма → но HP меняется = прогресс |
| Адские Игры | Ждём КД 15-30 мин → но переходим между источниками = прогресс |
| Ждём группу | Виджет может не появиться → таймаут на ожидание |
| Сервер лагает | Страница грузится долго → отслеживать загрузку |
| Shadow Guard | Другая механика → учитывать в detect_state |

### Реализация (план)

1. **Новый файл `state.py`** — State Machine
```python
class GameState(Enum):
    DUNGEONS_LIST = "dungeons_list"      # Список данженов
    DUNGEON_WIDGET = "dungeon_widget"    # Виджет "В подземелье!"
    DUNGEON_LOBBY = "dungeon_lobby"      # Лобби перед боем
    IN_BATTLE = "in_battle"              # Активный бой
    STAGE_COMPLETE = "stage_complete"    # Этап пройден
    DUNGEON_COMPLETE = "dungeon_complete"# Данжен завершён
    HELL_GAMES = "hell_games"            # Адские Игры
    DEAD = "dead"                        # Погибли
    UNKNOWN = "unknown"                  # Неизвестно
```

2. **Функция `detect_state(page)`** — определяет состояние по HTML
3. **Функция `check_progress(page)`** — проверяет изменения
4. **Таймер на отсутствие прогресса** — 2-3 мин без изменений = reset

### HTML-маркеры состояний (собрано с сайта)

```python
# Виджет "В подземелье"
div.widget с кнопкой "В подземелье!" → DUNGEON_WIDGET

# Бой
#ptx_combat_rich2_attack_link → IN_BATTLE
div.battlefield-modal._fail → DEAD

# Завершение
h2 с "Этап пройден" → STAGE_COMPLETE
h2 с "Подземелье пройдено" или URL dungeoncompleted → DUNGEON_COMPLETE

# Адские Игры
URL /basin/combat → HELL_GAMES
```

### Статус: НЕ РЕАЛИЗОВАНО
Нужно собрать больше случаев застреваний для полной картины.

---

## Детали реализации

### Основной цикл (main.py)

**Порядок запуска:**
1. Авторизация (cookies.json или login/password из settings.json)
2. **Ивент "Сталкер"** — ПЕРВЫЙ приоритет! (`try_event_dungeon()`)
3. Рюкзак, почта, крафт
4. Поиск данжена или Адские Игры
5. Основной цикл боя

**Счётчики защиты:**
```python
no_units_attempts = 0      # 5 попыток без юнитов → smart_recovery()
consecutive_attacks = 0    # 240 атак без прогресса → emergency_unstuck()
enter_failure_count = 0    # Счётчик неудачных входов в данжен
```

**Watchdog цикл (защита от бесконечного цикла):**
- `increment_watchdog_cycle()` — увеличивает счётчик срабатываний
- `get_watchdog_cycle_count()` — текущее количество
- `reset_watchdog_cycle()` — сброс после успешного действия
- **5 срабатываний watchdog подряд → HARD RESET на /dungeons** (без попыток нажать кнопки)

**Прогресс (сброс consecutive_attacks):**
- Лут собран (`loot_collected > 0`)
- Этап пройден (`stage_complete`)
- Данжен завершён (`dungeon_complete`)

**Управление (только Windows, не --server):**
- P — пауза/продолжение
- S — показать статистику

### Боевая система (combat.py)

**Скиллы:**
```python
# Позиции 1-5
wrapper = f".wrap-skill-link._skill-pos-{pos}"
timer = wrapper.query_selector(".time-counter")
# Если timer не пустой и != "00:00" → скилл на КД
```

**Печать Сталкера (ивент):**
```python
# Триггер: текст на странице
"применить Печать Сталкера" in page_text

# Кнопка
".wrap-device-link._device-pos-1"

# Проверка freeze
"_freeze" in wrapper_class  # = печать заморожена, ждём
```

**Проверка статуса данжена:**
```python
"dungeoncompleted" in URL → "dungeon_complete"
h2 с "этап" + "пройден" → "stage_complete"
h2 с "подземелье" + "пройден/зачищен" → "dungeon_complete"
```

**Смерть:**
```python
# Селектор модалки смерти
"div.battlefield-modal._fail"

# Последовательность выхода:
1. "Покинуть бой" (span.button-text в модалке)
2. "Покинуть банду" (span.go-btn-in)
3. goto(DUNGEONS_URL)
```

### Адские Игры (combat.py)

**Источники:**
```python
sources = page.query_selector_all("a.source-link")
# Классы:
# _side-light = вражеский
# _side-dark = наш
# _current = текущий
# _lock = заблокирован
```

**Хранитель:**
```python
# Позиция 22
"div.unit._unit-pos-22 div.unit-show._keeper"

# Враги на позициях 21-25
for pos in range(21, 26):
    page.query_selector(f"div.unit._unit-pos-{pos}")
```

**Логика боя:**
1. Ищем light источник (вражеский) → переходим
2. Кликаем на хранителя (pos-22) → бьём со скиллами
3. Когда хранитель убит → ищем следующий light
4. Когда все dark (наши) → атакуем без скиллов, ждём врага

**Пропуск скиллов:**
- `HELL_GAMES_SKIP_SKILLS` в config.py — список позиций (например Талисман Доблести)

### Управление подземельями (dungeon.py)

**Виджет "В подземелье" (блокирует клики!):**
```python
# Счётчик попыток
_widget_enter_attempts = 0
MAX_WIDGET_ENTER_ATTEMPTS = 3  # После 3 попыток — принудительно покидаем банду

# clear_blocking_widget(page) возвращает:
# - True — виджет убран или его не было
# - "started_battle" — бой начат через виджет
```

**Логика clear_blocking_widget:**
1. Ищет `div.widget` с текстом "В подземелье"
2. Пробует войти (кнопка "В подземелье!")
3. Проверяет появился ли "Начать бой!" → нажимает
4. Проверяет юнитов — если нет, инстанс багнутый
5. При неудаче — покидает банду через /dungeons
6. После MAX попыток — принудительно покидает банду

**Детекция "уже прошёл подземелье":**
```python
# Попап notice-rich3
notice_text содержит "уже прошла" или "не может идти"
→ переходим в /dungeons для выхода из банды
```

**Проверка КД данжена:**
```python
selector = f'div[title="{dungeon_id}"]'
cooldown_icon = dungeon_div.query_selector("[class*='dungeon-cooldown']")
# КД время в span.map-item-name
```

**Вход в данжен (enter_dungeon):**
1. Проверяем виджет (clear_blocking_widget)
2. Проверяем локацию (detect_location) — может уже на лендинге
3. Кликаем на данжен `div[title="{dungeon_id}"]`
4. Повышаем сложность если `need_difficulty` в конфиге
5. Ищем "Войти" (точно) → fallback "В подземелье"
6. Ждём "Начать бой!" (`span.go-btn-in._font-art`)
7. Сбрасываем `reset_widget_attempts()` при успехе

**go_to_next_dungeon — порядок действий:**
1. Если на DungeonCompletedPage → нажать "Продолжить"
2. Вернуться в /dungeons
3. Проверить рюкзак
4. Проверить крафт
5. **Проверить ивент "Сталкер"** (приоритет!)
6. Искать следующий данжен
7. Если все на КД → Адские Игры → повторить поиск

**find_next_available_dungeon возвращает:**
- `int` — индекс доступного данжена
- `"started_battle"` — бой начат через виджет
- `None` — все на КД

### Ивент "Сталкер" (event_dungeon.py)

**Селекторы:**
```python
EVENT_WIDGET_SELECTOR = 'a.city-menu-l-link[href*="HellStalker"]'  # Виджет в городе
EVENT_DUNGEON_SELECTOR = 'a.event-map-widget[href*="EventCemetery"]'  # Перевал Мертвецов
STALKER_SEAL_SELECTOR = 'a.iSuperior[href*="item"]:has-text("Печать Сталкера")'
TIKUAN_CRYSTAL_SELECTOR = 'a.iGood[href*="item"]:has-text("Треснутый Кристалл Тикуана")'
```

**Логика try_event_dungeon:**
1. Проверяем доступность ивента (`check_event_available`) — ищем виджет в городе
2. Надеваем Печать Сталкера (`equip_stalker_seal`)
3. Входим в ивент (`enter_event_dungeon`)
4. Если на КД — надеваем Кристалл Тикуана для обычных данженов

**Проверка КД ивента:**
```python
# Текст на странице
"Ты сможешь войти через" in page_text → на КД
```

**try_event_dungeon возвращает:**
- `"entered"` — успешно вошли в бой
- `"on_cooldown"` — ивент на КД (Кристалл Тикуана надет)
- `"not_available"` — ивент не активен
- `"error"` — ошибка

**equip_item логика:**
1. Переход в рюкзак `/user/rack`
2. Поиск предмета по селектору
3. Клик → меню → кнопка "Надеть"
4. Если не найден — считаем что уже надет

### Попапы и аварийный выход (popups.py)

**close_all_popups — закрывает:**
- Достижения (`POPUP_CLOSE_SELECTOR`)
- Виджет приглашения ("приглашает", "ожидает", "ждёт")
- Бонус отдыха (`REST_BONUS_POPUP_SELECTOR`)
- "Банда собрана" → нажимает "В подземелье"

**priority_checks — приоритеты:**
1. ~~Shadow Guard (отключено)~~ — теперь умираем на боссе
2. "Начать бой" — если в лобби данжена
3. "Покинуть банду" — ТОЛЬКО виджет приглашения от другого игрока

**emergency_unstuck — последовательность:**
1. Попробовать закрыть попап (крестик)
2. Искать кнопки по тексту (приоритет):
   - "Продолжить бой"
   - "Продолжить"
   - "В подземелье"
   - "Начать бой"
   - "Закрыть"
   - "Выйти"
   - "Назад"
3. Нажать любую видимую `a.go-btn` (кроме опасных: удалить, купить, продать, отмена)
4. **Hard reset на /dungeons** если ничего не помогло

**collect_loot:**
- Селектор: `COMBAT_LOOT_SELECTOR`
- Кликает на все элементы лута
- Возвращает количество собранного

### Навигация (navigation.py)

**detect_location возвращает:**
- `"main"` — город (/city, /main)
- `"dungeons"` — список данженов (/dungeons)
- `"dungeon_landing"` — лендинг данжена (описание + "Войти")
- `"battle"` — активный бой (/combat, /battle)
- `"backpack"` — рюкзак (/rack)
- `"auction"` — аукцион (/auction, /market)
- `"hell_games"` — Адские Игры (/basin/combat)
- `"unknown"` — неизвестно

**Селекторы локаций:**
```python
# Лендинг данжена
"div.wrap-dungeon-lobby" или "div.dungeon-intro"

# Бой
".battlefield-controls" или "#ptx_combat_rich2_attack_link"

# Рюкзак
"div.rack-items"
```

**smart_recovery(page, context) возвращает:**
- `"continue_battle"` — продолжить бой
- `"find_dungeon"` — искать данжен
- `"enter_dungeon"` — входить в данжен
- `"retry"` — повторить

**smart_recovery логика:**
1. Закрыть попапы
2. Проверить виджет "Банда собрана"
3. Определить локацию
4. В зависимости от локации:
   - dungeons → find_dungeon
   - dungeon_landing → войти или закрыть → find_dungeon
   - battle → continue_battle
   - hell_games → вернуться → find_dungeon
   - другое → recover_to_dungeons

**handle_dungeon_landing возвращает:**
- `"entered"` — нажали "Войти"
- `"closed"` — закрыли лендинг (кнопка `a.dungeon-intro-lock`)
- `"failed"` — не удалось

### Утилиты (utils.py)

**Watchdog система:**
```python
WATCHDOG_TIMEOUT = 90  # секунд без активности = застревание
WATCHDOG_CYCLE_THRESHOLD = 5  # срабатываний подряд = hard reset

reset_watchdog()           # Сбросить таймер + счётчик циклов
is_watchdog_triggered()    # True если 90+ сек простоя
get_watchdog_idle_time()   # Время простоя в секундах
increment_watchdog_cycle() # +1 к счётчику, True если >= 5
get_watchdog_cycle_count() # Текущий счётчик
reset_watchdog_cycle()     # Сбросить только счётчик циклов
```

**Логирование:**
```python
LOG_DIR = "logs/"  # Папка для логов
init_logging()     # Создать лог-файл bot_YYYY-MM-DD_HH-MM-SS.log
log(message)       # Вывод + запись в файл
write_log(message) # Только запись в файл
log_error(message, page)  # Логирует + скриншот (если включено)
```

**Скриншоты (по умолчанию ВЫКЛЮЧЕНЫ):**
```python
# settings.json: "save_screenshots": true
save_debug_screenshot(page, reason)  # Сохраняет в logs/screenshot_{reason}_{timestamp}.png
```

**parse_cooldown_time — парсинг КД:**
```python
"14м 30с" → 870 секунд
"2ч 33м"  → 9180 секунд
"59м 32с" → 3572 секунд
```

**safe_click / safe_click_element:**
- Используют `dispatch_event("click")` — работает без фокуса окна
- Возвращают True/False

### Конфигурация (config.py)

**URLs:**
```python
BASE_URL = "https://vmmo.vten.ru"
CITY_URL = f"{BASE_URL}/city"
DUNGEONS_URL = f"{BASE_URL}/dungeons?52"  # ?52 — tab для lvl 29
HELL_GAMES_URL = f"{BASE_URL}/basin/combat"
LOGIN_URL = f"{BASE_URL}/login"
```

**Настройки из settings.json:**
```python
BACKPACK_THRESHOLD = 15   # Порог очистки рюкзака
MAX_NO_UNITS_ATTEMPTS = 5 # Попыток без юнитов до smart_recovery
RESTART_INTERVAL = 7200   # Перезапуск сессии (секунды)
MAX_ENTER_FAILURES = 2    # Ошибок входа до force_refresh
```

**Ключевые селекторы:**
```python
ATTACK_SELECTOR = "#ptx_combat_rich2_attack_link"
DUNGEONS_BUTTON_SELECTOR = 'a.btn.nav-btn[href*="dungeons"]'
BACKPACK_LINK_SELECTOR = 'a.main-menu-link._rack[title="Рюкзак"]'
POPUP_CLOSE_SELECTOR = 'a.popup-close-link'
WIDGET_LEAVE_PARTY_SELECTOR = 'div.widget a.go-btn[href*="leaveParty"]'
COMBAT_LOOT_SELECTOR = 'div.combat-loot'
```

**Юниты (позиции 21-25):**
```python
UNIT_SELECTORS = [".unit._unit-pos-21", ... ".unit._unit-pos-25"]
```

**Скиллы:**
```python
SKILLS = {1: "Талисман Доблести", 2: "Гром и Молния", ...}
HELL_GAMES_SKIP_SKILLS = [1]  # Не использовать в Адских Играх
```

### Рюкзак и аукцион (backpack.py)

**Защищённые предметы (PROTECTED_ITEMS):**
- Железо, Железная Руда, Железный Слиток
- Осколки (Грёз, Порядка, Рассвета, Ночи, Тени, Хаоса)
- Треснутый Кристалл Тикуана
- Печать Сталкера (I, II, III)

**Чёрный список аукциона:**
- Файл: `auction_blacklist.json`
- Предметы которые не продались → разбираются вместо повторного выставления

**cleanup_backpack_if_needed — порядок:**
1. Открыть рюкзак
2. **Для каждой страницы (max 3):**
   - Открыть бонусы ("Бонус" в названии → "Открыть")
   - Выставить на аукцион
   - Разобрать оставшееся
   - Выбросить зелёные без использования
3. Вернуться в /dungeons
4. Проверить крафт

**Аукцион — автоценообразование:**
```python
# Получаем цену конкурента
comp_gold, comp_silver, comp_count = get_competitor_min_price_per_unit(page)
# Считаем цену за штуку
price_per_unit = (comp_gold * 100 + comp_silver) // comp_count
# Наша цена = (цена_за_штуку * наше_кол-во) - 1 серебро
our_total = (price_per_unit * my_count) - 1
```

**Селекторы аукциона:**
```python
"div.list-el.first"           # Первый конкурент (минимальная цена)
"a.go-btn._auction"           # Кнопка выкупа с ценой
"span.i12-money_gold"         # Иконка золота
"span.i12-money_silver"       # Иконка серебра
"span.e-count"                # Количество (x2, x10)
"span.feedbackPanelERROR"     # Предупреждение о низкой цене
"input[name='bidGold']"       # Поле начальной цены (золото)
"input[name='buyoutGold']"    # Поле выкупа (золото)
```

**Крафт:**
```python
# Проверка готовности
div.info-box с "Готово" + кнопка "Повторить"

# repeat_craft_if_ready() — нажимает "Повторить" если готов
```

**Зелёные предметы (iGood):**
```python
# Проверка
name_link.get_attribute("class") содержит "iGood"

# Приоритет: разобрать > аукцион > выбросить
```

### Конфигурация данженов (dungeon_config.py)

**DUNGEON_ORDER — порядок прохождения:**
```python
[
    "dng:dSanctuary",      # Святилище Накрила
    "dng:dHellRuins",      # Hell Ruins
    "dng:RestMonastery",   # Rest Monastery
    "dng:HighDungeon",     # High Dungeon
    "dng:CitadelHolding",  # Citadel Holding
    "dng:Underlight",      # Underlight
    "dng:way2Baron",       # Way to Baron
    "dng:Barony",          # Barony
    "dng:ShadowGuard",     # Shadow Guard
]
```

**START_DUNGEON_INDEX** — из settings.json, по умолчанию 0

**need_difficulty:**
- `True` — нужно повышать сложность (кнопка `a.switch-level-left`)
- `False` — Sanctuary, way2Baron (нельзя изменить)

### Статистика (stats.py)

**Файл:** `stats.json`

**Отслеживается:**
- total_dungeons_completed
- total_stages_completed
- total_deaths
- total_items_auctioned
- total_items_disassembled
- total_bonuses_opened
- total_hell_games_time (секунды)
- dungeons (статистика по каждому данжену)
- sessions (история, max 100)

**BotStats методы:**
```python
dungeon_completed(dungeon_id, name)  # +1 данжен
stage_completed()                     # +1 этап
death_recorded(dungeon_id)           # +1 смерть
items_auctioned(count)               # +N на аукцион
items_disassembled(count)            # +N разобрано
bonuses_opened(count)                # +N бонусов
hell_games_time(seconds)             # +время в АИ
end_session()                        # Завершить и сохранить
```

**Глобальный доступ:**
```python
init_stats()   # Инициализация (вызывается в main.py)
get_stats()    # Получить экземпляр
print_stats()  # Вывести сводку
```

### Почта (mail.py)

**Проверка уведомлений:**
```python
"span.navigator._mail"  # Иконка непрочитанного письма
```

**check_and_collect_mail(page):**
1. Проверяет `has_mail_notification()`
2. Переходит на `/message/list`
3. Обрабатывает все активные сообщения
4. Возвращается в /dungeons

**Активные сообщения:**
```python
"a.task-section._label.brass"  # Без класса c-verygray
```

**Забрать предметы:**
```python
# Кнопка
"Забрать и удалить сообщение" в a.btn.nav-btn

# Попап полного рюкзака
"div.notice-rich3" с текстом "рюкзаке нет места"
```

**Чёрный список аукциона (автозаполнение):**
```python
# Если сообщение "Срок твоего лота истёк. (Предмет)"
# → извлекаем название → добавляем в auction_blacklist.json
# → предмет будет разбираться вместо продажи
```
