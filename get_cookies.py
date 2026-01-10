import json
import time
import os
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# ================= 配置区域 =================
# 设置环境变量忽略 SSL 验证
os.environ['WDM_SSL_VERIFY'] = '0'
COOKIES_FILE = 'cookies.json'
# ===========================================

def get_cookies_manually():
    print("正在启动浏览器...")
    options = webdriver.EdgeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--log-level=3") # 屏蔽日志
    # 移除自动化特征，防止登录界面被屏蔽，同时屏蔽日志
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    
    try:
        driver_path = EdgeChromiumDriverManager().install()
        service = Service(driver_path)
    except Exception as e:
        print(f"自动下载驱动失败: {e}")
        if os.path.exists("msedgedriver.exe"):
            print("使用本地 msedgedriver.exe")
            service = Service("msedgedriver.exe")
        else:
            print("错误：未找到驱动程序")
            return

    driver = webdriver.Edge(service=service, options=options)
    
    # 注入反爬脚本
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"}
    )
    
    print("正在打开小红书...")
    driver.get("https://www.xiaohongshu.com")
    
    print("\n" + "="*60)
    print("【手动提取 Cookie 模式】")
    print("1. 浏览器已打开，请在浏览器中进行扫码登录/手机号登录")
    print("2. 务必等待页面完全加载，看到首页瀑布流或个人中心")
    print("3. 确认登录成功后，请回到本窗口按回车键")
    print("="*60 + "\n")
    
    input(">>> 确认已登录成功？(按回车键提取并保存): ")
    
    # 获取 Cookies
    cookies = driver.get_cookies()
    
    # 验证
    if not cookies:
        print("[×] 未获取到任何 Cookie，请重试。")
    else:
        # 检查核心凭证
        has_session = any(c.get('name') == 'web_session' for c in cookies)
        if has_session:
            with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=4)
            print(f"\n[√] 成功！已保存 {len(cookies)} 个 Cookie 到 {COOKIES_FILE}")
            print("[√] 包含核心凭证: web_session")
            print("现在你可以运行 crawler.py 或 publisher.py 了。")
        else:
            print(f"\n[!] 获取了 {len(cookies)} 个 Cookie，但缺失 'web_session'。")
            print("可能登录未完成，或者小红书未写入关键 Cookie。")
            print("建议：在浏览器中刷新页面，确保能看到个人头像，然后重新运行此脚本。")
            
            # 即使没有 web_session 也尝试保存，以供调试
            with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=4)
            print(f"已强制保存当前 Cookie 到 {COOKIES_FILE} (可能无效)")

    print("\n浏览器将在 3 秒后关闭...")
    time.sleep(3)
    driver.quit()

if __name__ == "__main__":
    get_cookies_manually()
