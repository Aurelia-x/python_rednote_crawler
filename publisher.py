import sys
import time
import json
import os
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# ================= 配置区域 =================
# 设置环境变量忽略 SSL 验证（解决部分网络环境下无法下载驱动的问题）
os.environ['WDM_SSL_VERIFY'] = '0'

# 文件路径配置
COOKIES_PATH = "cookies.json"                  # Cookie 保存文件
DATA_PATH = os.path.join("data", "result.json") # 待发布数据文件
# ===========================================

class XiaoHongShuPublisher:
    def __init__(self):
        """
        初始化发布器
        功能：
        1. 配置浏览器环境
        2. 启动 Edge 浏览器
        3. 注入反爬虫 JS 代码
        """
        options = webdriver.EdgeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--log-level=3") # 屏蔽日志
        # 移除自动化标志，并屏蔽 DevTools 日志
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option("useAutomationExtension", False)
        
        try:
            # 尝试自动下载驱动
            driver_path = EdgeChromiumDriverManager().install()
            service = Service(driver_path)
        except Exception as e:
            print(f"[-] 自动下载驱动失败: {e}")
            # 降级方案：使用本地驱动
            if os.path.exists("msedgedriver.exe"):
                print("[+] 检测到本地 msedgedriver.exe，尝试使用...")
                service = Service("msedgedriver.exe")
            else:
                print("\n" + "="*50)
                print("【严重错误】Edge 驱动自动下载失败。请手动下载 msedgedriver.exe 并放到当前目录。")
                print("下载地址: https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/")
                print("="*50 + "\n")
                raise e

        self.browser = webdriver.Edge(service=service, options=options)
        
        # 绕过 webdriver 检测（防止被识别为自动化工具）
        self.browser.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"}
        )

    def check_login_status(self):
        """
        智能检测登录状态（复用 crawler.py 的核心逻辑）
        返回: True (已登录), False (未登录)
        """
        # 1. 检查 Cookie 中是否包含 web_session
        cookies = self.browser.get_cookies()
        has_session = any(c.get('name') == 'web_session' for c in cookies)
        
        # 2. 检查页面元素（头像等）
        has_avatar = False
        try:
            if self.browser.find_elements(By.ID, "user-avatar-container") or \
               self.browser.find_elements(By.CLASS_NAME, "avatar-container") or \
               self.browser.find_elements(By.XPATH, "//div[contains(@class, 'user-avatar')]") or \
               self.browser.find_elements(By.XPATH, "//li[@class='user-side-bar']"):
                has_avatar = True
        except:
            pass

        return has_session or has_avatar

    def login(self):
        """
        登录流程控制
        1. 尝试加载本地 Cookie
        2. 如果 Cookie 无效或未登录，进入扫码等待循环
        3. 登录成功后自动更新本地 Cookie
        """
        print("\n=== 登录小红书 ===")
        self.browser.get("https://creator.xiaohongshu.com/publish/publish")
        time.sleep(2)
        
        # --- 步骤 1: 尝试加载 Cookie ---
        if os.path.exists(COOKIES_PATH):
            try:
                with open(COOKIES_PATH, "r", encoding="utf-8") as f:
                    cookie_content = f.read()
                    if cookie_content:
                        cookie_list = json.loads(cookie_content)
                        
                        # 1. 检查列表是否为空
                        if not cookie_list:
                            print("Cookie 列表为空，跳过注入")
                            raise ValueError("Cookie List is empty")
                            
                        # 2. 检查 web_session
                        has_session = any(c.get('name') == 'web_session' for c in cookie_list)
                        if not has_session:
                            print("Cookie 缺失 web_session，跳过注入")
                            raise ValueError("Missing web_session")
                            
                        print("正在注入 Cookie...")
                        
                        # 清除当前域名的 Cookie，防止冲突
                        self.browser.delete_all_cookies()
                        
                        for ck in cookie_list:
                            ck.pop("sameSite", None)
                            ck.pop("storeId", None)
                            if ck.get("domain", "").startswith("."):
                                ck["domain"] = ck["domain"][1:]
                            try:
                                self.browser.add_cookie(ck)
                            except:
                                pass
                        
                        print("Cookie 注入完成，刷新页面...")
                        self.browser.refresh()
                        time.sleep(3)
            except Exception as e:
                print(f"Cookie 加载失败: {e}")
        else:
            print("未找到 cookies.json，准备手动登录。")

        # --- 步骤 2: 验证登录状态 ---
        if self.check_login_status():
            print("登录验证成功！")
            return

        # --- 步骤 3: 如果未登录，等待用户扫码 ---
        print("\n------------------------------------------------")
        print("检测到未登录，请在浏览器中扫码登录。")
        print("程序将自动轮询检测登录状态...")
        print("------------------------------------------------\n")
        
        max_retries = 60 # 等待 60 秒
        for i in range(max_retries):
            if self.check_login_status():
                print("\n检测到已登录状态！")
                time.sleep(2) # 等待状态稳定
                
                # 保存最新的 cookie
                cookies = self.browser.get_cookies()
                if cookies:
                    if any(c.get('name') == 'web_session' for c in cookies):
                        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                            json.dump(cookies, f, indent=4)
                        print(f"Cookie 已更新并保存至 {COOKIES_PATH} (包含 {len(cookies)} 条数据)")
                    else:
                         print("警告：检测到登录但 Cookie 缺失 web_session，暂不保存")
                return
            
            sys.stdout.write(f"\r等待登录中... {i+1}/{max_retries}s")
            sys.stdout.flush()
            time.sleep(1)
            
        print("\n\n等待超时！请手动确认登录状态。")
        input("如果已登录，请按回车键继续...")

    def publish_one(self, images, title, content):
        """
        发布单篇笔记
        参数:
            images: 图片绝对路径列表
            title: 笔记标题
            content: 笔记正文
        返回: True (发布成功), False (失败)
        """
        print(f"\n--- 开始发布: {title} ---")
        
        # 1. 确保在发布页
        if "publish" not in self.browser.current_url:
            self.browser.get("https://creator.xiaohongshu.com/publish/publish")
            time.sleep(5)
            
        # 2. 切换到“上传图文” Tab (如果是视频默认页的话)
        try:
            # 查找包含“上传图文”文字的元素并点击
            tab = WebDriverWait(self.browser, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), '上传图文')]"))
            )
            tab.click()
            time.sleep(1)
        except:
            # 如果找不到，可能已经是图文模式，或者是新版界面
            pass

        # 3. 上传图片
        try:
            # 寻找 input type=file 元素
            upload_input = WebDriverWait(self.browser, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
            )
            # send_keys 支持多文件，路径之间用换行符分隔（大多数浏览器支持）
            file_paths = "\n".join(images)
            upload_input.send_keys(file_paths)
            print(f"图片上传中: {len(images)} 张图片")
            
            # 等待上传完成（这里简单等待5秒，实际可以检测加载条）
            time.sleep(5) 
        except Exception as e:
            print(f"上传图片失败: {e}")
            return False

        # 4. 输入标题
        try:
            # 使用 CSS 选择器定位标题输入框
            # .title-container input 是常见结构，input[placeholder*='标题'] 是备选
            title_input = WebDriverWait(self.browser, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".title-container input, input[placeholder*='标题']"))
            )
            
            # 使用 JS 清空输入框，比 clear() 更可靠
            self.browser.execute_script("arguments[0].value = '';", title_input)
            title_input.send_keys(title)
            print("标题已输入")
        except Exception as e:
            print(f"输入标题失败: {e}")
            return False

        # 5. 输入正文
        try:
            # 正文通常是富文本编辑器，定位 contenteditable 区域
            content_div = WebDriverWait(self.browser, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".tiptap.ProseMirror, #post-textarea"))
            )
            content_div.click()
            content_div.send_keys(content)
            print("正文已输入")
        except Exception as e:
            print(f"输入正文失败: {e}")
            return False

        # 6. 点击发布
        try:
            print("准备发布...")
            # 随机等待，模拟人工思考/检查时间
            time.sleep(random.randint(2, 5))
            
            # 定位发布按钮：排除掉 class 包含 disabled 的按钮
            publish_btn = self.browser.find_element(By.XPATH, "//button[contains(text(), '发布') and not(contains(@class, 'disabled'))]")
            
            # ⚠️⚠️⚠️ 安全起见，默认注释掉实际点击动作 ⚠️⚠️⚠️
            # publish_btn.click() 
            print(">>> [模拟模式] 点击了发布按钮 (为防止误发，实际点击代码已注释)")
            print(">>> 如需真实发布，请取消 publisher.py 第256行附近的注释")
            
            return True 
        except Exception as e:
            print(f"点击发布按钮失败: {e}")
            return False

    def run(self):
        """
        主运行逻辑
        """
        if not os.path.exists(DATA_PATH):
            print("未找到 result.json，请先运行 processor.py 生成数据")
            return

        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 执行登录
        self.login()
        
        count = 0
        # 遍历数据进行发布
        for key, item in data.items():
            if count >= 3: # ⚠️ 安全限制：每次运行只发3条
                print("达到单次运行上限(3条)，停止运行。")
                break
                
            # 构建标题
            # 优先使用 processor 生成的 title，如果太长则截取
            raw_title = item.get('title', '')
            if not raw_title:
                raw_title = item.get('text', '')[:10]
            
            post_title = "【网购趣事】" + raw_title
            if len(post_title) > 20: 
                 post_title = post_title[:20] + "..."

            post_content = item['text']
            
            # 传入图片列表
            success = self.publish_one(item['images'], post_title, post_content)
            if success:
                print(f"{key} 发布流程完成")
                count += 1
                
                # 随机等待 10-20 秒，模拟人工间隔
                wait_time = random.randint(10, 20)
                print(f"等待 {wait_time} 秒...")
                time.sleep(wait_time)
                
                # 刷新页面，清空表单，准备下一条
                self.browser.refresh()
                time.sleep(3)
            else:
                print(f"{key} 发布失败，跳过")

        print("所有任务结束")
        input("按回车关闭浏览器...")
        self.browser.quit()

if __name__ == "__main__":
    bot = XiaoHongShuPublisher()
    bot.run()
