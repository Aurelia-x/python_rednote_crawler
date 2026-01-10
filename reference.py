import sys
import time
import json
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium import webdriver

#浏览器配置信息如下
options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

Browser = webdriver.Chrome(options=options)

Browser.execute_cdp_cmd(
    "Page.addScriptToEvaluateOnNewDocument",
    {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"}
)

#cookies 文件路径
cookies_path = "cookies.json"   #可通过浏览器插件Cookie-Editor导出

# 笔记发布内容
PathImage = r"C:\Users\86135\Desktop\数学建模\6.jpg"    #请写图片的绝对路径
title = "我的第一个笔记"
describe = "我爱python编程实践"


def wait_and_find(by, selector, timeout=10):
    try:
        element = WebDriverWait(Browser, timeout).until(
            EC.presence_of_element_located((by, selector))
        )
        return element
    except:
        return None

# =============================================
#   使用 cookie 登录
# =============================================
def login():
    print("\n=== 使用 Cookie 自动登录小红书 ===")

    # Step1: 先访问一次主页，不然无法写入 cookie
    Browser.get("https://www.xiaohongshu.com")
    time.sleep(1)

    # Step2: 读取 cookie.json
    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            cookie_list = json.load(f)
    except Exception as e:
        print(" 无法读取 cookie.json，请确保文件存在")
        print(e)
        input("按回车退出...")
        sys.exit(1)

    # Step3: 写入 cookie
    for ck in cookie_list:
        try:
            # 删除 Selenium 不支持的字段
            ck.pop("sameSite", None)
            ck.pop("storeId", None)

            # 修复 domain：".xiaohongshu.com" → "xiaohongshu.com"
            if ck.get("domain", "").startswith("."):
                ck["domain"] = ck["domain"][1:]

            Browser.add_cookie(ck)

        except Exception as e:
            print(f" cookie 写入失败：{ck.get('name')}（正常现象，可能是 httpOnly）")

    print("✓ Cookie 写入完成，刷新以验证登录状态...")
    time.sleep(1)

    # Step4: 刷新到创作者后台
    Browser.get("https://creator.xiaohongshu.com/publish/publish")
    time.sleep(1)

    if "login" in Browser.current_url:
        print(" Cookie 登录失败，仍然跳转到登录页")
        print("可能 cookie 过期。请手动登录一次以更新 cookie.json")
        input("登录完成后按回车继续...")
    else:
        print(" Cookie 登录成功！")



# =============================================
#   自动上传并发布笔记
# =============================================
def uploadNote():

    # 如果当前不在 publish 页面，先跳转
    if "publish" not in Browser.current_url:
        Browser.get("https://creator.xiaohongshu.com/publish/publish")
        time.sleep(5)

    print("Step 1: 进入发布笔记页面...")

    try:
        # 点击左侧菜单“发布笔记”
        publish_entry_xpath = "//div[@id='content-area']/main[@class='css-1emrnlo']/div[@class='menu-container menu-panel']/div[@class='list']/div[@class='publish-video']/div[@class='btn']/span"

        publish_entry = WebDriverWait(Browser, 10).until(
            EC.element_to_be_clickable((By.XPATH, publish_entry_xpath))
        )
        publish_entry.click()
        time.sleep(1)
        print("✓ 已点击“发布笔记”入口")

        

    except Exception as e:
        print(" 无法自动点击“发布笔记”，请手动点击左侧菜单中的【发布笔记】按钮")
        print(e)
        input("点击完成后按回车继续...")

    # Step 2: 点击上传图文 tab
    print("Step 2: 点击上传图文 tab...")

    try:
        upload_tab_xpath = "/html/body/div[@class='d-popover d-popover-default']/div[@class='dropdownItem']/div[@class='container'][2]"

        upload_tab = WebDriverWait(Browser, 10).until(
            EC.element_to_be_clickable((By.XPATH, upload_tab_xpath))
        )
        upload_tab.click()
        print("✓ 已点击上传图文 tab")
    

    except Exception as e:
        print(" 无法自动点击上传图文，请手动点击页面中的【上传图文】")
        print(e)
        input("点击完成后按回车继续...")


    # =============================================
    # Step2: 上传图片
    # =============================================
    print("Step2: 上传图片")

    try:
        upload_input = WebDriverWait(Browser, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@class='upload-input']"))
        )
        upload_input.send_keys(PathImage)
        print(f"✓ 图片上传成功：{PathImage}")
        time.sleep(1)
    except Exception as e:
        print(" 自动上传失败，请手动上传图片")
        input("完成后按回车继续...")

    # =============================================
    # Step3: 输入标题
    # =============================================
    print("Step3: 输入标题")

    try:
        # 真实 DOM: .title-container input
        title_input = WebDriverWait(Browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".title-container input"))
        )

        Browser.execute_script("""
            const input = arguments[0];
            input.value = arguments[1];
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        """, title_input, title)

        print(f"✓ 标题录入成功：{title}")

    except Exception as e:
        print(" 标题录入失败，请手动填写标题")
        print(e)
        input("完成后按回车继续...")


    # =============================================
    # Step4: 输入正文描述
    # =============================================
    print("Step4: 输入正文内容")

    try:
        content_div = WebDriverWait(Browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".tiptap.ProseMirror"))
        )

        Browser.execute_script("""
            const div = arguments[0];
            div.innerHTML = '<p>' + arguments[1].replace(/\\n/g, "<br>") + '</p>';
            div.dispatchEvent(new Event('input', { bubbles: true }));
            div.dispatchEvent(new Event('change', { bubbles: true }));
        """, content_div, describe)

        print(f"✓ 正文录入成功：{describe}")

    except Exception as e:
        print(" 正文录入失败，请手动填写内容")
        print(e)
        input("完成后按回车继续...")


    time.sleep(3)

    # =============================================
    # Step5: 点击发布按钮
    # =============================================
    print("Step5: 点击发布按钮")

    try:
        publish_btn = WebDriverWait(Browser, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'publishBtn')]"))
        )
        publish_btn.click()
        print(" 发布已点击！")
        time.sleep(1)
    except:
        print(" 自动点击失败，请手动点击右上角发布按钮")
        input("发布后按回车继续...")

    print("\n===== 发布流程结束 =====")


# =============================================
#          程序入口
# =============================================
def start():
    try:
        login()
        uploadNote()

        print("\n=====================================")
        print(" 自动发布流程完成！")
        print("=====================================")

    except Exception as e:
        print("程序异常：", e)
        import traceback
        traceback.print_exc()

    finally:
        input("\n按回车关闭浏览器...")
        try:
            Browser.quit()
        except:
            pass


if __name__ == "__main__":
    start()
