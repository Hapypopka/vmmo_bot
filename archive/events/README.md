# Архив ивент-данженов

Этот каталог содержит код ивентов, которые закончились и не будут активны до следующего года.

## Содержимое

### event_dungeon.py (архивирован 2026-01-28)

Код для всех ивент-данженов:

| Ключ | Название | Сложность | Период |
|------|----------|-----------|--------|
| NYLairFrost_2026 | Логово Демона Мороза | Брутал | Новый Год 2026 |
| SurtCaves | Пещеры Сурта | Нормал | Новый Год 2026 |
| DarknessComing | Предвестник Тьмы | Брутал | Новый Год 2026 |
| NYIceCastle_2026 | Ледяная Цитадель | Брутал | Новый Год 2026 |
| HellStalker | Ивент Сталкера | - | Хэллоуин |

### Классы в файле:
- `EventDungeonClient` - базовый клиент (устаревший)
- `NYEventDungeonClient` - клиент для NY ивента (устаревший)
- `GenericEventDungeonClient` - универсальный клиент для всех ивентов
- `EquipmentClient` - клиент для экипировки (был нужен для ивентов)

### Функции:
- `try_ny_event_dungeon()` - вход в NY ивент
- `try_event_dungeon_generic()` - универсальный вход в любой ивент
- `check_event_cooldown()` - проверка КД ивента
- `set_event_cooldown()` - установка КД после победы

## Как восстановить

1. Скопировать `event_dungeon.py` в `requests_bot/`
2. В `bot.py`:
   - Раскомментировать импорт `from requests_bot.event_dungeon import ...`
   - Добавить блок ивентов в `run_dungeon_cycle()`
3. В `config.py`:
   - Добавить функции `is_event_dungeon_enabled()` и `is_ny_event_dungeon_enabled()`
4. В `telegram_bot.py`:
   - Добавить кнопки настроек ивентов
5. В `web_panel.py`:
   - Добавить default значения для конфигов ивентов

## Настройки профиля (для справки)

```json
{
  "event_dungeon_enabled": true,
  "ny_event_dungeon_enabled": true
}
```
