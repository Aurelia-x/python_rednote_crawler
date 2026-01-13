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
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        
        # 创建上下文
        context = browser.new_context(no_viewport=True)
        
        # 注入反爬脚本
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = context.new_page()
        
        print("正在打开小红书...")
        try:
            page.goto("https://www.xiaohongshu.com")
        except Exception as e:
            print(f"打开网页出错: {e}")
            return

        print("\n" + "="*60)
        print("【手动提取 Cookie 模式 (Playwright 版)】")
        print("1. 浏览器已打开，请在浏览器中进行扫码登录/手机号登录")
        print("2. 务必等待页面完全加载，看到首页瀑布流或个人中心")
        print("3. 确认登录成功后，请回到本窗口按回车键")
        print("="*60 + "\n")

        input(">>> 确认已登录成功？(按回车键提取并保存): ")

        # 获取当前上下文的所有 Cookies
        cookies = context.cookies()

        # 验证逻辑
        if not cookies:
            print("[×] 未获取到任何 Cookie，请重试。")
        else:
            # 检查是否包含核心凭证 'web_session'
            has_session = any(c.get('name') == 'web_session' for c in cookies)
            
            # --- 关键修复：统一 Cookie 字段格式 ---
            # Playwright 获取的 Cookie 包含 'sameSite' 等字段，格式与 Selenium 略有不同
            # xhs_crawler.py 使用 Playwright 注入 Cookie，格式是兼容的
            # 但为了保险起见，我们确保字段名称与标准一致
            
            # 过滤掉不需要的字段，只保留 Playwright context.add_cookies() 支持的标准字段
            # 标准字段: name, value, url, domain, path, expires, httpOnly, secure, sameSite
            valid_keys = {'name', 'value', 'url', 'domain', 'path', 'expires', 'httpOnly', 'secure', 'sameSite'}
            cleaned_cookies = []
            for c in cookies:
                cleaned_c = {k: v for k, v in c.items() if k in valid_keys}
                # 确保 sameSite 值是 Playwright 接受的 "Strict", "Lax", "None"
                if 'sameSite' in cleaned_c:
                     # Playwright 返回的 sameSite 可能是 "Lax" 等，通常可以直接使用
                     pass
                cleaned_cookies.append(cleaned_c)
            # ------------------------------------

            if has_session:
                with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cleaned_cookies, f, indent=4)
                print(f"\n[√] 成功！已保存 {len(cleaned_cookies)} 个 Cookie 到 {COOKIES_FILE}")
                print("[√] 包含核心凭证: web_session")
                print("现在你可以运行 xhs_crawler.py 或 xhs_publisher.py 了。")
            else:
                print(f"\n[!] 获取了 {len(cookies)} 个 Cookie，但缺失 'web_session'。")
                print("可能登录未完成，或者小红书未写入关键 Cookie。")
                print("建议：在浏览器中刷新页面，确保能看到个人头像，然后重新运行此脚本。")
                
                with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cleaned_cookies, f, indent=4)
                print(f"已强制保存当前 Cookie 到 {COOKIES_FILE} (可能无效)")

        print("\n浏览器将在 3 秒后关闭...")
        time.sleep(3)
        browser.close()

if __name__ == "__main__":
    get_cookies_manually()
