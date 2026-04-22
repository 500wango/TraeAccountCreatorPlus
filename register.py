from ast import For
import asyncio
import warnings
from ctypes import cdll
import random
import string
import os
import re
import json
import sys
from turtle import back
from httpx import ReadTimeout
from playwright.async_api import async_playwright
from mail_client import AsyncMailClient, check_api_key
from colorama import Fore, Style, Back
from colorama import init as coloinit
import httpx

# 屏蔽RuntimeWarning
warnings.filterwarnings("ignore", category=RuntimeWarning)

coloinit(autoreset=True)
# 颜色列表
colors = [
    Back.GREEN,
    Back.YELLOW,
    Back.BLUE,
    Back.MAGENTA,
    Back.CYAN,
    Fore.CYAN,
    Fore.GREEN,
    Fore.BLUE,
    Fore.YELLOW,
    Fore.MAGENTA,
]

# Setup directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_DIR = os.path.join(BASE_DIR, "cookies")
SESSION_DIR = os.path.join(BASE_DIR, "sessions")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.txt")
os.makedirs(COOKIES_DIR, exist_ok=True)
os.makedirs(SESSION_DIR, exist_ok=True)

# Chrome 139 真实浏览器指纹
CHROME_139_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.7258.154 Safari/537.36"
)


def generate_password(length=12):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.choices(chars, k=length))


async def save_account(email, password):
    write_header = (
        not os.path.exists(ACCOUNTS_FILE) or os.path.getsize(ACCOUNTS_FILE) == 0
    )
    with open(ACCOUNTS_FILE, "a", encoding="utf-8") as f:
        if write_header:
            f.write("Email    Password\n")
        f.write(f"{email}    {password}\n")


async def check_network():
    """检查网络连接（访问Google）"""
    test_urls = ["https://www.google.com", "https://www.youtube.com"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in test_urls:
            try:
                response = await client.get(url, follow_redirects=True)
                if response.status_code == 200:
                    return True
            except Exception:
                continue
    return False


async def load_cookies(context, email):
    """加载保存的Cookie"""
    cookie_path = os.path.join(COOKIES_DIR, f"{email}.json")
    if os.path.exists(cookie_path):
        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            return True
        except Exception:
            pass
    return False


async def load_session_storage(playwright, email):
    """加载保存的Session存储"""
    session_path = os.path.join(SESSION_DIR, f"{email}.json")
    if os.path.exists(session_path):
        try:
            with open(session_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


async def save_session_storage(email, page):
    """保存Session存储（localStorage等）"""
    try:
        session_data = await page.evaluate("""() => {
            return {
                localStorage: localStorage,
                sessionStorage: sessionStorage
            };
        }""")
        session_path = os.path.join(SESSION_DIR, f"{email}.json")
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f)
    except Exception:
        pass


async def inject_stealth_scripts(page):
    """注入反检测脚本"""
    await page.add_init_script("""
        // 1. navigator.webdriver 设置为 undefined
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
        
        // 2. 插件检测伪装
        const fakePlugins = [
            { name: 'Chrome PDF Plugin', description: 'Portable Document Format', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', description: '', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', description: '', filename: 'internal-nacl-plugin' }
        ];
        Object.defineProperty(navigator, 'plugins', {
            get: () => fakePlugins.slice(0, 3),
            configurable: true
        });
        
        // 3. languages 伪装
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en-US', 'en'],
            configurable: true
        });
        
        // 4. permissions API 伪装
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission, force: true }) :
                originalQuery(parameters)
        );
        
        // 5. platform 伪装
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32',
            configurable: true
        });
        
        // 6. hardwareConcurrency 伪装
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => Math.floor(Math.random() * 8) + 8,
            configurable: true
        });
        
        // 7. deviceMemory 伪装
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8,
            configurable: true
        });
        
        // 8. Chrome 运行时对象
        window.chrome = {
            runtime: { sendMessage: () => {}, onMessage: { addListener: () => {} } }
        };
    """)

    # WebGL 伪装
    await page.add_init_script("""
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Google Inc. (NVIDIA)';
            if (parameter === 37446) return 'ANGLE (NVIDIA GeForce RTX 3080, Direct3D11 vs_5_0 ps_5_0)';
            return getParameter.apply(this, arguments);
        };
    """)


async def setup_request_interception(page):
    """设置请求拦截，移除自动化相关headers"""

    async def handle_route(route):
        request = route.request
        headers = request.headers.copy()

        headers.pop("x-playwright", None)
        headers.pop("x-devtools", None)
        headers.pop(" playwright", None)

        if request.resource_type == "document":
            headers["Accept"] = (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            )
            headers["Upgrade-Insecure-Requests"] = "1"

        await route.continue_(headers=headers)

    await page.route("**/*", handle_route)


async def run_registration(CD, thread_num):
    global colors
    print(colors[thread_num - 1] + "开始单账号注册流程...")

    if not check_api_key():
        return False

    total_duration = 60
    retry_num = int(total_duration / CD)

    mail_client = AsyncMailClient()
    browser = None
    context = None
    page = None

    try:
        await mail_client.start()
        password = generate_password()
        email = mail_client.get_email()

        async with async_playwright() as p:
            print(colors[thread_num - 1] + f"[线程{thread_num}] 启动浏览器...")

            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--renderer-process-limit=1",
                    "--start-minimized",
                    "--window-position=10000,10000",
                ],
            )

            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=CHROME_139_USER_AGENT,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                permissions=["geolocation"],
                geolocation={"latitude": 31.2304, "longitude": 121.4737},
                extra_http_headers={
                    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                    "sec-ch-ua": '"Chromium";v="139", "Not-A Brand";v="8"',
                    "sec-ch-ua-platform": '"Windows"',
                },
            )

            if email:
                await load_cookies(context, email)

            page = await context.new_page()
            await inject_stealth_scripts(page)
            await setup_request_interception(page)

            print(colors[thread_num - 1] + f"[线程{thread_num}] 打开注册页面...")
            await page.goto(
                "https://www.trae.ai/sign-up",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(2)

            email = mail_client.get_email()
            if not email:
                return False

            email_input = page.get_by_role("textbox", name="Email")
            await email_input.wait_for(state="visible", timeout=15000)
            await email_input.fill(email)
            await page.get_by_text("Send Code").click()

            verification_code = None
            for i in range(retry_num):
                await asyncio.sleep(CD)
                await mail_client.check_emails()
                if mail_client.last_verification_code:
                    verification_code = mail_client.last_verification_code
                    break

            if not verification_code:
                return False

            await page.get_by_role("textbox", name="Verification code").fill(verification_code)
            await page.get_by_role("textbox", name="Password").fill(password)

            signup_btns = page.get_by_text("Sign Up")
            if await signup_btns.count() > 1:
                await signup_btns.nth(1).click()
            else:
                await signup_btns.click()

            try:
                await page.wait_for_url(lambda url: "setting" in url, timeout=20000)
                print(colors[thread_num - 1] + f"[线程{thread_num}] 注册成功")
            except:
                if await page.locator(".error-message").count() > 0:
                    return False

            await save_account(email, password)

            # 保存 Cookies
            cookies = await context.cookies()
            cookie_path = os.path.join(COOKIES_DIR, f"{email}.json")
            with open(cookie_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f)

            await save_session_storage(email, page)
            return True

    except Exception as e:
        print(colors[thread_num - 1] + f"[线程{thread_num}] 异常：{e}")
        return False
    finally:
        if mail_client:
            await mail_client.close()

# 连续失败计数器
consecutive_failures = 0
failure_lock = asyncio.Lock()
MAX_CONSECUTIVE_FAILURES = 10

async def run_batch(total, concurrency, mailsCheckCD):
    if not await check_network():
        print("网络连接异常")
        return

    queue = asyncio.Queue()
    for i in range(1, total + 1):
        queue.put_nowait(i)
    
    stop_event = asyncio.Event()

    async def worker(worker_id):
        global consecutive_failures
        while not queue.empty() and not stop_event.is_set():
            index = await queue.get()
            success = await run_registration(mailsCheckCD, worker_id)
            
            async with failure_lock:
                if success:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        stop_event.set()
            queue.task_done()

    tasks = [asyncio.create_task(worker(i + 1)) for i in range(concurrency)]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(run_batch(1, 1, 10))
