import os
import time
import json
import requests
import random
import re
import pyautogui
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# ================= 配置区域 =================
# 设置环境变量忽略 SSL 验证
os.environ['WDM_SSL_VERIFY'] = '0'

# 搜索关键词列表
KEYWORDS = ["网购 拆快递 退货 六宫格漫画"]

# 文件保存路径配置
SAVE_DIR = os.path.join("data", "images")      # 图片保存目录
JSON_PATH = os.path.join("data", "raw_data.json") # 爬取结果元数据文件
COOKIES_PATH = "cookies.json"                  # Cookie 保存文件
MAX_NOTES = 1                                 # 最大爬取笔记数量
# ===========================================

def init_driver():
    """
    初始化 Selenium Edge 驱动
    """
    options = webdriver.EdgeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--log-level=3") # 屏蔽控制台常规日志输出
    
    # 移除自动化特征，并屏蔽 DevTools 日志
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    
    try:
        driver_path = EdgeChromiumDriverManager().install()
        service = Service(driver_path)
    except Exception as e:
        print(f"[-] 自动下载驱动失败: {e}")
        if os.path.exists("msedgedriver.exe"):
            print("[+] 使用本地 msedgedriver.exe")
            service = Service("msedgedriver.exe")
        else:
            raise e

    driver = webdriver.Edge(service=service, options=options)
    
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"}
    )
    return driver

def click_with_pyautogui(driver, element):
    """
    使用 PyAutoGUI 进行物理鼠标点击
    注意：这会移动用户的真实鼠标，执行期间请勿操作鼠标
    """
    try:
        # 1. 滚动元素到视图中心
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});", element)
        time.sleep(0.5)

        # 2. 获取浏览器窗口位置
        win_rect = driver.get_window_rect()
        win_x = win_rect['x']
        win_y = win_rect['y']

        # 3. 获取浏览器 UI 高度 (地址栏、标签页等)
        # window.outerHeight - window.innerHeight 大致等于顶部 UI 高度
        nav_height = driver.execute_script("return window.outerHeight - window.innerHeight;")
        
        # 4. 获取元素相对于视口的位置
        elem_rect = driver.execute_script("return arguments[0].getBoundingClientRect();", element)
        elem_left = elem_rect['left']
        elem_top = elem_rect['top']
        elem_width = elem_rect['width']
        elem_height = elem_rect['height']

        # 5. 计算目标屏幕坐标
        # X = 窗口X + 元素视口左边距 + 元素一半宽度
        target_x = win_x + elem_left + (elem_width / 2)
        
        # Y = 窗口Y + 导航栏高度 + 元素视口上边距 + 元素一半高度
        # 注意：这里的 nav_height 只是估算，有时可能不准，但通常足够
        target_y = win_y + nav_height + elem_top + (elem_height / 2)

        # 边界检查 (防止点到屏幕外)
        screen_w, screen_h = pyautogui.size()
        if not (0 <= target_x <= screen_w and 0 <= target_y <= screen_h):
            print(f"  - 目标坐标 ({target_x}, {target_y}) 超出屏幕范围，放弃物理点击")
            return False

        # 6. 移动鼠标并点击
        # 缓动移动，看起来更像真人
        pyautogui.moveTo(target_x, target_y, duration=0.5, tween=pyautogui.easeInOutQuad)
        pyautogui.click()
        return True
        
    except Exception as e:
        print(f"  - PyAutoGUI 点击异常: {e}")
        return False

def load_cookies(driver):
    """
    加载本地保存的 Cookie
    """
    if os.path.exists(COOKIES_PATH):
        try:
            with open(COOKIES_PATH, "r", encoding="utf-8") as f:
                content = f.read()
                if not content:
                    return False
                cookie_list = json.loads(content)
                
            if not cookie_list:
                print("Cookie 列表为空，视为无效")
                return False
                
            has_session = any(c.get('name') == 'web_session' for c in cookie_list)
            if not has_session:
                print("Cookie 中缺失 web_session 核心凭证，视为无效")
                return False
                
            driver.get("https://www.xiaohongshu.com")
            time.sleep(2)
            
            for ck in cookie_list:
                ck.pop("sameSite", None)
                ck.pop("storeId", None)
                if ck.get("domain", "").startswith("."):
                    ck["domain"] = ck["domain"][1:]
                try:
                    driver.add_cookie(ck)
                except:
                    pass
            
            driver.refresh()
            time.sleep(2)
            return True
        except Exception as e:
            print(f"加载 Cookie 失败: {e}")
            return False
    return False

def check_login(driver):
    """
    检查登录状态
    """
    print("\n" + "-"*40)
    print("请检查浏览器是否已登录小红书。")
    print("如果未登录，请手动扫码登录。")
    print("登录完成后，请按回车键继续...")
    print("-"*40 + "\n")
    
    try:
        max_retries = 60
        for _ in range(max_retries):
            cookies = driver.get_cookies()
            has_session = any(c.get('name') == 'web_session' for c in cookies)
            
            has_avatar = False
            try:
                if driver.find_elements(By.ID, "user-avatar-container") or \
                   driver.find_elements(By.CLASS_NAME, "avatar-container") or \
                   driver.find_elements(By.XPATH, "//div[contains(@class, 'user-avatar')]") or \
                   driver.find_elements(By.XPATH, "//li[@class='user-side-bar']"):
                    has_avatar = True
            except:
                pass

            if has_session or has_avatar:
                print("检测到已登录状态！")
                time.sleep(2)
                
                cookies = driver.get_cookies()
                if cookies:
                    if any(c.get('name') == 'web_session' for c in cookies):
                        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                            json.dump(cookies, f, indent=4)
                        print(f"Cookie 已保存至 {COOKIES_PATH}")
                        return
                    else:
                        print("警告：Cookie 缺失 web_session")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"登录检测出错: {e}")

def download_image(url, note_id, index):
    """
    下载图片
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            "Referer": "https://www.xiaohongshu.com/"
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            ext = ".jpg"
            if "webp" in url:
                ext = ".webp"
                
            filename = f"xhs_{note_id}_{index:02d}{ext}"
            filepath = os.path.join(SAVE_DIR, filename)
            
            with open(filepath, "wb") as f:
                f.write(response.content)
            return filename, filepath
    except Exception as e:
        print(f"下载失败: {e}")
    return None, None

def scrape_note_modal(driver, note_id):
    """
    抓取当前弹窗中的笔记详情（标题、正文、所有图片）
    """
    data = {
        "title": "",
        "content": "",
        "images": [],
        "source_url": driver.current_url
    }
    
    try:
        # 等待弹窗内容加载
        print(f"  - 正在等待详情页加载... ({driver.current_url})")
        # 增加更多选择器以提高兼容性
        wait_selectors = [
            "#detail-title", 
            ".note-content .title", 
            ".note-container", 
            "#noteContainer", 
            ".interaction-container"
        ]
        xpath_union = " | ".join([f"//*[contains(@class, '{s.replace('.', '')}')]" if s.startswith('.') else f"//*[@id='{s.replace('#', '')}']" for s in wait_selectors])
        # 简化：直接检测核心元素
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'note-content')] | //div[@id='noteContainer'] | //div[contains(@class, 'interaction')]"))
        )
        time.sleep(random.uniform(1, 2))
        
        # 1. 提取标题
        try:
            title_el = driver.find_element(By.ID, "detail-title")
            data["title"] = title_el.text.strip()
        except:
            try:
                title_el = driver.find_element(By.CSS_SELECTOR, ".note-content .title")
                data["title"] = title_el.text.strip()
            except:
                data["title"] = "无标题"
                
        # 2. 提取正文
        try:
            desc_el = driver.find_element(By.ID, "detail-desc")
            data["content"] = desc_el.text.strip()
        except:
            try:
                desc_el = driver.find_element(By.CSS_SELECTOR, ".note-content .desc")
                data["content"] = desc_el.text.strip()
            except:
                data["content"] = ""

        # 3. 提取图片（多图）
        img_urls = []
        try:
            # 查找所有 slide 的 div，背景图通常在 style 中
            slides = driver.find_elements(By.CSS_SELECTOR, ".swiper-wrapper .swiper-slide")
            
            for slide in slides:
                # 尝试从 style 属性提取 background-image
                style = slide.get_attribute("style")
                if style and "url(" in style:
                    # 提取 url("...") 中的内容
                    match = re.search(r'url\("?(.+?)"?\)', style)
                    if match:
                        url = match.group(1)
                        if url not in img_urls:
                            img_urls.append(url)
                else:
                    # 或者是 img 标签
                    try:
                        img = slide.find_element(By.TAG_NAME, "img")
                        src = img.get_attribute("src")
                        if src and src not in img_urls:
                            img_urls.append(src)
                    except:
                        pass
                        
            # 如果没找到 swiper，可能是单图，直接找 cover
            if not img_urls:
                 # 尝试多种选择器
                 selectors = [".note-content .cover img", ".image-container img", "#noteContainer img"]
                 for sel in selectors:
                     try:
                         cover = driver.find_element(By.CSS_SELECTOR, sel)
                         src = cover.get_attribute("src")
                         if src:
                             img_urls.append(src)
                             break
                     except:
                         pass

        except Exception as e:
            print(f"提取图片链接失败: {e}")

        print(f"  - 标题: {data['title'][:10]}...")
        print(f"  - 找到 {len(img_urls)} 张图片")
        
        # 4. 下载图片
        for i, url in enumerate(img_urls):
            fname, fpath = download_image(url, note_id, i+1)
            if fpath:
                data["images"].append(fpath)
                
    except Exception as e:
        print(f"抓取弹窗内容出错: {e}")
        
    return data

def run_crawler():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)
        
    try:
        driver = init_driver()
    except Exception as e:
        print(f"驱动初始化失败: {e}")
        return
    
    # 登录流程
    is_logged_in = load_cookies(driver)
    if not is_logged_in:
        driver.get("https://www.xiaohongshu.com")
        check_login(driver)
    
    all_data = {}
    note_count = 0
    
    for keyword in KEYWORDS:
        if note_count >= MAX_NOTES:
            break
            
        print(f"\n正在搜索: {keyword}")
        search_url = f"https://www.xiaohongshu.com/search_result?keyword={keyword}&source=web_search_result_notes"
        driver.get(search_url)
        time.sleep(3)
        
        try:
            # 滚动几次加载更多
            for _ in range(3):
                driver.execute_script("window.scrollBy(0, 1000)")
                time.sleep(1.5)
            
            # 查找所有笔记卡片
            # 通常是 section.note-item 或 .feeds-container .note-item
            # 使用更通用的选择器，查找包含 href 的 a 标签，且 href 包含 /explore/
            # 为了点击，我们最好找到其外层的卡片或者直接点 a 标签
            # 但是直接获取所有 element 列表容易 stale，所以采用“查找-点击-返回”或者“按索引查找”策略
            # 这里使用：先收集所有链接作为 ID，然后每次循环重新查找对应元素进行点击
            
            # 1. 查找所有笔记卡片
            # 采用索引遍历方式，避免 stale element 和定位失败问题
            cards_locator = (By.XPATH, "//a[contains(@href, '/explore/')]")
            initial_cards = driver.find_elements(*cards_locator)
            card_count = len(initial_cards)
            print(f"找到 {card_count} 个潜在笔记")
            
            # 2. 遍历点击
            for i in range(card_count):
                if note_count >= MAX_NOTES:
                    break
                    
                # 重新在页面中查找列表
                try:
                    # 确保我们在搜索结果页
                    if "search_result" not in driver.current_url:
                        print("[-] 当前不在搜索结果页，尝试重新加载搜索页...")
                        driver.get(search_url)
                        time.sleep(3)
                        # 重新滚动加载（如果需要）
                        # driver.execute_script("window.scrollBy(0, 1000)")
                        # time.sleep(1)

                    current_cards = driver.find_elements(*cards_locator)
                    if i >= len(current_cards):
                        print(f"[-] 索引 {i} 超出当前列表长度 {len(current_cards)}，跳过")
                        continue
                        
                    card = current_cards[i]
                    href = card.get_attribute("href")
                    explore_id = href.split('/')[-1].split('?')[0] if href else "unknown"
                    
                    # 滚动到元素可见
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});", card)
                    time.sleep(1)
                    
                    print(f"\n[{note_count+1}] 点击笔记: {explore_id}")
                    
                    # 尝试多种点击策略
                    click_success = False
                    
                    # 策略1: 常规 Selenium 点击
                    try:
                        card.click()
                        click_success = True
                    except Exception as e1:
                        print(f"  - 常规点击失败: {e1}")
                        
                        # 策略2: PyAutoGUI 物理点击 (模拟真人)
                        print("  - 尝试 PyAutoGUI 物理点击...")
                        if click_with_pyautogui(driver, card):
                            click_success = True
                        else:
                            # 策略3: JS 强制点击 (最后的兜底)
                            print("  - 物理点击失败，尝试 JS 强制点击...")
                            try:
                                driver.execute_script("arguments[0].click();", card)
                                click_success = True
                            except Exception as e3:
                                print(f"  - JS 点击也失败: {e3}")

                    if not click_success:
                        print("[-] 所有点击方式均失败，跳过此笔记")
                        continue
                    
                    # 等待页面响应（弹窗或跳转）
                    time.sleep(3)
                    
                    # 检查是否遇到 404 或 错误页
                    if "404" in driver.current_url or "error" in driver.current_url:
                        print(f"[-] 无法查看笔记 (可能是 Cookie 失效或反爬): {driver.current_url}")
                        driver.back()
                        time.sleep(2)
                        continue

                    # 生成 ID
                    note_id = f"note_{note_count+1}"
                    
                    # 抓取内容
                    note_data = scrape_note_modal(driver, note_id)
                    
                    # 保存数据
                    if note_data["images"]:
                        all_data[note_id] = note_data
                        note_count += 1
                        print(f"[+] 成功抓取")
                    else:
                        print("[-] 无有效内容")
                        
                    # 关闭弹窗或返回
                    # 1. 尝试按 ESC 关闭弹窗
                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(1)
                    
                    # 2. 检查是否还在详情页（URL 包含 /explore/），如果是，说明是全页跳转或 ESC 无效，需要后退
                    if "/explore/" in driver.current_url and "search_result" not in driver.current_url:
                        print("  - 检测到页面跳转，执行后退操作")
                        driver.back()
                        time.sleep(2)
                    
                except Exception as e:
                    print(f"处理笔记时出错: {e}")
                    # 确保恢复到列表页
                    if "search_result" not in driver.current_url:
                         driver.back()
                         time.sleep(2)
                    continue
            
        except Exception as e:
            print(f"搜索页处理失败: {e}")
            continue

    try:
        driver.quit()
    except:
        pass
    
    # 保存结果
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)
        
    print(f"\n爬取结束，共保存 {len(all_data)} 条笔记数据。")
    print(f"数据已保存至: {JSON_PATH}")
if __name__ == "__main__":
    run_crawler()
