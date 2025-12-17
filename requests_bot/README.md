# VMMO Requests Bot

Экспериментальный бот на чистом `requests` — без браузера.

## Статус

**РАБОТАЕТ**: Бой в Адских Играх (атака + скиллы)

## Что реализовано

- [x] Авторизация через requests
- [x] Парсинг Wicket AJAX URLs из HTML
- [x] Атака в бою
- [x] Использование скиллов
- [x] Переключение источников (Hell Games)

## Что НЕ реализовано

- [ ] Вход в данжен (требует клик по div, сложная логика)
- [ ] Проверка КД данженов (AJAX подгрузка)
- [ ] Сбор лута
- [ ] Переход между этапами

## Запуск

```bash
# Из корня проекта
cd warrior

# Тест (10 атак)
python -m requests_bot.main --attacks 10

# Бой в loop режиме
python -m requests_bot.main --loop --attacks 100 --delay 1.5

# Просто тест авторизации
python -m requests_bot.client
```

## Ограничения

1. **Нужен активный бой** — бот не может войти в данжен сам
2. **Только Hell Games** — данжены требуют сложной навигации
3. **Нет WebSocket** — не получает пуши от сервера

## Гибридный подход

Рекомендуемый workflow:

1. **Playwright бот** входит в данжен/Hell Games
2. **Requests бот** бьётся (меньше RAM)
3. **Playwright бот** собирает лут и переходит дальше

## Память

- Playwright + Chromium: ~500-800 MB
- Requests бот: ~30-50 MB

## Файлы

```
requests_bot/
├── __init__.py
├── client.py      # HTTP клиент + авторизация
├── combat.py      # Боевая система
├── main.py        # Точка входа
├── explore.py     # Утилита исследования HTML
├── test_ajax.py   # Тесты AJAX
├── test_combat.py # Тесты боя
└── test_login.py  # Тесты логина
```
