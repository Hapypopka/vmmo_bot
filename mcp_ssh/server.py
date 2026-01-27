"""
MCP SSH Server для VMMO Bot
Позволяет Claude выполнять команды на сервере напрямую
"""

import asyncio
import os
import sys
from pathlib import Path

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("ERROR: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

try:
    import asyncssh
except ImportError:
    print("ERROR: asyncssh not installed. Run: pip install asyncssh", file=sys.stderr)
    sys.exit(1)

# Конфигурация сервера
SSH_HOST = os.environ.get("VMMO_SSH_HOST", "45.131.187.128")
SSH_USER = os.environ.get("VMMO_SSH_USER", "root")
SSH_KEY_PATH = os.environ.get("VMMO_SSH_KEY", str(Path.home() / ".ssh" / "id_ed25519_vmmo"))
VMMO_BOT_PATH = "/home/claude/vmmo_bot"

server = Server("vmmo-ssh")

# Глобальное соединение
ssh_conn = None


async def ensure_connection():
    """Создаёт SSH соединение если нет"""
    global ssh_conn

    if ssh_conn is not None:
        try:
            # Проверяем что соединение живо
            result = await ssh_conn.run("echo ok", check=True)
            return ssh_conn
        except Exception:
            ssh_conn = None

    # Создаём новое соединение
    ssh_conn = await asyncssh.connect(
        SSH_HOST,
        username=SSH_USER,
        client_keys=[SSH_KEY_PATH],
        known_hosts=None  # Отключаем проверку known_hosts
    )
    return ssh_conn


@server.list_tools()
async def list_tools():
    """Список доступных инструментов"""
    return [
        Tool(
            name="ssh_exec",
            description="Выполнить команду на сервере VMMO (45.131.187.128)",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Команда для выполнения"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Таймаут в секундах (по умолчанию 30)",
                        "default": 30
                    }
                },
                "required": ["command"]
            }
        ),
        Tool(
            name="ssh_bot_logs",
            description="Получить логи бота (последние N строк)",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "string",
                        "description": "Профиль бота (char1-char22)",
                        "default": "char1"
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Количество строк (по умолчанию 50)",
                        "default": 50
                    },
                    "grep": {
                        "type": "string",
                        "description": "Фильтр (grep pattern)",
                        "default": None
                    }
                }
            }
        ),
        Tool(
            name="ssh_bot_status",
            description="Статус всех ботов (запущены/остановлены)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="ssh_restart_bot",
            description="Перезапустить бота",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "string",
                        "description": "Профиль бота (char1-char22) или 'all' для всех"
                    }
                },
                "required": ["profile"]
            }
        ),
        Tool(
            name="ssh_deploy",
            description="Задеплоить файл на сервер (scp)",
            inputSchema={
                "type": "object",
                "properties": {
                    "local_path": {
                        "type": "string",
                        "description": "Локальный путь к файлу"
                    },
                    "remote_path": {
                        "type": "string",
                        "description": "Путь на сервере (относительно /home/claude/vmmo_bot/)",
                        "default": ""
                    }
                },
                "required": ["local_path"]
            }
        ),
        Tool(
            name="ssh_read_file",
            description="Прочитать файл на сервере",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Путь к файлу на сервере"
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Ограничить количество строк (0 = весь файл)",
                        "default": 0
                    }
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="ssh_list_profiles",
            description="Список профилей и их статусов на сервере",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="ssh_clear_cache",
            description="Очистить __pycache__ на сервере",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="ssh_restart_services",
            description="Перезапустить веб-панель и/или Telegram бота",
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Сервис: 'web', 'telegram', или 'all'",
                        "enum": ["web", "telegram", "all"],
                        "default": "all"
                    }
                }
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Выполнить инструмент"""
    try:
        conn = await ensure_connection()

        if name == "ssh_exec":
            command = arguments["command"]
            timeout = arguments.get("timeout", 30)

            result = await asyncio.wait_for(
                conn.run(command, check=False),
                timeout=timeout
            )

            output = result.stdout or ""
            if result.stderr:
                output += f"\n[STDERR]\n{result.stderr}"
            output += f"\n[Exit code: {result.exit_status}]"

            return [TextContent(type="text", text=output)]

        elif name == "ssh_bot_logs":
            profile = arguments.get("profile", "char1")
            lines = arguments.get("lines", 50)
            grep_pattern = arguments.get("grep")

            log_path = f"{VMMO_BOT_PATH}/logs/bot_{profile}_live.log"

            if grep_pattern:
                cmd = f"grep -i '{grep_pattern}' {log_path} | tail -{lines}"
            else:
                cmd = f"tail -{lines} {log_path}"

            result = await conn.run(cmd, check=False)
            output = result.stdout or f"No logs found for {profile}"

            return [TextContent(type="text", text=output)]

        elif name == "ssh_bot_status":
            # Получаем список запущенных ботов
            cmd = "ps aux | grep 'python.*-m requests_bot.bot' | grep -v grep | awk '{print $NF}'"
            result = await conn.run(cmd, check=False)
            running = set(result.stdout.strip().split('\n')) if result.stdout.strip() else set()

            # Получаем список всех профилей
            cmd = f"ls -1 {VMMO_BOT_PATH}/profiles/"
            result = await conn.run(cmd, check=False)
            all_profiles = [p for p in result.stdout.strip().split('\n') if p.startswith('char')]

            lines = []
            running_count = 0
            for profile in sorted(all_profiles, key=lambda x: int(x.replace('char', ''))):
                if profile in running:
                    lines.append(f"🟢 {profile}")
                    running_count += 1
                else:
                    lines.append(f"🔴 {profile}")

            header = f"Боты: {running_count}/{len(all_profiles)} запущено\n" + "="*30 + "\n"
            return [TextContent(type="text", text=header + "\n".join(lines))]

        elif name == "ssh_restart_bot":
            profile = arguments["profile"]

            if profile == "all":
                # Останавливаем всех
                await conn.run("pkill -f 'python.*-m requests_bot.bot'", check=False)
                await asyncio.sleep(2)

                # Запускаем всех
                cmd = f"ls -1 {VMMO_BOT_PATH}/profiles/ | grep char"
                result = await conn.run(cmd, check=False)
                profiles = result.stdout.strip().split('\n')

                for p in profiles:
                    if p.startswith('char'):
                        start_cmd = f"cd {VMMO_BOT_PATH} && nohup python3 -m requests_bot.bot {p} > /dev/null 2>&1 &"
                        await conn.run(start_cmd, check=False)
                        await asyncio.sleep(0.5)

                return [TextContent(type="text", text=f"Перезапущено {len(profiles)} ботов")]
            else:
                # Останавливаем конкретного
                await conn.run(f"pkill -f 'python.*-m requests_bot.bot {profile}'", check=False)
                await asyncio.sleep(1)

                # Запускаем
                start_cmd = f"cd {VMMO_BOT_PATH} && nohup python3 -m requests_bot.bot {profile} > /dev/null 2>&1 &"
                await conn.run(start_cmd, check=False)

                return [TextContent(type="text", text=f"Бот {profile} перезапущен")]

        elif name == "ssh_deploy":
            local_path = arguments["local_path"]
            remote_path = arguments.get("remote_path", "")

            if not remote_path:
                # Вычисляем путь относительно vmmo_bot
                if "requests_bot" in local_path:
                    remote_path = local_path.split("requests_bot")[-1]
                    remote_path = f"requests_bot{remote_path}"
                else:
                    remote_path = os.path.basename(local_path)

            full_remote = f"{VMMO_BOT_PATH}/{remote_path}"

            # Используем asyncssh.scp
            await asyncssh.scp(local_path, (conn, full_remote))

            return [TextContent(type="text", text=f"Deployed: {local_path} -> {full_remote}")]

        elif name == "ssh_read_file":
            path = arguments["path"]
            lines = arguments.get("lines", 0)

            # Добавляем базовый путь если нужно
            if not path.startswith("/"):
                path = f"{VMMO_BOT_PATH}/{path}"

            if lines > 0:
                cmd = f"head -{lines} '{path}'"
            else:
                cmd = f"cat '{path}'"

            result = await conn.run(cmd, check=False)

            if result.exit_status != 0:
                return [TextContent(type="text", text=f"Error: {result.stderr}")]

            return [TextContent(type="text", text=result.stdout)]

        elif name == "ssh_list_profiles":
            cmd = f"""
            for d in {VMMO_BOT_PATH}/profiles/char*/; do
                profile=$(basename $d)
                if [ -f "$d/config.json" ]; then
                    enabled=$(python3 -c "import json; c=json.load(open('$d/config.json')); print('enabled' if c.get('dungeons_enabled', True) else 'disabled')" 2>/dev/null || echo "unknown")
                    echo "$profile: $enabled"
                fi
            done
            """
            result = await conn.run(cmd, check=False)
            return [TextContent(type="text", text=result.stdout or "No profiles found")]

        elif name == "ssh_clear_cache":
            cmd = f"find {VMMO_BOT_PATH} -type d -name '__pycache__' -exec rm -rf {{}} + 2>/dev/null; echo 'Cache cleared'"
            result = await conn.run(cmd, check=False)
            return [TextContent(type="text", text="__pycache__ очищен на сервере")]

        elif name == "ssh_restart_services":
            service = arguments.get("service", "all")
            messages = []

            if service in ["web", "all"]:
                await conn.run("fuser -k 5000/tcp 2>/dev/null", check=False)
                await asyncio.sleep(1)
                cmd = f"cd {VMMO_BOT_PATH} && nohup python3 -m requests_bot.web_panel > /tmp/web_panel.log 2>&1 &"
                await conn.run(cmd, check=False)
                messages.append("Веб-панель перезапущена")

            if service in ["telegram", "all"]:
                await conn.run("pkill -f 'python.*telegram_bot'", check=False)
                await asyncio.sleep(1)
                cmd = f"cd {VMMO_BOT_PATH} && nohup python3 -m requests_bot.telegram_bot > /tmp/telegram_bot.log 2>&1 &"
                await conn.run(cmd, check=False)
                messages.append("Telegram бот перезапущен")

            return [TextContent(type="text", text="\n".join(messages))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except asyncio.TimeoutError:
        return [TextContent(type="text", text="Error: Command timed out")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {type(e).__name__}: {str(e)}")]


async def cleanup():
    """Закрывает SSH соединение"""
    global ssh_conn
    if ssh_conn:
        ssh_conn.close()
        await ssh_conn.wait_closed()


async def main():
    """Запуск MCP сервера"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
