"""
MCP Browser Server для VMMO Bot
Позволяет Claude управлять браузером с авторизацией через куки
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Добавляем родительскую папку для импорта requests_bot
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("ERROR: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

try:
    from playwright.async_api import async_playwright, Browser, Page
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium", file=sys.stderr)
    sys.exit(1)

# Глобальные переменные
browser: Browser = None
page: Page = None
playwright_instance = None

# Путь к кукам по умолчанию
DEFAULT_COOKIES_PATH = os.environ.get(
    "VMMO_COOKIES_PATH",
    str(Path(__file__).parent.parent / "profiles" / "char1" / "cookies.json")
)

BASE_URL = "https://m.vten.ru"  # Мобильная версия (как боты)

server = Server("vmmo-browser")


def convert_cookies_for_playwright(cookies: list) -> list:
    """Конвертирует куки из формата requests/puppeteer в формат Playwright"""
    pw_cookies = []
    for cookie in cookies:
        pw_cookie = {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie.get("domain", ".vmmo.vten.ru"),
            "path": cookie.get("path", "/"),
        }
        # Playwright не принимает expires=-1, пропускаем такие
        if cookie.get("expires") and cookie["expires"] > 0:
            pw_cookie["expires"] = cookie["expires"]
        if cookie.get("secure"):
            pw_cookie["secure"] = cookie["secure"]
        if cookie.get("httpOnly"):
            pw_cookie["httpOnly"] = cookie["httpOnly"]
        if cookie.get("sameSite"):
            # Playwright принимает "Strict", "Lax", "None"
            pw_cookie["sameSite"] = cookie["sameSite"]
        pw_cookies.append(pw_cookie)
    return pw_cookies


async def ensure_browser():
    """Запускает браузер если ещё не запущен или был закрыт"""
    global browser, page, playwright_instance

    # Проверяем что браузер жив
    need_restart = False
    if browser is None:
        need_restart = True
    else:
        try:
            # Пробуем обратиться к браузеру - если закрыт, будет ошибка
            if not browser.is_connected():
                need_restart = True
        except Exception:
            need_restart = True

    if need_restart:
        # Закрываем старые ресурсы если есть
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if playwright_instance:
            try:
                await playwright_instance.stop()
            except Exception:
                pass

        # Создаём новый браузер
        playwright_instance = await async_playwright().start()
        browser = await playwright_instance.chromium.launch(
            headless=os.environ.get("HEADLESS", "true").lower() == "true"
        )
        context = await browser.new_context(
            viewport={"width": 500, "height": 844},
            device_scale_factor=3,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1"
        )
        page = await context.new_page()

        # Загружаем куки
        cookies_path = os.environ.get("VMMO_COOKIES_PATH", DEFAULT_COOKIES_PATH)
        if os.path.exists(cookies_path):
            with open(cookies_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            pw_cookies = convert_cookies_for_playwright(cookies)
            await context.add_cookies(pw_cookies)

    return page


@server.list_tools()
async def list_tools():
    """Список доступных инструментов"""
    return [
        Tool(
            name="browser_navigate",
            description="Перейти на URL. Можно указать полный URL или относительный путь (например /backpack)",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL или путь (например: /backpack, /dungeon, https://vmmo.vten.ru/city)"
                    },
                    "wait_for": {
                        "type": "string",
                        "description": "CSS селектор элемента, которого ждать после загрузки",
                        "default": None
                    }
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="browser_get_html",
            description="Получить HTML текущей страницы или конкретного элемента",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента (если не указан - вся страница)",
                        "default": None
                    },
                    "outer": {
                        "type": "boolean",
                        "description": "Включить внешний HTML элемента (outerHTML vs innerHTML)",
                        "default": True
                    }
                }
            }
        ),
        Tool(
            name="browser_get_text",
            description="Получить текстовое содержимое страницы или элемента (без HTML тегов)",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента",
                        "default": None
                    }
                }
            }
        ),
        Tool(
            name="browser_click",
            description="Кликнуть на элемент по CSS селектору или тексту",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента"
                    },
                    "text": {
                        "type": "string",
                        "description": "Текст элемента (альтернатива selector)",
                        "default": None
                    },
                    "wait_after": {
                        "type": "integer",
                        "description": "Миллисекунды ожидания после клика",
                        "default": 1000
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="browser_fill",
            description="Ввести текст в поле ввода",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор поля ввода"
                    },
                    "value": {
                        "type": "string",
                        "description": "Текст для ввода"
                    }
                },
                "required": ["selector", "value"]
            }
        ),
        Tool(
            name="browser_screenshot",
            description="Сделать скриншот страницы",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Путь для сохранения (по умолчанию temp/screenshot.png)",
                        "default": None
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": "Скриншот всей страницы (не только видимой части)",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="browser_execute_js",
            description="Выполнить JavaScript код на странице",
            inputSchema={
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "JavaScript код для выполнения"
                    }
                },
                "required": ["script"]
            }
        ),
        Tool(
            name="browser_wait",
            description="Подождать появления элемента или заданное время",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента для ожидания",
                        "default": None
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Таймаут в миллисекундах",
                        "default": 5000
                    }
                }
            }
        ),
        Tool(
            name="browser_get_cookies",
            description="Получить текущие куки браузера",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="browser_load_profile",
            description="Загрузить куки другого профиля (char1-char22)",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "string",
                        "description": "Имя профиля (char1, char2, ..., char21, char22)"
                    }
                },
                "required": ["profile"]
            }
        ),
        Tool(
            name="browser_info",
            description="Получить информацию о текущей странице (URL, title, etc)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="browser_reset",
            description="Принудительно перезапустить браузер (если завис или закрыт вручную)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="browser_login",
            description="Залогиниться на m.vten.ru по логину и паролю. По умолчанию использует Пупупу Пупупу",
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Логин (по умолчанию: Пупупу Пупупу)",
                        "default": "Пупупу Пупупу"
                    },
                    "password": {
                        "type": "string",
                        "description": "Пароль (по умолчанию: Agesevemu1313!)",
                        "default": "Agesevemu1313!"
                    }
                }
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Выполнить инструмент"""
    global browser, page

    try:
        page = await ensure_browser()

        if name == "browser_navigate":
            url = arguments["url"]
            if not url.startswith("http"):
                url = BASE_URL + (url if url.startswith("/") else "/" + url)

            await page.goto(url, wait_until="domcontentloaded")

            if arguments.get("wait_for"):
                await page.wait_for_selector(arguments["wait_for"], timeout=10000)

            return [TextContent(
                type="text",
                text=f"Navigated to: {page.url}\nTitle: {await page.title()}"
            )]

        elif name == "browser_get_html":
            selector = arguments.get("selector")
            outer = arguments.get("outer", True)

            if selector:
                element = await page.query_selector(selector)
                if element:
                    if outer:
                        html = await element.evaluate("el => el.outerHTML")
                    else:
                        html = await element.evaluate("el => el.innerHTML")
                else:
                    html = f"Element not found: {selector}"
            else:
                html = await page.content()

            # Ограничиваем размер
            if len(html) > 50000:
                html = html[:50000] + "\n... (truncated)"

            return [TextContent(type="text", text=html)]

        elif name == "browser_get_text":
            selector = arguments.get("selector")

            if selector:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                else:
                    text = f"Element not found: {selector}"
            else:
                text = await page.inner_text("body")

            return [TextContent(type="text", text=text)]

        elif name == "browser_click":
            selector = arguments.get("selector")
            text = arguments.get("text")
            wait_after = arguments.get("wait_after", 1000)

            if text and not selector:
                # Клик по тексту
                selector = f"text={text}"

            if not selector:
                return [TextContent(type="text", text="Error: need selector or text")]

            await page.click(selector)
            await page.wait_for_timeout(wait_after)

            return [TextContent(
                type="text",
                text=f"Clicked: {selector}\nCurrent URL: {page.url}"
            )]

        elif name == "browser_fill":
            await page.fill(arguments["selector"], arguments["value"])
            return [TextContent(type="text", text=f"Filled {arguments['selector']} with value")]

        elif name == "browser_screenshot":
            path = arguments.get("path")
            if not path:
                path = str(Path(__file__).parent.parent / "temp" / "screenshot.png")

            os.makedirs(os.path.dirname(path), exist_ok=True)

            await page.screenshot(
                path=path,
                full_page=arguments.get("full_page", False)
            )

            return [TextContent(type="text", text=f"Screenshot saved to: {path}")]

        elif name == "browser_execute_js":
            result = await page.evaluate(arguments["script"])
            return [TextContent(type="text", text=f"Result: {json.dumps(result, ensure_ascii=False, default=str)}")]

        elif name == "browser_wait":
            selector = arguments.get("selector")
            timeout = arguments.get("timeout", 5000)

            if selector:
                await page.wait_for_selector(selector, timeout=timeout)
                return [TextContent(type="text", text=f"Element found: {selector}")]
            else:
                await page.wait_for_timeout(timeout)
                return [TextContent(type="text", text=f"Waited {timeout}ms")]

        elif name == "browser_get_cookies":
            context = page.context
            cookies = await context.cookies()
            return [TextContent(
                type="text",
                text=json.dumps(cookies, ensure_ascii=False, indent=2)
            )]

        elif name == "browser_load_profile":
            profile = arguments["profile"]
            cookies_path = Path(__file__).parent.parent / "profiles" / profile / "cookies.json"

            if not cookies_path.exists():
                return [TextContent(type="text", text=f"Profile not found: {profile}")]

            with open(cookies_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            pw_cookies = convert_cookies_for_playwright(cookies)
            context = page.context
            await context.clear_cookies()
            await context.add_cookies(pw_cookies)

            return [TextContent(type="text", text=f"Loaded cookies for profile: {profile}")]

        elif name == "browser_info":
            return [TextContent(
                type="text",
                text=f"URL: {page.url}\nTitle: {await page.title()}\nViewport: {page.viewport_size}"
            )]

        elif name == "browser_reset":
            # Принудительно закрываем и пересоздаём браузер
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_instance:
                try:
                    await playwright_instance.stop()
                except Exception:
                    pass
            browser = None
            page = None
            playwright_instance = None

            # Создаём новый
            page = await ensure_browser()
            return [TextContent(type="text", text="Browser reset complete. New browser started.")]

        elif name == "browser_login":
            username = arguments.get("username", "Пупупу Пупупу")
            password = arguments.get("password", "Agesevemu1313!")

            # Переходим на главную (там форма логина)
            await page.goto("https://vmmo.vten.ru/", wait_until="domcontentloaded")

            # Заполняем форму (поле называется "login", не "username"!)
            await page.fill('#login', username)
            await page.fill('#password', password)

            # Нажимаем кнопку входа
            await page.click('button[type="submit"]')
            await page.wait_for_timeout(3000)

            # Проверяем успех
            current_url = page.url
            title = await page.title()

            # Если остались на странице с формой логина - ошибка
            login_form = await page.query_selector('#login')
            if login_form:
                return [TextContent(type="text", text=f"Login failed. Still on login page: {current_url}")]

            return [TextContent(
                type="text",
                text=f"Logged in as: {username}\nCurrent URL: {current_url}\nTitle: {title}"
            )]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {type(e).__name__}: {str(e)}")]


async def cleanup():
    """Закрывает браузер"""
    global browser, playwright_instance
    if browser:
        await browser.close()
    if playwright_instance:
        await playwright_instance.stop()


async def main():
    """Запуск MCP сервера"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
