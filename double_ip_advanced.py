import argparse
import asyncio
import subprocess
import sys
import os
import random
from pathlib import Path
from typing import List


def ensure_playwright(auto_install: bool) -> None:
    """Ensure playwright is importable. If not, optionally try to install it into the
    current Python interpreter (safe convenience for users who run the script directly).
    """
    try:
        # try import lazily to avoid hard dependency until runtime
        import playwright  # type: ignore
    except ModuleNotFoundError:
        msg = (
            "Playwright is not installed in this Python environment.\n"
            "To install, run:\n"
            f"  {sys.executable} -m pip install playwright\n"
            "  then:\n"
            f"  {sys.executable} -m playwright install chromium\n"
        )
        if not auto_install:
            raise RuntimeError(msg)

        print("Playwright not found — attempting automatic install into this interpreter...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])  # may raise
        # install the browser binaries
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


async def run_browser(port: int, label: str, headless: bool, wait: int, fast: bool, timeout: int, text: bool, stealth: bool, profile_root: str, humanize: bool, incognito: bool, deep_stealth: bool, humanize2: bool, viewport_arg: str = None):
    # import inside function so the script can show a helpful message before import failure
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        # Device-like randomization: viewport, device scale, timezone
        viewports = [(1366, 768), (1440, 900), (1536, 864), (1280, 800), (1920, 1080)]
        vw, vh = random.choice(viewports)
        device_scale = random.choice([1, 1, 1, 2])
        timezones = ["UTC", "Europe/Moscow", "America/New_York", "Asia/Shanghai", "Europe/Paris"]
        tz = random.choice(timezones)

        # Randomize a User-Agent and Accept-Language a bit to reduce simple fingerprinting.
        user_agents = [
            # A few common desktop Chromium user agents
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        ]
        ua = random.choice(user_agents)
        accept_langs = ["en-US,en;q=0.9", "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7", "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"]
        lang = random.choice(accept_langs)

        # Choose whether to use persistent profile or incognito (ephemeral) context
        browser = None
        # Parse viewport_arg: None -> use randomized viewport; 'none' -> disable viewport (let window manage size)
        use_viewport = None
        if viewport_arg is None:
            use_viewport = {"width": vw, "height": vh}
        else:
            if isinstance(viewport_arg, str) and viewport_arg.lower() == "none":
                use_viewport = None
            else:
                try:
                    w, h = viewport_arg.lower().split('x')
                    use_viewport = {"width": int(w), "height": int(h)}
                except Exception:
                    use_viewport = {"width": vw, "height": vh}

        if incognito:
            # ephemeral: launch browser and create a fresh context (no profiles)
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox"]) 
            # If use_viewport is None, pass viewport=None to let the browser window be native size
            context_kwargs = dict(
                proxy={"server": f"http://127.0.0.1:{port}"},
                user_agent=ua,
                locale=lang.split(",")[0],
                device_scale_factor=device_scale,
                timezone_id=tz,
                accept_downloads=False,
            )
            if use_viewport is not None:
                context_kwargs["viewport"] = use_viewport
            else:
                context_kwargs["viewport"] = None
            context = await browser.new_context(**context_kwargs)
        else:
            # Use a persistent context so cookies/localStorage/cache persist between runs.
            # Create a per-port profile directory.
            profile_dir = Path(profile_root) / f"profile_{port}"
            profile_dir.mkdir(parents=True, exist_ok=True)

            # Launch a persistent context so we keep profile data between runs. Pass proxy and some context options.
            # persistent context: pass viewport only if set (None keeps browser default)
            persistent_kwargs = dict(
                headless=headless,
                proxy={"server": f"http://127.0.0.1:{port}"},
                user_agent=ua,
                locale=lang.split(",")[0],
                accept_downloads=False,
                args=["--no-sandbox"],
            )
            if use_viewport is not None:
                persistent_kwargs["viewport"] = use_viewport

            context = await p.chromium.launch_persistent_context(
                str(profile_dir),
                **persistent_kwargs,
            )

        

        # Use the first page or create one if none exist.
        pages = context.pages
        if pages:
            page = pages[0]
        else:
            page = await context.new_page()

        # Apply extra headers to hint Accept-Language
        await context.set_extra_http_headers({"Accept-Language": lang})

        print(f"正在打开 {label} 窗口 (端口: {port})... headless={headless} fast={fast} stealth={stealth}")
        # 如果启用了文本模式（最严格），仅允许 document 和 XHR/fetch
        if fast or text:
            if text:
                async def route_handler_text(route, request):
                    rtype = request.resource_type
                    # 仅允许文档和异步请求（xhr/fetch）以尽量只加载文本
                    if rtype in ("document", "xhr", "fetch"):
                        await route.continue_()
                    else:
                        await route.abort()

                await page.route("**/*", route_handler_text)
            else:
                # 快速模式：阻止图片、样式、字体、媒体资源
                async def route_handler(route, request):
                    rtype = request.resource_type
                    if rtype in ("image", "stylesheet", "font", "media"):
                        await route.abort()
                    else:
                        await route.continue_()

                await page.route("**/*", route_handler)

        # Apply stealth measures: try to use an external package if available, otherwise inject our own init script.
        if stealth or deep_stealth:
            applied = False
            try:
                # try to use an installed playwright_stealth package if present
                from playwright_stealth import stealth_async  # type: ignore

                try:
                    await stealth_async(page)
                    applied = True
                    print(f"playwright_stealth applied for port {port} via playwright_stealth package")
                except Exception:
                    # fallback to injection below
                    applied = False
            except Exception:
                applied = False

            if not applied:
                # A conservative stealth init script. Adds common anti-detection patches.
                # If deep_stealth is enabled we will augment this script with client hints and userAgentData.
                stealth_script = r"""
                // Pass the webdriver check
                Object.defineProperty(navigator, 'webdriver', {get: () => false, configurable: true});
                // Mock chrome runtime
                window.chrome = window.chrome || { runtime: {} };
                // Languages
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                // Plugins
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                // Canvas/noise: override toDataURL and getImageData to add slight entropy
                (function() {
                    try {
                        const proto = HTMLCanvasElement.prototype;
                        const toDataURL = proto.toDataURL;
                        proto.toDataURL = function() {
                            try {
                                const ctx = this.getContext('2d');
                                if (ctx) {
                                    const w = this.width, h = this.height;
                                    // draw a 1px random rectangle to perturb the canvas
                                    ctx.fillStyle = 'rgba(' + (Math.floor(Math.random()*20)) + ',0,0,0.01)';
                                    ctx.fillRect(0,0,1,1);
                                }
                            } catch(e) {}
                            return toDataURL.apply(this, arguments);
                        };
                    } catch(e) {}
                })();
                // Platform
                try { Object.defineProperty(navigator, 'platform', {get: () => 'Win32'}); } catch(e) {}
                // Permissions
                try {
                    const _origQuery = window.navigator.permissions.query;
                    window.navigator.permissions.__query = _origQuery;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : _origQuery(parameters)
                    );
                } catch (e) {}
                // Prevent detection via toString calls
                const newProto = window.Element && window.Element.prototype;
                if (newProto) {
                    const toString = newProto.toString;
                    newProto.toString = function() { return toString.call(this); };
                }
                """
                try:
                    await context.add_init_script(stealth_script)
                    print_msg = f"stealth init script injected for port {port}"
                    print(print_msg)
                except Exception as e:
                    print(f"无法注入 stealth 脚本: {e}")

        # deep-stealth: inject userAgentData and client hints headers to be consistent with UA
        if deep_stealth:
            try:
                # prepare JS for navigator.userAgentData and override navigator.userAgent getter
                ua_major = '0'
                try:
                    import re
                    m = re.search(r'Chrome/(\d+)', ua)
                    if m:
                        ua_major = m.group(1)
                except Exception:
                    pass

                brands = [
                    {"brand": "Chromium", "version": ua_major},
                    {"brand": "Google Chrome", "version": ua_major}
                ]

                ua_data_script = f"""
                (() => {{
                    try {{
                        const data = {{
                            brands: {brands},
                            mobile: false,
                            getHighEntropyValues: (hints) => Promise.resolve(Object.assign({{}}, {{architecture: 'x86', model: '', platform: 'Windows', platformVersion: '10.0.0'}}))
                        }};
                        try {{ Object.defineProperty(navigator, 'userAgentData', {{get: () => data}}); }} catch(e) {{ window.navigator.userAgentData = data; }}
                        // override userAgent getter to match UA
                        try {{
                            const ua = {repr(ua)};
                            const _orig = Object.getOwnPropertyDescriptor(Navigator.prototype, 'userAgent');
                            Object.defineProperty(Navigator.prototype, 'userAgent', {{
                                get: function() {{ return ua; }},
                                configurable: true
                            }});
                        }} catch(e){{}}
                    }} catch(e){{}}
                }})();
                """
                await context.add_init_script(ua_data_script)
                # Add approximate client hints headers as extra http headers
                try:
                    ch_ua = f'"Chromium";v="{ua_major}", "Google Chrome";v="{ua_major}"'
                    await context.set_extra_http_headers({
                        "Sec-CH-UA": ch_ua,
                        "Sec-CH-UA-Mobile": "?0",
                        "Sec-CH-UA-Platform": '"Windows"'
                    })
                except Exception:
                    pass
                print(f"deep-stealth: userAgentData + client hints injected for port {port}")
            except Exception as e:
                print(f"deep-stealth injection failed for port {port}: {e}")

        # Lightweight human simulation to make automated runs appear more like a real user.
        async def simulate_human(page):
            try:
                # Get viewport size via evaluate (fallback values if unavailable)
                try:
                    vs = await page.evaluate("() => ({w: window.innerWidth||800, h: window.innerHeight||600})")
                    vw = int(vs.get('w', 800))
                    vh = int(vs.get('h', 600))
                except Exception:
                    vw, vh = 800, 600

                # A few randomized mouse moves
                for _ in range(random.randint(2,5)):
                    x = random.randint(int(vw*0.1), int(vw*0.9))
                    y = random.randint(int(vh*0.1), int(vh*0.9))
                    await page.mouse.move(x, y, steps=random.randint(5,20))
                    await asyncio.sleep(random.uniform(0.1, 0.4))

                # Small scrolls
                for _ in range(random.randint(1,3)):
                    dy = random.randint(50, 400)
                    await page.evaluate(f"window.scrollBy(0, {dy})")
                    await asyncio.sleep(random.uniform(0.2, 0.6))

                # Minor keyboard interaction
                try:
                    await page.keyboard.press('Tab')
                    await asyncio.sleep(random.uniform(0.05, 0.2))
                except Exception:
                    pass
            except Exception:
                pass

        # Enhanced human simulation (Humanize 2.0): Bezier mouse paths, non-uniform typing, scroll randomness
        import math
        def cubic_bezier(p0, p1, p2, p3, t):
            # p* are (x,y), t in [0,1]
            x = (1-t)**3 * p0[0] + 3*(1-t)**2 * t * p1[0] + 3*(1-t) * t**2 * p2[0] + t**3 * p3[0]
            y = (1-t)**3 * p0[1] + 3*(1-t)**2 * t * p1[1] + 3*(1-t) * t**2 * p2[1] + t**3 * p3[1]
            return int(x), int(y)

        async def simulate_human2(page):
            try:
                # viewport
                try:
                    vs = await page.evaluate("() => ({w: window.innerWidth||800, h: window.innerHeight||600})")
                    vw = int(vs.get('w', 800))
                    vh = int(vs.get('h', 600))
                except Exception:
                    vw, vh = 800, 600

                # Bezier mouse movements between random points
                for _ in range(random.randint(2,4)):
                    x0 = random.randint(int(vw*0.1), int(vw*0.9))
                    y0 = random.randint(int(vh*0.1), int(vh*0.9))
                    x3 = random.randint(int(vw*0.1), int(vw*0.9))
                    y3 = random.randint(int(vh*0.1), int(vh*0.9))
                    # control points
                    x1 = x0 + random.randint(-100,100)
                    y1 = y0 + random.randint(-100,100)
                    x2 = x3 + random.randint(-100,100)
                    y2 = y3 + random.randint(-100,100)
                    steps = random.randint(20, 60)
                    for i in range(steps):
                        t = i / (steps - 1)
                        x, y = cubic_bezier((x0,y0),(x1,y1),(x2,y2),(x3,y3), t)
                        # add micro jitter
                        jx = x + random.randint(-2,2)
                        jy = y + random.randint(-2,2)
                        try:
                            await page.mouse.move(jx, jy, steps=1)
                        except Exception:
                            pass
                        # non-uniform timing
                        await asyncio.sleep(random.uniform(0.005, 0.03))

                # Scrolling with small backtrack
                for _ in range(random.randint(1,3)):
                    dy = random.randint(200, 800)
                    await page.evaluate(f"window.scrollBy(0, {dy})")
                    await asyncio.sleep(random.uniform(0.3, 1.2))
                    # small upward backscroll
                    back = random.randint(20, 100)
                    await page.evaluate(f"window.scrollBy(0, -{back})")
                    await asyncio.sleep(random.uniform(0.2, 0.8))

                # Non-uniform typing in a focused input (if any)
                try:
                    # find a visible input or textarea
                    el = await page.query_selector('input[type="text"], textarea')
                    if el:
                        await el.click()
                        sample = 'example test'
                        # type with occasional backspace
                        for ch in sample:
                            await page.keyboard.type(ch)
                            await asyncio.sleep(random.uniform(0.05, 0.22))
                            if random.random() < 0.03:
                                # simulate a small mistake
                                await page.keyboard.press('Backspace')
                                await asyncio.sleep(random.uniform(0.05, 0.12))
                                await page.keyboard.type(random.choice('abcdefghijklmnopqrstuvwxyz'))
                        await asyncio.sleep(random.uniform(0.1,0.4))
                except Exception:
                    pass
            except Exception:
                pass

        # 访问一个显示 IP 的网站来验证（使用较短的超时并在 DOMContentLoaded 后继续）
        try:
            await page.goto("https://www.ip.gs", timeout=timeout, wait_until="domcontentloaded")
            # Optionally run light human simulation after navigation
            if humanize:
                try:
                    await simulate_human(page)
                    print(f"humanize simulation executed for port {port}")
                except Exception:
                    print(f"humanize simulation failed for port {port}")
        except Exception as e:
            print(f"导航到测试页面失败: {e}")

        # 访问一个显示 IP 的网站来验证（使用较短的超时并在 DOMContentLoaded 后继续）
        # 保持窗口开启，让你观察 IP
        try:
            if wait == 0:
                # wait indefinitely until process is interrupted (Ctrl+C)
                print("等待中（按 Ctrl+C 关闭所有窗口）...")
                await asyncio.Event().wait()
            else:
                await asyncio.sleep(wait)
        finally:
            # ensure browser is closed when task is cancelled or finishes
            # persistent context: close context
            try:
                await context.close()
            except Exception:
                pass


async def main_async(ports: List[int], labels: List[str], headless: bool, wait: int, fast: bool, timeout: int, text: bool, stealth: bool, profile_root: str, humanize: bool, incognito: bool, deep_stealth: bool, humanize2: bool, viewport_arg: str = None):
    """Orchestrate multiple browser tasks and forward the optional viewport argument."""
    tasks = []
    for i, port in enumerate(ports):
        label = labels[i] if i < len(labels) else f"节点-{port}"
        tasks.append(run_browser(port, label, headless, wait, fast, timeout, text, stealth, profile_root, humanize, incognito, deep_stealth, humanize2, viewport_arg))
    await asyncio.gather(*tasks)


def parse_args():
    p = argparse.ArgumentParser(description="通过本地 sing-box 代理并行打开多个浏览器窗口以验证出口 IP")
    p.add_argument("--ports", nargs="+", type=int, default=[10001, 10002, 10003, 10004],
                   help="代理端口列表，默认: 10001 10002 10003 10004")
    p.add_argument("--labels", nargs="+", default=["节点-1", "节点-2", "节点-3", "节点-4"],
                   help="每个端口对应的标签（可选）")
    p.add_argument("--wait", type=int, default=0,
                   help="每个窗口保持打开的秒数。传 0 表示一直保持直到按 Ctrl+C（默认：0，表示不自动关闭）")
    p.add_argument("--headless", action="store_true",
                   help="是否以 headless 模式运行（不弹出窗口）")
    p.add_argument("--fast", action="store_true",
                   help="启用快速模式：阻止图片/样式/字体/媒体等资源以加快页面加载（可能影响页面外观，但保留脚本以维持功能）")
    p.add_argument("--text", action="store_true",
                   help="文本模式：仅允许加载页面主体和 XHR/fetch 请求，阻止所有静态资源以只获取文本内容（最省流量）")
    p.add_argument("--timeout", type=int, default=15000,
                   help="页面导航超时时间（毫秒），默认 15000ms")
    p.add_argument("--auto-install", action="store_true",
                   help="如果 Playwright 缺失，自动安装到当前 Python 解释器（可能需要网络和权限）")
    p.add_argument("--stealth", action="store_true",
                   help="启用 stealth 伪装（尝试使用 playwright_stealth 包，否则注入常用 anti-detection 脚本）")
    p.add_argument("--profile-root", type=str, default="./profiles",
                   help="Persistent context 存放目录前缀（默认: ./profiles），每个端口将使用 profile_<port> 子目录")
    p.add_argument("--humanize", action="store_true",
                   help="启用轻量级人类行为模拟（随机鼠标移动/滚动/按键），仅用于减低自动化判定")
    p.add_argument("--incognito", action="store_true",
                   help="使用无痕/临时上下文（不保存 profile），每次为独立会话，适合希望不保留本地状态的场景")
    p.add_argument("--viewport", type=str, default=None,
                   help="可选固定视口 WxH，例如 1366x768；传 none（小写）表示禁用 viewport 以使用窗口默认大小（visible 模式下推荐）")
    p.add_argument("--deep-stealth", action="store_true",
                   help="启用深度指纹伪装：同步 userAgentData、client hints、WebGL/Canvas 微扰等（实验性）")
    p.add_argument("--humanize2", action="store_true",
                   help="启用增强行为模拟：贝塞尔鼠标轨迹、非匀速输入、滚动回弹等")
    return p.parse_args()


def main():
    args = parse_args()

    try:
        ensure_playwright(auto_install=args.auto_install)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    # Run the asyncio main
    try:
        asyncio.run(main_async(args.ports, args.labels, args.headless, args.wait, args.fast, args.timeout, args.text, args.stealth, args.profile_root, args.humanize, args.incognito, args.deep_stealth, args.humanize2, args.viewport))
    except Exception as e:
        print(f"运行脚本时出现错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()