import asyncio
import json
import os
import time
import re
import base64
import httpx
from typing import List, Dict, Union, Optional
from playwright.async_api import async_playwright, Page, BrowserContext, expect

def load_env(env_path=".env"):
    """简单的 .env 文件加载器"""
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

async def generate_ai_copywriting(api_key: str, image_paths: List[str], original_title: str, original_desc: str) -> Dict[str, str]:
    """
    调用千问 Qwen-VL API 基于图片和原文本生成新文案
    """
    print("正在调用 AI 生成新文案...")
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 构建消息内容
    content = []
    
    # 添加图片 (限制最多 4 张以避免 token 过大或超时)
    for img_path in image_paths[:4]: 
        try:
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
                # 获取文件扩展名
                ext = os.path.splitext(img_path)[1][1:].lower()
                if ext == "jpg": ext = "jpeg"
                content.append({"image": f"data:image/{ext};base64,{img_b64}"})
        except Exception as e:
            print(f"读取图片失败 {img_path}: {e}")

    # 添加文本提示
    prompt = f"""
    你是一个小红书爆款文案专家。请根据提供的图片和原帖内容，重新创作一篇吸引人的小红书笔记。
    
    原帖标题：{original_title}
    原帖内容：{original_desc}
    
    要求：
    1. 标题要吸引眼球，使用emoji，不超过20字。
    2. 正文语气活泼、真诚，适当使用emoji。
    3. 保留原帖的核心信息，但换一种表达方式。
    4. 结尾加上相关的标签（hashtags）。
    5. 返回格式必须是 JSON，包含 "title" 和 "content" 两个字段。
    """
    content.append({"text": prompt})

    payload = {
        "model": "qwen-vl-max",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": content
                }
            ]
        },
        "parameters": {
            "result_format": "message"
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=60)
            
        if response.status_code == 200:
            result = response.json()
            if "output" in result and "choices" in result["output"]:
                ai_text = result["output"]["choices"][0]["message"]["content"][0]["text"]
                
                # 尝试解析 JSON
                # AI 可能会返回带有 markdown 代码块的 json
                ai_text = ai_text.replace("```json", "").replace("```", "").strip()
                
                try:
                    data = json.loads(ai_text)
                    print("AI 文案生成成功！")
                    return data
                except json.JSONDecodeError:
                    # 如果不是标准 JSON，尝试手动提取或直接作为 content
                    print("AI 返回的不是标准 JSON，将直接使用返回文本。")
                    # 简单分割标题和内容
                    lines = ai_text.split("\n", 1)
                    return {
                        "title": lines[0].strip()[:20], # 截取一下防止过长
                        "content": ai_text
                    }
            else:
                print(f"AI API 返回结构异常: {result}")
        else:
            print(f"AI API 请求失败: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"调用 AI API 出错: {e}")

    return None

class XhsPublisher:
    def __init__(self, cookie_file: str = "cookies.json"):
        self.cookie_file = cookie_file
        self.browser_context: BrowserContext = None
        self.page: Page = None

    async def start(self):
        """启动浏览器并加载 Cookies"""
        playwright = await async_playwright().start()
        # 启动浏览器，headless=False 方便观察
        # 参照 xhs_crawler，不使用 --start-maximized，也不设定 viewport
        browser = await playwright.chromium.launch(headless=False)
        
        # 创建上下文
        self.browser_context = await browser.new_context()
        
        # 注入脚本以屏蔽地理位置权限弹窗 (模拟“一律不允许”)
        # 覆盖 navigator.geolocation 方法，使其直接报错或返回拒绝
        await self.browser_context.add_init_script("""
            navigator.geolocation.getCurrentPosition = (success, error, options) => {
                if (error) {
                    error({ code: 1, message: 'User denied Geolocation' });
                }
            };
            navigator.geolocation.watchPosition = (success, error, options) => {
                if (error) {
                    error({ code: 1, message: 'User denied Geolocation' });
                }
                return 0;
            };
            // 同时也尝试覆盖 permissions query
            const originalQuery = navigator.permissions.query;
            navigator.permissions.query = (parameters) => {
                if (parameters.name === 'geolocation') {
                    return Promise.resolve({ state: 'denied', onchange: null });
                }
                return originalQuery(parameters);
            };
        """)
        
        # 加载 Cookies
        if os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                    # Playwright 需要的 cookie 格式可能与 Selenium 略有不同，
                    # 但通常只需要 name, value, domain, path, secure 等字段
                    # 我们可以简单清洗一下
                    clean_cookies = []
                    for cookie in cookies:
                        # 移除 Selenium 特有或 Playwright 可能不支持的字段
                        c = {
                            "name": cookie.get("name"),
                            "value": cookie.get("value"),
                            "domain": cookie.get("domain"),
                            "path": cookie.get("path", "/"),
                            "secure": cookie.get("secure", False)
                        }
                        # 修复 domain：如果是 .xiaohongshu.com 开头，Playwright 通常也能处理，
                        # 但为了保险，保持原样或根据需要调整
                        clean_cookies.append(c)
                    
                    await self.browser_context.add_cookies(clean_cookies)
                    print(f"成功加载 {len(clean_cookies)} 个 Cookies。")
            except Exception as e:
                print(f"加载 Cookies 失败: {e}")
        else:
            print("Cookies 文件不存在，请先登录。")

        self.page = await self.browser_context.new_page()

    async def check_login(self) -> bool:
        """检查是否登录成功"""
        try:
            # 参照 xhs_crawler，先访问首页
            # 使用 domcontentloaded 避免 networkidle 超时
            await self.page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")
            
            # 尝试等待搜索框出现，作为登录成功的标志
            try:
                await self.page.wait_for_selector(".search-input", state="visible", timeout=5000)
                print("登录状态有效 (找到搜索框)。")
                return True
            except:
                pass

            # 检查是否有登录按钮
            if await self.page.get_by_text("登录", exact=True).count() > 0:
                 print("检测到登录按钮，Cookie 可能失效。")
                 return False
            
            # 如果既没有搜索框也没有登录按钮，可能是页面结构变化或未完全加载
            # 但为了流程继续，我们可以尝试返回 True，或者进一步检查头像
            # 这里简单返回 True，由后续步骤验证
            print("未检测到明确标志，尝试继续...")
            return True
        except Exception as e:
            print(f"检查登录状态出错: {e}")
            return False

    async def publish_note(self, image_paths: List[str], title: str, content: str, dry_run: bool = False):
        """
        发布图文笔记
        :param image_paths: 图片路径列表
        :param title: 标题
        :param content: 正文内容
        :param dry_run: 是否为演示模式（不点击发布按钮）
        """
        if not await self.check_login():
            return

        print("开始发布流程...")
        
        try:
            # 1. 点击左侧边栏的发布按钮
            # 注意：点击发布通常会打开新标签页
            print("正在寻找并点击左侧边栏的‘发布’按钮...")
            
            # 捕获新页面事件
            async with self.browser_context.expect_page() as new_page_info:
                # 定位“发布”按钮，通常在左侧导航栏
                # 使用 get_by_role 更加语义化，且根据错误提示，侧边栏的是一个 link
                # 如果有多个，取第一个 (通常侧边栏在前面)
                await self.page.get_by_role("link", name="发布").first.click()
            
            # 获取新页面（创作中心）
            new_page = await new_page_info.value
            await new_page.wait_for_load_state("networkidle")
            print(f"已跳转到新页面: {new_page.url}")
            
            # 更新 self.page 为新页面
            self.page = new_page

            # 2. 上传图片
            # 小红书发布页面默认可能是“上传视频”
            # 左上角有一个红色按钮“发布笔记”，悬停后会出现“上传图文”
            print("正在寻找‘发布笔记’按钮并悬停...")
            
            try:
                # 寻找“发布笔记”按钮，通常是红色按钮
                publish_btn_trigger = self.page.get_by_text("发布笔记").first
                
                # 鼠标悬停
                await publish_btn_trigger.hover()
                await self.page.wait_for_timeout(1000) # 等待菜单浮现
                
                print("菜单已展开，点击‘上传图文’...")
                # 点击出现的“上传图文”链接/按钮
                # 使用 dispatch_event 模拟点击
                upload_img_btn = self.page.get_by_text("上传图文").first
                await upload_img_btn.dispatch_event("click")
                
                # 等待切换/导航完成
                await self.page.wait_for_timeout(2000)
                
            except Exception as e:
                print(f"切换图文模式过程出错: {e}")
                raise e

            print(f"正在上传 {len(image_paths)} 张图片...")
            
            # 定位文件输入框
            # 关键：图文发布的 input 应该支持多选 (multiple) 且 accept 包含图片格式
            file_input = self.page.locator("input[type='file'][accept*='.jpg'], input[type='file'][accept*='image']")
            
            # 等待 input 出现
            await file_input.wait_for(state="attached", timeout=10000)
            
            # 设置文件 (支持多图)
            try:
                await file_input.set_input_files(image_paths)
            except Exception as e:
                print(f"文件选择操作异常: {e}")
                raise e
            
            # (已移除 DOM 弹窗处理，改用 init_script 自动拒绝权限)

            print("图片上传指令已发送，等待预览确认...")
            
            # 等待图片上传完成的标志，例如出现了图片预览图
            print("等待图片上传预览出现...")
            try:
                # 尝试更宽泛的选择器
                # .drag-item: 拖拽项
                # .preview-item: 预览项
                # img[src^='blob:']: blob 图片
                await self.page.wait_for_selector(".drag-item, .preview-item, .media-container, img[src^='blob:']", timeout=10000) 
                print("检测到图片预览元素，确认上传成功。")
            except Exception as e:
                print(f"等待图片预览超时 (可能是选择器不匹配或上传慢)，尝试继续填充标题和内容... Error: {e}")
            
            await asyncio.sleep(2) # 稍作缓冲

            # 3. 输入标题
            print(f"正在输入标题: {title}")
            title_input = self.page.locator(".title-container input")
            await title_input.fill(title)
            
            # 4. 输入正文
            print("正在输入正文...")
            # 正文编辑器通常是 contenteditable 的 div
            editor = self.page.locator(".tiptap.ProseMirror")
            await editor.click() # 聚焦
            await editor.fill(content) # Playwright 的 fill 对 contenteditable 通常有效
            # 如果 fill 不行，可以回退到 type 或者 evaluate (JS 注入)
            # await editor.press_sequentially(content, delay=50) 
            
            # 5. 发布
            if dry_run:
                print("演示模式：跳过点击发布按钮。")
                print("内容填充已完成，请在浏览器中查看。")
                return

            print("准备点击发布按钮...")
            publish_btn = self.page.locator("button.publishBtn") # 根据 reference.py 的类名
            # 或者用文本定位
            if not await publish_btn.count():
                publish_btn = self.page.get_by_role("button", name="发布")
            
            # 检查按钮是否可点击
            await expect(publish_btn).to_be_enabled()
            await publish_btn.click()
            print("发布按钮已点击！")
            
            # 等待发布成功的提示
            # 通常会有 "发布成功" 的 toast 或者跳转
            await asyncio.sleep(3)
            print("流程结束。")

        except Exception as e:
            print(f"发布过程中出错: {e}")
            import traceback
            traceback.print_exc()

    async def close(self):
        if self.browser_context:
            await self.browser_context.close()

async def main():
    # 加载环境变量
    load_env()
    api_key = os.environ.get("API_KEY")

    publisher = XhsPublisher()
    await publisher.start()
    
    base_dir = r"e:\python code\python class\final test"
    
    # 修改：通过 note_id 获取信息
    note_id = "67f546dd000000001d003bc7"
    
    # 1. 确定图片目录
    image_dir = os.path.join(base_dir, "data_final", "image", note_id)
    
    # 2. 扫描图片
    images = []
    if os.path.exists(image_dir):
        for f in sorted(os.listdir(image_dir)):
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                images.append(os.path.join(image_dir, f))
    
    # 3. 获取标题和内容 (从 annotations.json)
    title = ""
    content = ""
    
    annotations_path = os.path.join(base_dir, "data_final", "annotations.json")
    if os.path.exists(annotations_path):
        try:
            with open(annotations_path, "r", encoding="utf-8") as f:
                annotations = json.load(f)
            
            # 尝试查找对应的笔记信息
            # 遍历 annotations 寻找匹配 note_id 的条目
            found_note = False
            for key, value in annotations.items():
                # 检查 key 中是否包含 note_id，或者 value['info']['note_id'] 是否匹配
                # 注意 key 是类似 "data_final\\image\\695e3...\\0.jpg"
                if note_id in key or (value.get("info") and value["info"].get("note_id") == note_id):
                    note_content = value.get("content", {})
                    title = note_content.get("title", "")
                    content = note_content.get("desc", "")
                    
                    # 移除话题标签 (井号包裹的内容)
                    content = re.sub(r"#[^#]+#", "", content)
                    content = content.strip()
                    
                    # 获取原作者和链接
                    nickname = value.get("user", {}).get("nickname", "未知作者")
                    url = value.get("info", {}).get("url", "")
                    
                    # 调用 AI 生成新文案
                    if api_key and images:
                        ai_result = await generate_ai_copywriting(api_key, images, title, content)
                        if ai_result:
                            title = ai_result.get("title", title)
                            content = ai_result.get("content", content)
                            print(f"-------- AI 生成的新文案 --------\n标题: {title}\n内容: {content}\n--------------------------------")

                    # 添加声明信息 (润色后)
                    disclaimer = f"\n\n--------------------\n原作者：{nickname}\n原帖链接：{url}\n\n⚠️ 声明：本内容仅作为 Python 爬虫与 AI 自动化技术的学习演示。文案由 AI 基于原帖内容重写，仅供参考。引用内容版权归原作者所有，如有侵权请联系删除。"
                    content += disclaimer
                    
                    found_note = True
                    print(f"最终待发布的笔记信息:\n标题: {title}\n内容摘要: {content[:20]}...")
                    break
            
            if not found_note:
                print(f"Warning: 在 annotations.json 中未找到 note_id={note_id} 的信息，将使用默认/空值。")
                
        except Exception as e:
            print(f"读取 annotations.json 失败: {e}")
            import traceback
            traceback.print_exc()
    else:
            print(f"Warning: annotations.json 不存在: {annotations_path}")

    
    if images:
        print(f"找到 {len(images)} 张图片: {images}")
        # dry_run=True 表示只填充不发布
        await publisher.publish_note(
            image_paths=images,
            title=title,
            content=content,
            dry_run=True 
        )
    else:
        print(f"未在 {image_dir} 找到图片，仅启动浏览器演示登录。")
        await publisher.check_login()

    # 保持浏览器打开一会以便观察
    print("脚本执行完毕，浏览器将保持打开状态 120 秒...")
    await asyncio.sleep(120)
    await publisher.close()

# 示例调用
if __name__ == "__main__":
    asyncio.run(main())
