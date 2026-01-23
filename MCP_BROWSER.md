# MCP Browser - Заметки

## Авторизация на vmmo.vten.ru

### browser_login
Исправлен. Использует правильные селекторы:
- Поле логина: `#login`
- Поле пароля: `#password`
- URL: главная страница `https://vmmo.vten.ru/`

### Ручная авторизация (если browser_login всё равно не работает)
```
1. browser_navigate → https://vmmo.vten.ru/
2. browser_fill → #login → Castertoyi
3. browser_fill → #password → Agesevemu1313!
4. browser_click → button[type="submit"]
```

### Форма логина
- Поле логина: `#login` или `input[name="login"]`
- Поле пароля: `#password` или `input[name="password"]`
- Кнопка: `button[type="submit"]` с классом `.landing-login-button`

---

## Частые проблемы

### Таймаут при авторизации
Если browser_login зависает - использовать ручную авторизацию выше.

### browser_reset не работает
Ошибка `UnboundLocalError: playwright_instance`. Просто игнорировать и пробовать navigate заново.

### accessDenied
Означает что сессия не авторизована. Нужно залогиниться.

---

## Полезные селекторы

### Адские игры
- Источники: `.source-link`
- Текущий источник: `.source-link._current`
- Светлый источник: `._side-light`
- Тёмный источник: `._side-dark`
- Заблокированный: `._lock`
- Хранитель: `._keeper`
- Свой юнит: `._own` или `._own-death`
- Позиция юнита: `._unit-pos-{N}`

### Скиллы
- Обёртка скилла: `.wrap-skill-link._skill-pos-{N}`
- На кулдауне: `._time-lock`
- Таймер КД: `.time-counter`

---

## Дефолтный аккаунт
- Логин: `Castertoyi`
- Пароль: `Agesevemu1313!`
- Использовать для исследований, НЕ для боевых ботов
