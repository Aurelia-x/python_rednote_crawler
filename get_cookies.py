import json
import time
import os
from playwright.sync_api import sync_playwright

# ================= 配置区域 =================
COOKIES_FILE = 'cookies.json'
# ===========================================

def get_cookies_manually():
    print("正在启动浏览器...")
    with sync_playwright() as p:
        # 启动 Chromium 浏览器
        # headless=False: 显示浏览器界面
        # args=["--start-maximized"]: 启动时最大化窗口
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        
        # 创建上下文
        # no_viewport=True: 禁用默认的 1280x720 视口限制，让网页内容自适应窗口大小
        context = browser.new_context(no_viewport=True)
        
        # 注入反爬脚本: 隐藏 navigator.webdriver 属性，防止被识别为自动化工具
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = context.new_page()
        
        print("正在打开小红书...")
        try:
            page.goto("https://www.xiaohongshu.com")
        except Exception as e:
            print(f"打开网页出错: {e}")
            return

        print("\n" + "="*60)
        print("【手动提取 Cookie 模式 】")
        print("1. 浏览器已打开，请在浏览器中进行扫码登录/手机号登录")
        print("2. 务必等待页面完全加载，看到首页瀑布流或个人中心")
        print("3. 确认登录成功后，请回到本窗口按回车键")
        print("="*60 + "\n")

        # 阻塞等待用户输入
        input(">>> 确认已登录成功？(按回车键提取并保存): ")

        # 获取当前上下文的所有 Cookies
        cookies = context.cookies()

        # 验证逻辑
        if not cookies:
            print("[×] 未获取到任何 Cookie，请重试。")
        else:
            # 检查是否包含核心凭证 'web_session'
            has_session = any(c.get('name') == 'web_session' for c in cookies)
            
            if has_session:
                with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cookies, f, indent=4)
                print(f"\n[√] 成功！已保存 {len(cookies)} 个 Cookie 到 {COOKIES_FILE}")
                print("[√] 包含核心凭证: web_session")
                print("现在你可以运行 xhs_crawler.py 或 xhs_publisher.py 了。")
            else:
                print(f"\n[!] 获取了 {len(cookies)} 个 Cookie，但缺失 'web_session'。")
                print("可能登录未完成，或者小红书未写入关键 Cookie。")
                print("建议：在浏览器中刷新页面，确保能看到个人头像，然后重新运行此脚本。")
                
                # 即使没有 web_session 也尝试保存，以供调试或部分功能使用
                with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cookies, f, indent=4)
                print(f"已强制保存当前 Cookie 到 {COOKIES_FILE} (可能无效)")

        print("\n浏览器将在 3 秒后关闭...")
        time.sleep(3)
        browser.close()

if __name__ == "__main__":
    get_cookies_manually()
