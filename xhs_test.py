import os
import time
import json
import random
import requests
from playwright.sync_api import sync_playwright
from PIL import Image
from io import BytesIO

class XHSAutoScraper:
    def __init__(self, cookie_path="cookies.json", output_dir="data"):
        self.cookie_path = cookie_path
        self.output_dir = output_dir
        self.images_dir = os.path.join(output_dir, "images")
        self.json_path = os.path.join(output_dir, "data.json")
        
        # 任务配置
        self.keywords = ["网购 拆快递", "退货 搞笑", "买家秀 六宫格"] # 轮询关键词
        self.target_count = 25   # 计划采集的数据组数
        self.min_text_len = 10   # 文本最少字符
        self.min_resolution = 500 # 图片最小宽/高
        
        # 结果存储
        self.data_store = {}
        self.collected_ids = set()
        
        # 初始化目录
        if not os.path.exists(self.images_dir):
            os.makedirs(self.images_dir)

    def load_cookies(self, context):
        """加载本地Cookie文件并注入浏览器上下文"""
        if not os.path.exists(self.cookie_path):
            print(f"[错误] 未找到 {self.cookie_path} 文件，请先导出Cookie！")
            return False
            
        try:
            with open(self.cookie_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            
            # 清洗Cookie数据，Playwright只需要特定字段
            clean_cookies = []
            for c in cookies:
                # 确保 domain 字段存在，通常设为 .xiaohongshu.com
                cookie_dict = {
                    "name": c.get("name"),
                    "value": c.get("value"),
                    "domain": c.get("domain", ".xiaohongshu.com"),
                    "path": c.get("path", "/")
                }
                clean_cookies.append(cookie_dict)
            
            context.add_cookies(clean_cookies)
            print(f"[成功] 已加载 {len(clean_cookies)} 条Cookie数据")
            return True
        except Exception as e:
            print(f"[错误] Cookie加载失败: {e}")
            return False

    def human_sleep(self, min_s=1.5, max_s=3.5):
        time.sleep(random.uniform(min_s, max_s))

    def check_and_save_image(self, img_url, file_prefix, index):
        """下载并校验图片分辨率"""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
            # 小红书图片通常需要 Referer
            headers["Referer"] = "https://www.xiaohongshu.com/"
            
            resp = requests.get(img_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                image = Image.open(BytesIO(resp.content))
                w, h = image.size
                
                # 过滤分辨率
                if w < self.min_resolution or h < self.min_resolution:
                    # print(f"    - [跳过] 分辨率过低: {w}x{h}")
                    return None
                
                # 保存
                ext = image.format.lower() if image.format else 'jpg'
                if ext == 'jpeg': ext = 'jpg'
                filename = f"{file_prefix}_{index}.{ext}"
                save_path = os.path.join(self.images_dir, filename)
                
                with open(save_path, 'wb') as f:
                    f.write(resp.content)
                
                return {
                    "filename": filename,
                    "rel_path": f"images/{filename}",
                    "width": w,
                    "height": h
                }
        except Exception as e:
            print(f"    - [错误] 图片下载异常: {e}")
        return None

    def parse_detail_page(self, page, url):
        """解析详情页内容"""
        # 等待关键元素加载
        try:
            # 尝试等待标题或轮播图加载
            page.wait_for_selector(".note-content, .interaction-container", timeout=5000)
        except:
            print("  [失败] 页面加载超时或结构异常")
            return

        # 1. 获取文本
        title = ""
        desc = ""
        
        # 尝试获取标题 (选择器可能会随版本更新，这里使用了较通用的ID和Class)
        try:
            if page.locator("#detail-title").count() > 0:
                title = page.locator("#detail-title").inner_text()
            elif page.locator(".title").count() > 0:
                title = page.locator(".title").first.inner_text()
        except: pass

        # 尝试获取正文
        try:
            if page.locator("#detail-desc").count() > 0:
                desc = page.locator("#detail-desc").inner_text()
            elif page.locator(".desc").count() > 0:
                desc = page.locator(".desc").first.inner_text()
        except: pass
        
        content_text = f"{title}\n{desc}"
        clean_len = len("".join(content_text.split()))
        
        if clean_len < self.min_text_len:
            print(f"  [过滤] 文本过短 ({clean_len}字)")
            return

        # 2. 获取图片链接
        # 策略：查找 swiper-slide 下的背景图或者 img 标签
        img_urls = []
        
        # 方法A: 查找 img 标签
        elements = page.locator(".note-slider .swiper-slide img, .note-content img").all()
        for el in elements:
            src = el.get_attribute("src")
            if src and "sns-webpic" in src: # 简单的特征校验
                img_urls.append(src)
        
        # 方法B: 如果方法A没找到，尝试查找style中的background-image (旧版结构)
        if not img_urls:
            divs = page.locator(".note-slider .swiper-slide span").all() # 经常是span做背景
            for div in divs:
                style = div.get_attribute("style")
                if style and "url(" in style:
                    url_extract = style.split('url("')[1].split('")')[0]
                    img_urls.append(url_extract)

        # 去重并补全协议
        unique_urls = []
        for u in img_urls:
            if u.startswith("//"): u = "https:" + u
            if u not in unique_urls: unique_urls.append(u)
            
        if len(unique_urls) < 3: # 连环画至少要有几张图
            print(f"  [过滤] 图片数量不足 ({len(unique_urls)}张)")
            return

        # 3. 下载流程
        print(f"  > 标题: {title[:15]}... | 图片数: {len(unique_urls)}")
        note_id = url.split("/")[-1]
        
        saved_imgs = []
        for i, u in enumerate(unique_urls):
            res = self.check_and_save_image(u, note_id, i)
            if res: saved_imgs.append(res)
            
        if not saved_imgs:
            return

        # 4. 存入内存数据
        # 题目要求：键为图像名称，值为字典
        for img_info in saved_imgs:
            self.data_store[img_info['filename']] = {
                "rel_path": img_info['rel_path'],
                "text_content": content_text, # 标注内容
                "post_title": title,
                "source_url": url,
                "img_width": img_info['width'],
                "img_height": img_info['height'],
                "theme": "网购/拆快递/退货"
            }
        
        print(f"  [成功] 保存 {len(saved_imgs)} 张图片及标注")

    def run(self):
        with sync_playwright() as p:
            # 启动浏览器
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            
            # 注入 Cookie 实现自动登录
            if not self.load_cookies(context):
                browser.close()
                return

            page = context.new_page()
            
            # 验证登录状态
            try:
                print(">>> 正在访问主页验证登录状态...")
                page.goto("https://www.xiaohongshu.com/explore")
                page.wait_for_load_state("networkidle")
                # 检查是否存在登录按钮，如果不存在，说明登录成功
                if page.locator(".login-btn").count() == 0:
                    print(">>> 自动登录成功！")
                else:
                    print(">>> Cookie可能已过期，请重新手动登录或更新文件。")
                    # 这里给个机会手动救场
                    time.sleep(10)
            except Exception as e:
                print(f"验证过程出错: {e}")

            # 开始关键词轮询采集
            for keyword in self.keywords:
                if len(self.data_store) >= self.target_count * 5: # 估算图片数，防止过多
                    break
                    
                print(f"\n>>> 开始搜索关键词: {keyword}")
                search_url = f"https://www.xiaohongshu.com/search_result?keyword={keyword}&source=web_search_result_notes"
                page.goto(search_url)
                self.human_sleep(2, 3)
                
                # 滚动加载几次以获取更多数据
                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 1000)")
                    self.human_sleep(1, 2)
                
                # 获取当前页所有笔记卡片
                cards = page.locator("section.note-item").all()
                print(f"扫描到 {len(cards)} 个笔记，准备采集...")
                
                for card in cards:
                    # 检查总目标是否达成（按组计算，这里简单用 data_store 长度估算）
                    # 更好的方式是计数处理过的 valid notes
                    if len(self.collected_ids) >= self.target_count:
                        break
                        
                    try:
                        # 提取链接
                        a_tag = card.locator("a").first
                        if not a_tag.count(): continue
                        href = a_tag.get_attribute("href")
                        
                        # 构造完整URL
                        if not href.startswith("http"):
                            full_url = "https://www.xiaohongshu.com" + href
                        else:
                            full_url = href
                            
                        # 去重 ID
                        note_id = full_url.split("/")[-1]
                        if note_id in self.collected_ids:
                            continue
                            
                        # 打开新页面处理（避免破坏搜索列表页状态）
                        new_page = context.new_page()
                        print(f"\n处理笔记: {full_url}")
                        self.parse_detail_page(new_page, full_url)
                        new_page.close()
                        
                        self.collected_ids.add(note_id)
                        self.human_sleep(2, 4) # 稍微慢点，防止封IP
                        
                    except Exception as e:
                        print(f"处理卡片出错: {e}")
                        continue

            # 保存 JSON
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(self.data_store, f, ensure_ascii=False, indent=4)
                
            print(f"\n>>> 采集结束！共采集 {len(self.collected_ids)} 组连环画，图片及Json已保存至 {self.output_dir}")
            browser.close()

if __name__ == "__main__":
    # 确保目录下有 cookie.json
    scraper = XHSAutoScraper(cookie_path="cookies.json")
    scraper.run()