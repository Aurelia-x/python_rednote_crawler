import asyncio
import json
import os
import re
import base64
import httpx
from typing import List, Dict, Union, Optional
from playwright.async_api import async_playwright, Page, BrowserContext, expect
from loguru import logger

def load_env(env_path=".env"):
    """
    加载 .env 文件中的环境变量。
    
    Args:
        env_path (str): .env 文件路径，默认为当前目录下的 ".env"。
    """
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 忽略空行和注释行
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()
                    # 不记录具体的 key/value 以防泄露敏感信息


async def generate_ai_copywriting(api_key: str, image_paths: List[str], original_title: str, original_desc: str) -> Dict[str, str]:
    """
    调用千问 Qwen-VL API，基于提供的图片和原帖文本生成新的小红书文案。
    
    Args:
        api_key (str): 阿里云 API Key。
        image_paths (List[str]): 图片文件的本地路径列表。
        original_title (str): 原帖标题。
        original_desc (str): 原帖内容。
        
    Returns:
        Dict[str, str]: 包含 "title" 和 "content" 的字典。如果失败则返回 None。
    """
    logger.info("正在调用 AI 生成新文案...")
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
            logger.error(f"读取图片失败 {img_path}: {e}")

    # 添加文本提示
    prompt = f"""
    你是一个小红书爆款文案专家。请根据提供的图片和原帖内容，重新创作一篇吸引人的小红书笔记。
    
    原帖标题：{original_title}
    原帖内容：{original_desc}
    
    要求：
    1. 标题要吸引眼球，使用emoji，不超过20字。
    2. 正文语气活泼、真诚，适当使用emoji。
    3. 保留原帖的核心信息，但换一种表达方式。
    4. 结尾加上相关的标签。
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
                
                # 解析 JSON
                # AI 可能会返回带有 markdown 代码块的 json，需要清洗
                ai_text = ai_text.replace("```json", "").replace("```", "").strip()
                
                try:
                    data = json.loads(ai_text)
                    logger.success("AI 文案生成成功！")
                    return data
                except json.JSONDecodeError:
                    # 如果不是标准 JSON，尝试手动提取或直接作为 content
                    logger.warning("AI 返回的不是标准 JSON，将直接使用返回文本。")
                    # 简单分割标题和内容
                    lines = ai_text.split("\n", 1)
                    return {
                        "title": lines[0].strip()[:20], # 截取一下防止过长
                        "content": ai_text
                    }
            else:
                logger.warning(f"AI API 返回结构异常: {result}")
        else:
            logger.error(f"AI API 请求失败: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.exception(f"调用 AI API 出错: {e}")

    return None

class XhsPublisher:
    """
    小红书自动发布器。
    
    使用 Playwright 模拟浏览器操作，实现自动登录检测、图片上传、文案填充等功能。
    """
    
    def __init__(self, cookie_file: str = "cookies.json"):
        """
        初始化发布器。
        
        Args:
            cookie_file (str): 存储 Cookies 的 JSON 文件路径。
        """
        self.cookie_file = cookie_file
        self.browser_context: BrowserContext = None
        self.page: Page = None

    async def start(self, playwright):
        """
        启动浏览器并加载 Cookies。
        
        Args:
            playwright: Playwright 实例
            
        包括：
        1. 启动 Playwright Chromium 浏览器（有头模式）。
        2. 创建浏览器上下文。
        3. 注入 JavaScript 脚本以屏蔽地理位置权限弹窗。
        4. 从文件加载 Cookies 并注入到上下文。
        5. 创建新页面。
        """
        # 启动浏览器
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
                    await self.browser_context.add_cookies(cookies)
                    logger.info(f"成功加载 {len(cookies)} 个 Cookies。")
            except Exception as e:
                logger.error(f"加载 Cookies 失败: {e}")
        else:
            logger.warning("Cookies 文件不存在，请先使用get_cookies.py登录获取。")

        self.page = await self.browser_context.new_page()

    async def check_login(self) -> bool:
        """
        检查是否登录成功。
        
        Returns:
            bool: 登录成功返回 True，否则返回 False。
        """
        try:
            # 先访问小红书首页
            await self.page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")
            
            # 尝试等待搜索框出现，作为登录成功的标志
            try:
                await self.page.wait_for_selector(".search-input", state="visible", timeout=5000)
                logger.info("登录状态有效 (找到搜索框)。")
                return True
            except:
                logger.warning("Cookie 已失效或格式不正确，未能找到登录成功标识（搜索框）。")
                return False

        except Exception as e:
            logger.error(f"检查登录状态出错: {e}")
            return False

    async def publish_note(self, image_paths: List[str], title: str, content: str, dry_run: bool = False):
        """
        发布图文笔记的主逻辑。
        
        Args:
            image_paths (List[str]): 图片文件的绝对路径列表。
            title (str): 笔记标题。
            content (str): 笔记正文。
            dry_run (bool): 是否为演示模式。True 则只填充不点击发布按钮。
        """
        if not await self.check_login():
            logger.error("登录检查失败，终止发布流程。")
            return

        logger.info("开始发布流程...")
        
        try:
            # 1. 点击左侧边栏的发布按钮
            logger.info("正在寻找并点击左侧边栏的‘发布’按钮...")
            
            # 捕获新页面事件
            async with self.browser_context.expect_page() as new_page_info:
                # 定位“发布”按钮，通常在左侧导航栏
                await self.page.get_by_role("link", name="发布").first.click()
            
            # 获取新页面（创作中心）
            new_page = await new_page_info.value
            await new_page.wait_for_load_state("networkidle")
            logger.info(f"已跳转到新页面: {new_page.url}")
            
            # 更新 self.page 为新页面
            self.page = new_page

            # 2. 上传图片
            # 小红书发布页面默认是“上传视频”
            # 左上角有一个红色按钮“发布笔记”，悬停后会出现“上传图文”
            logger.info("正在寻找‘发布笔记’按钮并悬停...")
            
            try:
                # 寻找“发布笔记”按钮
                publish_btn_trigger = self.page.get_by_text("发布笔记").first
                
                # 鼠标悬停
                await publish_btn_trigger.hover()
                await self.page.wait_for_timeout(1000) # 等待菜单浮现
                
                logger.info("菜单已展开，点击‘上传图文’...")
                # 点击出现的“上传图文”链接/按钮
                upload_img_btn = self.page.get_by_text("上传图文").first
                await upload_img_btn.dispatch_event("click")
                
                # 等待切换/导航完成
                await self.page.wait_for_timeout(2000)
                
            except Exception as e:
                logger.error(f"切换图文模式过程出错: {e}")
                raise e

            logger.info(f"正在上传 {len(image_paths)} 张图片...")
            
            # 定位文件输入框
            # 关键：图文发布的 input 支持多选 且 accept 包含图片格式
            file_input = self.page.locator("input[type='file'][accept*='.jpg'], input[type='file'][accept*='image']")
            
            # 等待 input 出现
            await file_input.wait_for(state="attached", timeout=10000)
            
            # 设置文件 (支持多图)
            try:
                await file_input.set_input_files(image_paths)
            except Exception as e:
                logger.error(f"文件选择操作异常: {e}")
                raise e
            

            logger.info("图片上传指令已发送，等待预览确认...")
            
            # 等待图片上传完成的标志（图片预览图）
            logger.info("等待图片上传预览出现...")
            try:
                # .drag-item: 拖拽项
                # .preview-item: 预览项
                # img[src^='blob:']: blob 图片
                await self.page.wait_for_selector(".drag-item, .preview-item, .media-container, img[src^='blob:']", timeout=10000) 
                logger.success("检测到图片预览元素，确认上传成功。")
            except Exception as e:
                logger.warning(f"等待图片预览超时 (可能是选择器不匹配或上传慢)，尝试继续填充标题和内容... Error: {e}")
            
            await asyncio.sleep(2) # 缓冲

            # 3. 输入标题
            logger.info(f"正在输入标题: {title}")
            title_input = self.page.locator(".title-container input")
            await title_input.fill(title)
            
            # 4. 输入正文
            logger.info("正在输入正文...")
            # 正文编辑器通常是 contenteditable 的 div
            editor = self.page.locator(".tiptap.ProseMirror")
            await editor.click() # 聚焦
            await editor.fill(content) # Playwright 的 fill 对 contenteditable 通常有效
   
            await asyncio.sleep(2)# 缓冲

            # 5. 设置内容声明
            try:
                logger.info("正在设置内容来源声明...")
                # 滚动页面以确保元素可见
                await self.page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(1)

                # 找到“添加内容类型声明”选项栏并点击
                # 定位策略：查找文本为“添加内容类型声明”的元素，它是一个按钮或可点击的 div
                declaration_trigger = self.page.get_by_text("添加内容类型声明")
                if await declaration_trigger.count() > 0:
                    await declaration_trigger.first.click()
                    await asyncio.sleep(0.5)
                    
                    # 悬停到弹出的菜单栏中的“内容来源声明”
                    source_declaration_menu = self.page.get_by_text("内容来源声明")
                    await source_declaration_menu.first.hover()
                    await asyncio.sleep(0.5)
                    
                    # 在右侧的选项栏中找到“已在正文中自主标注”并点击
                    custom_annotation_option = self.page.get_by_text("已在正文中自主标注")
                    await custom_annotation_option.first.click()
                    logger.success("已勾选‘已在正文中自主标注’。")
                else:
                    logger.warning("未找到‘添加内容类型声明’选项，跳过。")
            except Exception as e:
                logger.warning(f"设置内容声明时出错: {e}")

            await asyncio.sleep(2)# 缓冲

            # 6. 发布
            if dry_run:
                logger.info("演示模式：跳过点击发布按钮。")
                logger.success("内容填充已完成，请在浏览器中查看。")
                return

            logger.info("准备点击发布按钮...")
            publish_btn = self.page.locator("button.publishBtn") 
            # 无法通过类名定位，则用文本定位
            if not await publish_btn.count():
                publish_btn = self.page.get_by_role("button", name="发布")
            
            # 检查按钮是否可点击
            await expect(publish_btn).to_be_enabled()
            await publish_btn.click()
            logger.info("发布按钮已点击！")
            
            # 等待发布成功的提示
            await asyncio.sleep(3)
            logger.success("流程结束。")

        except Exception as e:
            logger.exception(f"发布过程中出错: {e}")

    async def close(self):
        """关闭浏览器上下文"""
        if self.browser_context:
            await self.browser_context.close()

async def main():
    """
    主函数：编排整个发布流程。
    """
    # 是否启用AI生成文案功能
    ENABLE_AI = True
    # 加载环境变量
    load_env()
    api_key = os.environ.get("API_KEY")
    
    base_dir = r"e:\python code\python class\final test"
    
    # 通过 note_id 获取信息
    note_id = "67f546dd000000001d003bc7"
    
    logger.info("正在准备发布数据...")
    
    # 1. 确定图片目录
    image_dir = os.path.join(base_dir, "data_final", "image", note_id)
    
    # 2. 扫描图片
    images = []
    if os.path.exists(image_dir):
        for f in sorted(os.listdir(image_dir)):
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                images.append(os.path.join(image_dir, f))
    
    # 3. 从 annotations.json获取标题和内容 
    title = ""
    content = ""
    
    annotations_path = os.path.join(base_dir, "data_final", "annotations.json")
    if os.path.exists(annotations_path):
        try:
            with open(annotations_path, "r", encoding="utf-8") as f:
                annotations = json.load(f)
            
            # 遍历 annotations 寻找匹配 note_id 的条目
            found_note = False
            for key, value in annotations.items():
                # 检查 key 中是否包含 note_id，或者 value['info']['note_id'] 是否匹配
                if note_id in key or (value.get("info") and value["info"].get("note_id") == note_id):
                    note_content = value.get("content", {})
                    title = note_content.get("title", "")
                    content = note_content.get("desc", "")
                    
                    # 移除原话题标签 (井号包裹的内容)
                    content = re.sub(r"#[^#]+#", "", content)
                    content = content.strip()
                    
                    # 获取原作者和链接
                    nickname = value.get("user", {}).get("nickname", "未知作者")
                    url = value.get("info", {}).get("url", "")
                    
                    # 调用 AI 生成新文案
                    if ENABLE_AI and api_key and images:
                        ai_result = await generate_ai_copywriting(api_key, images, title, content)
                        if ai_result:
                            title = ai_result.get("title", title)
                            content = ai_result.get("content", content)
                            logger.info(f"-------- AI 生成的新文案 --------\n标题: {title}\n内容: {content}\n--------------------------------")

                    # 添加声明信息 
                    disclaimer = f"\n\n--------------------\n原作者：{nickname}\n原帖链接：{url}\n\n⚠️ 声明：本内容仅作为 Python 爬虫与 AI 自动化技术的学习演示。文案由 AI 基于原帖内容重写，仅供参考。引用内容版权归原作者所有，如有侵权请联系删除。"
                    content += disclaimer
                    
                    found_note = True
                    logger.info(f"最终待发布的笔记信息:\n标题: {title}\n内容摘要: {content[:20]}...")
                    break
            
            if not found_note:
                logger.warning(f"在 annotations.json 中未找到 note_id={note_id} 的信息，将使用默认/空值。")
                
        except Exception as e:
            logger.error(f"读取 annotations.json 失败: {e}")
            
    else:
            logger.warning(f"annotations.json 不存在: {annotations_path}")

    
    # 数据准备完成后，再启动浏览器
    logger.info("数据准备完成，启动浏览器...")
    async with async_playwright() as playwright:
        publisher = XhsPublisher()
        await publisher.start(playwright)

        if images:
            logger.info(f"找到 {len(images)} 张图片: {images}")
            # dry_run=True 表示只填充不发布
            await publisher.publish_note(
                image_paths=images,
                title=title,
                content=content,
                dry_run=True 
            )
        else:
            logger.warning(f"未在 {image_dir} 找到图片，仅启动浏览器演示登录。")
            await publisher.check_login()

        # 保持浏览器打开一会以便观察
        logger.info("脚本执行完毕，浏览器将保持打开状态 120 秒...")
        await asyncio.sleep(120)
        await publisher.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("脚本被用户手动中断。")