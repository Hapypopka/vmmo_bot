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
