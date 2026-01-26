# Server Secrets & Infrastructure

> **Этот файл на всякий случай** - SSH, VPN, пароли, порты.
> Не нужен для обычной работы с ботом.

---

## SSH ключи и доступ к серверам

**Локальный SSH ключ (без passphrase):**
- Путь: `~/.ssh/id_ed25519_vmmo`
- Публичный ключ: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG6Nk7NGphIN/1McdMCcTIhZ7hzLO24sEWnJkwBJCUu0 vmmo_bot`

**Серверы:**

| Сервер | IP | Пароль root | SSH ключ добавлен | Статус |
|--------|-----|-------------|-------------------|--------|
| Германия (старый) | 45.148.117.107 | JO8d3GSHqvLV | ДА (id_ed25519_vmmo) | Архив |
| Нидерланды (основной) | 45.131.187.128 | 6pCV9qfZiRTH | ДА (id_ed25519_vmmo) | Активный |

**Подключение:**
```bash
ssh -i ~/.ssh/id_ed25519_vmmo root@45.131.187.128  # Нидерланды (основной)
ssh -i ~/.ssh/id_ed25519_vmmo root@45.148.117.107  # Германия (старый, архив)
```

---

## DuckDNS

- Домен: `faizbot.duckdns.org`
- Токен: `7c65da64-4f47-4643-b812-6a801ea3605f`
- Обновление IP: `curl "https://www.duckdns.org/update?domains=faizbot&token=7c65da64-4f47-4643-b812-6a801ea3605f&ip=NEW_IP"`

---

## VPN (Reality/VLESS)

**x-ui панель:** http://45.131.187.128:15619

VPN работает на порту **8443** (не 443, т.к. 443 занят nginx для HTTPS).

### VPN пользователи (все на порту 8443):
| Имя | UUID | subId |
|-----|------|-------|
| Faiz (main) | 4678b413-dde6-4a9f-b57c-e154633f0f6f | reality123 |
| Ильмир | 15c47bf3-ea1d-418b-afa0-fc8eea553276 | ilmir456 |
| Faiz-2 | f4a2fda4-6763-4c7e-a560-ca60a96a3bb5 | faiz789 |
| Зульфия | 7d7b4c50-11fc-4df1-92d2-c24b8ca0a0a6 | lgfdsox2c1gl0s5j |
| Фаиз | e1c5fb07-f05f-4edf-a5fc-ab3812f77631 | veh6hfbsafmgupfj |
| Ильгам | 84ec4d41-a4b8-40e8-851f-d242c86dc207 | zox9snw9u8lve2dw |
| ПК Ильгам | d241b4cc-5001-4919-a267-50e1ac1adb85 | hk8gfmtqpggmv6mz |

### Ссылка для подключения (Hiddify/v2rayNG):
Формат ссылки (подставить нужный UUID):
```
vless://UUID@45.131.187.128:8443?type=tcp&security=reality&pbk=78Men0MPTAojbX2S7SL2n9OmUh3HPuj35uRmaH_kTFw&fp=chrome&sni=www.microsoft.com&sid=fc0f1ebc97ae1e55&spx=%2F&flow=xtls-rprx-vision#ИМЯ
```

### Управление x-ui:
```bash
systemctl restart x-ui   # перезапуск
systemctl status x-ui    # статус
```

### Watchdog (автопроверка каждые 5 мин):
Скрипт `/usr/local/bin/check-xray.sh` проверяет что порт 8443 слушается и перезапускает x-ui если нет.
Логи: `/var/log/xray-watchdog.log`

```bash
# Проверить лог watchdog
cat /var/log/xray-watchdog.log
```

### Если нужно изменить порт VPN:
```bash
sqlite3 /etc/x-ui/x-ui.db "UPDATE inbounds SET port = НОВЫЙ_ПОРТ WHERE id = 8;"
systemctl restart x-ui
```

---

## Порты на сервере

| Порт | Сервис |
|------|--------|
| 80 | nginx (редирект на 443) |
| 443 | nginx (HTTPS веб-панель) |
| 5000 | Flask веб-панель (internal) |
| 8443 | xray Reality VPN |
| 15619 | x-ui веб-панель |
| 2096 | x-ui subscription server |

---

## Веб-панель - доступ

**URL:** https://faizbot.duckdns.org
**Пароль:** `1616`

### Перезапуск веб-панели:
```bash
ssh -i ~/.ssh/id_ed25519_vmmo root@45.131.187.128 "fuser -k 5000/tcp; sleep 1; cd /home/claude/vmmo_bot && nohup python3 -m requests_bot.web_panel > /tmp/web_panel.log 2>&1 &"
```
