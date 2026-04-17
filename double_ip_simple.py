import argparse
import asyncio
import subprocess
import sys
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


async def run_browser(port: int, label: str, headless: bool, wait: int, fast: bool, timeout: int, text: bool):
    # import inside function so the script can show a helpful message before import failure
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        # 启动浏览器，并连接到 Sing-box 开启的对应端口
        # 10001 对应美国，10002 对应俄罗斯（根据你的配置）
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            proxy={"server": f"http://127.0.0.1:{port}"}
        )
        page = await context.new_page()

        print(f"正在打开 {label} 窗口 (端口: {port})... headless={headless} fast={fast}")
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

        # 访问一个显示 IP 的网站来验证（使用较短的超时并在 DOMContentLoaded 后继续）
        try:
            await page.goto("https://www.ip.gs", timeout=timeout, wait_until="domcontentloaded")
        except Exception as e:
            print(f"导航到测试页面失败: {e}")

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
            await browser.close()


async def main_async(ports: List[int], labels: List[str], headless: bool, wait: int, fast: bool, timeout: int, text: bool):
    tasks = []
    for i, port in enumerate(ports):
        label = labels[i] if i < len(labels) else f"节点-{port}"
        tasks.append(run_browser(port, label, headless, wait, fast, timeout, text))
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
        asyncio.run(main_async(args.ports, args.labels, args.headless, args.wait, args.fast, args.timeout, args.text))
    except Exception as e:
        print(f"运行脚本时出现错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
