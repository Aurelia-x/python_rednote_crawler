import asyncio
import json
import os
import random
import re
from typing import Dict, Optional
from urllib.parse import quote
import httpx
from playwright.async_api import async_playwright
from loguru import logger
from xhs_sign_utils import sign_with_playwright



class Visualizer:
    """
    演示模式可视化控制器
    
    设计目的:
        为了解决"演示模式"下浏览器页面跳转会阻塞主爬虫逻辑的问题。
        主爬虫需要高速并发请求 API，而浏览器页面加载渲染很慢。
        通过引入 Visualizer，将"视觉展示"与"数据抓取"解耦。
        
    工作原理:
        1. 维护一个 asyncio.Queue 队列，用于存放"展示任务"（如跳转页面）。
        2. 启动一个后台 worker 协程，不断从队列中取出任务并执行。
        3. 主爬虫只需往队列里 put 任务即可立刻返回，无需等待浏览器加载完成。
    """
    def __init__(self, context):
        """
        初始化可视化控制器
        
        Args:
            context: Playwright 的 BrowserContext 对象，用于创建新的演示页面
        """
        self.context = context
        self.page = None
        self.queue = asyncio.Queue()
        self.worker_task = None

    async def start(self):
        """
        启动可视化控制器
        创建一个新的浏览器页面用于演示，并启动后台 worker 任务。
        """
        self.page = await self.context.new_page()
        # 启动后台消费者任务，处理演示动作
        self.worker_task = asyncio.create_task(self._worker())

    async def _worker(self):
        """
        后台消费者协程
        不断从队列获取演示任务并执行，确保不阻塞主线程。
        """
        while True:
            # 获取下一个动作（这是一个 async 函数）
            action = await self.queue.get()
            try:
                await action()
            except Exception as e:
                logger.warning(f"演示动作执行失败: {e}")
            finally:
                # 标记任务完成
                self.queue.task_done()

    def show_search_page(self, keyword):
        """
        添加"展示搜索页面"的任务到队列
        
        Args:
            keyword: 搜索关键词
        """
        async def _action():
            if not self.page: return
            try:
                # 必须将页面置于前台，否则用户可能看不到演示效果
                await self.page.bring_to_front()
                # 构造搜索结果页 URL
                search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_search_result_notes"
                logger.info(f"正在跳转到搜索页面: {search_url}")
                await self.page.goto(search_url)
                # 强制等待 2 秒，让观众看清楚页面内容
                await asyncio.sleep(2) 
            except Exception as e:
                logger.warning(f"跳转搜索页面失败: {e}")
        
        # 非阻塞放入队列
        self.queue.put_nowait(_action)

    def show_note_detail(self, note_id, xsec_token):
        """
        添加"展示笔记详情"的任务到队列
        
        Args:
            note_id: 笔记 ID
            xsec_token: 笔记的安全令牌（跳转详情页必需参数）
        """
        async def _action():
            if not self.page: return
            try:
                await self.page.bring_to_front()
                # 构造笔记详情页 URL
                detail_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_search"
                logger.info(f"正在跳转到详情页: {detail_url}")
                await self.page.goto(detail_url)
                # 强制等待 2 秒，展示效果
                await asyncio.sleep(2) 
            except Exception as e:
                logger.warning(f"跳转详情页失败: {e}")
        
        self.queue.put_nowait(_action)

    async def stop(self):
        """
        停止可视化控制器
        等待队列中的所有演示任务执行完毕，然后关闭页面。
        """
        if self.worker_task:
            # 等待队列中剩余任务完成
            if not self.queue.empty():
                logger.info("正在等待演示任务完成...")
                await self.queue.join()
            
            # 取消后台任务
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        
        if self.page:
            await self.page.close()

# --- 主爬虫类 ---
class XhsCrawler:
    """
    小红书爬虫主类
    
    功能:
    1. 负责模拟登录（Cookie 注入）。
    2. 执行关键词搜索（调用搜索 API）。
    3. 获取笔记详情（调用详情 API）。
    4. 下载图片并保存元数据（JSON 格式）。
    
    架构特点:
    - 采用 Playwright + HTTP API 混合模式。
    - Playwright 用于环境模拟和签名生成（解决 JS 加密难题）。
    - HTTP API (httpx) 用于数据传输（提高爬取速度）。
    """
    def __init__(self, keywords=None, max_notes_count=10, display_mode=False, display_id=None, enable_filtering=True):
        """
        初始化爬虫
        
        Args:
            keywords: 搜索关键词列表
            max_notes_count: 每个关键词最大爬取笔记数量
            display_mode: 是否开启演示模式（可视化展示）
            display_id: 仅演示特定 ID 的笔记（调试用）
            enable_filtering: 是否开启关键词相关性过滤
        """
        self.keywords = keywords if keywords else ["爬虫"]
        self.max_notes_count = max_notes_count
        self.cookie_path = "cookies.json"
        self.browser = None
        self.context = None
        self.page = None
        self.cookie_dict = {}
        self._host = "https://edith.xiaohongshu.com" # 小红书 API 域名
        self.display_mode = display_mode
        self.display_id = display_id
        self.enable_filtering = enable_filtering
        self.visualizer = None
        
        # 定义高级过滤规则
        # 格式: keyword -> { groups: [[必须包含组1], [必须包含组2]], exclude: [排除词] }
        # 逻辑: (组1中任一词命中) AND (组2中任一词命中) AND (排除词均未命中)
        common_style_group = ["漫画", "手绘", "画画", "插画", "简笔画", "条漫", "四格", "六格"]
        self.filter_rules = {
            "网购题材手绘漫画": {
                "groups": [
                    ["网购", "淘宝", "购物", "买东西", "下单", "电商", "买家秀"],
                    common_style_group
                ],
                "exclude": ["教程", "招聘", "代画"]
            },
            "退货题材手绘漫画": {
                "groups": [
                    ["退货", "退款", "避雷", "踩雷", "售后", "差评", "商家"],
                    common_style_group
                ],
                "exclude": ["教程", "招聘", "代画"]
            },
            "拆快递题材手绘漫画": {
                "groups": [
                    ["拆快递", "快递", "拆箱", "包裹", "开箱", "取快递"],
                    common_style_group
                ],
                "exclude": ["教程", "招聘", "代画"]
            }
        }

    async def _login_with_cookies(self) -> bool:
        """
        使用本地 cookies.json 文件进行免密登录
        
        流程:
        1. 读取本地 Cookie 文件。
        2. 注入到 Playwright 上下文。
        3. 打开首页并检查是否出现搜索框（登录成功的标志）。
        4. 如果成功，更新内存中的 cookie_dict 供后续 API 请求使用。
        
        Returns:
            bool: 登录是否成功
        """
        logger.info("尝试使用 Cookie 文件登录...")
        if not os.path.exists(self.cookie_path):
            logger.error(f"Cookie 文件不存在: {self.cookie_path}")
            return False
        try:
            with open(self.cookie_path, 'r') as f:
                cookies = json.load(f)
            logger.info("成功加载 Cookie 文件。")
            
            # 注入 Cookie
            await self.context.add_cookies(cookies)
            logger.info("Cookie 已添加到浏览器上下文。")
            
            self.page = await self.context.new_page()
            logger.info("正在打开新页面并导航到小红书首页...")
            await self.page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")
            logger.info("页面加载完成。")

            # 验证登录是否成功：检查页面是否存在搜索框元素 (.search-input)
            logger.info("正在检查登录状态...")
            login_success_element = await self.page.query_selector(".search-input")
            if login_success_element:
                logger.info("Cookie 登录成功，找到搜索框元素。")
                # 重新获取最新的 Cookie（可能包含服务端更新的字段）
                current_cookies = await self.context.cookies()
                self.cookie_dict = {cookie['name']: cookie['value'] for cookie in current_cookies}
                logger.info("已更新当前会话的 Cookie。")
                return True
            else:
                logger.error("Cookie 已失效或格式不正确，未能找到登录成功标识（搜索框）。")
                return False
        except Exception as e:
            logger.error(f"使用 Cookie 登录时发生异常: {e}")
            return False

    async def _request(self, method, url, retry_count=3, **kwargs):
        """
        封装 HTTP 请求，包含错误处理和重试机制
        
        Args:
            method: 请求方法 (GET, POST)
            url: 请求 URL
            retry_count: 重试次数，默认 3 次
            **kwargs: 传递给 httpx.request 的其他参数
            
        Returns:
            API 返回的 data 字段内容
            
        Raises:
            Exception: 如果重试多次后仍然失败
        """
        for i in range(retry_count):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.request(method, url, timeout=60, **kwargs)
                response.raise_for_status() # 检查 HTTP 状态码
                data = response.json()
                
                # 小红书 API 通常返回 {success: true, data: ...}
                if data.get("success"):
                    return data.get("data")
                else:
                    raise Exception(f"API 请求失败: {data.get('msg', '未知错误')}")
            except Exception as e:
                logger.warning(f"请求失败 (尝试 {i+1}/{retry_count}): {e}")
                if i == retry_count - 1:
                    # 最后一次重试失败，抛出异常
                    raise e
                # 随机延迟后重试，避免立即重试再次被拒
                await asyncio.sleep(random.uniform(1, 3))

    async def _get_signed_headers(self, uri: str, data: Dict) -> Dict:
        """
        生成带有签名的请求头
        
        原理:
        小红书 API 需要 X-S, X-T 等签名头才能验证通过。
        本方法调用 xhs_sign_utils.sign_with_playwright，
        利用浏览器上下文中的 JS 环境计算签名。
        
        Args:
            uri: API 路径 (如 /api/sns/web/v1/search/notes)
            data: 请求参数字典
            
        Returns:
            Dict: 包含完整 Headers 的字典
        """
        a1_value = self.cookie_dict.get("a1", "")
        # 调用签名工具函数，获取 x-s, x-t 等核心参数
        signs = await sign_with_playwright(self.page, uri, data, a1_value, "POST")
        
        return {
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-S": signs["x-s"],
            "X-T": signs["x-t"],
            "x-S-Common": signs["x-s-common"],
            "X-B3-Traceid": signs["x-b3-traceid"],
            "Cookie": "; ".join([f"{k}={v}" for k, v in self.cookie_dict.items()]),
        }

    async def get_note_detail(self, note_id: str, xsec_token: str) -> Optional[Dict]:
        """
        获取笔记详情数据
        
        Args:
            note_id: 笔记 ID
            xsec_token: 笔记的安全令牌 (搜索列表接口返回)
            
        Returns:
            Dict: 笔记详情数据，如果获取失败返回 None
        """
        logger.info(f"正在获取笔记详情: {note_id}")

        uri = "/api/sns/web/v1/feed"
        data = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"},
            "xsec_source": "pc_search",
            "xsec_token": xsec_token
        }
        try:
            # 1. 生成签名头
            headers = await self._get_signed_headers(uri, data)
            json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            
            # 2. 发送请求
            response_data = await self._request(
                method="POST",
                url=f"{self._host}{uri}",
                content=json_str,
                headers=headers,
            )
            
            # 3. 解析结果 (API 返回的数据结构可能有多层，需要找到 items)
            if "items" in response_data and response_data["items"]:
                return response_data["items"][0]
            else:
                logger.warning(f"笔记 {note_id} 的详情API未返回有效items。")
                return None
        except Exception as e:
            logger.error(f"获取笔记 {note_id} 详情时出错: {e}")
            return None

    async def search(self):
        """
        执行搜索主逻辑
        
        流程:
        1. 遍历关键词列表。
        2. 分页调用搜索 API (/api/sns/web/v1/search/notes)。
        3. 遍历搜索结果，提取 note_id 和 xsec_token。
        4. 调用详情 API 获取完整内容。
        5. 下载图片并保存标注数据。
        """
        logger.info(f"开始搜索关键词: {self.keywords}")
        
        annotations = {}
        image_count = 0
        data_dir = "data"
        os.makedirs(data_dir, exist_ok=True)

        for keyword in self.keywords:
            processed_notes_count = 0

            # --- 演示用：跳转到搜索页面 ---
            try:
                if self.display_mode and self.visualizer:
                    self.visualizer.show_search_page(keyword)
            except Exception as e:
                logger.warning(f"跳转搜索页面失败: {e}")
            # ---------------------------

            page_num = 1
            search_id = "".join(random.choice("0123456789abcdef") for _ in range(32))
            
            while True:
                # 检查是否达到最大爬取数量
                if processed_notes_count >= self.max_notes_count:
                    break
                logger.info(f"正在 API 搜索 '{keyword}' 的第 {page_num} 页...")
                
                # --- 反爬虫策略：随机延迟 ---
                # 模拟人类翻页的时间间隔，避免高频请求
                await asyncio.sleep(random.uniform(2, 5))


                # 1. 构造搜索 API 请求参数
                uri = "/api/sns/web/v1/search/notes"
                data = {
                    "keyword": keyword,
                    "page": page_num,
                    "page_size": 20,
                    "search_id": search_id,
                    "sort": "general",
                    "note_type": 0,
                }
                
                try:
                    # 生成签名并请求
                    headers = await self._get_signed_headers(uri, data)
                    json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
                    response_data = await self._request(
                        method="POST",
                        url=f"{self._host}{uri}",
                        content=json_str,
                        headers=headers,
                    )
                except Exception as e:
                    logger.error(f"API 搜索失败: {e}")
                    break # API搜索失败，终止当前关键词的搜索

                # 检查是否还有更多内容
                if not response_data or not response_data.get("items"):
                    logger.info(f"关键词 '{keyword}' 第 {page_num} 页没有更多内容了。")
                    break

                # 2. 遍历搜索结果列表
                for item in response_data.get("items", []):
                    # 过滤非笔记类型的内容
                    if item.get("model_type") != "note":
                        continue
                    if processed_notes_count >= self.max_notes_count:
                        break
                    
                    note_id = item.get("id")
                    
                    # 演示模式下，如果指定了 display_id，则只处理该 ID
                    if self.display_mode and note_id != self.display_id:
                        continue
                        
                    # 处理 ID 中可能包含的额外参数
                    if '#' in note_id:
                        note_id = note_id.split('#')[0]
                    # 提取 xsec_token    
                    xsec_token = item.get("xsec_token")

                    if not note_id or not xsec_token:
                        continue
                    
                    try:
                        # --- 演示用：跳转到详情页 ---
                        if self.display_mode and self.visualizer:   
                            self.visualizer.show_note_detail(note_id, xsec_token)
                        # ----------------------------------

                        logger.info(f"准备获取笔记 {note_id} 的详情...")
                        
                        # --- 反爬虫策略：随机延迟 ---
                        # 详情页访问间隔
                        await asyncio.sleep(random.uniform(1, 3))


                        # 3. 获取笔记详细内容
                        detail_data = await self.get_note_detail(note_id, xsec_token)
                        if not detail_data:
                            logger.warning(f"笔记 {note_id} 详情获取失败或为空")
                            continue
                        logger.info(f"成功获取笔记 {note_id} 的详情，开始解析...")

                        note_card = detail_data.get("note_card", {})
                        
                        # 提取基础信息
                        text_content = note_card.get("desc", "")
                        title = note_card.get("title", "")
                        image_list = note_card.get("image_list", [])

                        # --- 数据过滤：文本标注不少于10个中文字符 ---
                        # 保证爬取的数据质量
                        chinese_char_count = len(re.findall(r'[\u4e00-\u9fa5]', text_content))
                        if chinese_char_count < 10:
                            logger.warning(f"笔记 {note_id} 中文字符数不足 ({chinese_char_count} < 10)，跳过。")
                            continue
                        # ----------------------------------------

                        # 提取用户信息
                        user_info = note_card.get("user", {})
                        user_data = {
                            "user_id": user_info.get("user_id"),
                            "nickname": user_info.get("nickname"),
                            "avatar": user_info.get("avatar"),
                        }
                        
                        # 提取交互信息 (点赞、收藏、评论)
                        interact_info = note_card.get("interact_info", {})
                        interact_data = {
                            "liked_count": interact_info.get("liked_count"),
                            "collected_count": interact_info.get("collected_count"),
                            "comment_count": interact_info.get("comment_count"),
                            "share_count": interact_info.get("share_count"),
                        }
                        
                        # 提取标签
                        tag_list = note_card.get("tag_list", [])
                        tags = [tag.get("name") for tag in tag_list if tag.get("name")]

                        # --- 关键词相关性过滤 ---
                        if self.enable_filtering:
                            relevant = False
                            
                            # 检查是否有针对该关键词的高级过滤规则
                            if keyword in self.filter_rules:
                                rule = self.filter_rules[keyword]
                                groups = rule.get("groups", [])
                                exclude_words = rule.get("exclude", [])
                                
                                # 1. 黑名单检查 (如果有任一排除词，直接不相关)
                                is_excluded = False
                                content_to_check = (title + text_content + "".join(tags)).lower()
                                for bad_word in exclude_words:
                                    if bad_word.lower() in content_to_check:
                                        is_excluded = True
                                        logger.warning(f"笔记 {note_id} 包含排除词 '{bad_word}'，跳过。")
                                        break
                                
                                if is_excluded:
                                    continue # 直接跳过本轮循环
                                    
                                # 2. 分组交叉匹配
                                # 必须满足：每个组中至少有一个词命中
                                all_groups_matched = True
                                for group in groups:
                                    group_matched = False
                                    for word in group:
                                        word_lower = word.lower()
                                        # 检查标题、正文
                                        if word_lower in title.lower() or word_lower in text_content.lower():
                                            group_matched = True
                                            break
                                        # 检查标签
                                        for tag in tags:
                                            if word_lower in tag.lower():
                                                group_matched = True
                                                break
                                        if group_matched:
                                            break
                                    
                                    if not group_matched:
                                        all_groups_matched = False
                                        break # 只要有一个组没命中，就不满足条件
                                
                                if all_groups_matched:
                                    relevant = True
                                    logger.info(f"笔记 {note_id} 通过高级过滤规则匹配。")
                                else:
                                    logger.warning(f"笔记 {note_id} 未满足高级过滤规则的所有分组条件，跳过。")

                            else:
                                # 默认简单过滤逻辑
                                kw_lower = keyword.lower()
                                if kw_lower in title.lower() or kw_lower in text_content.lower():
                                    relevant = True
                                else:
                                    for tag in tags:
                                        if kw_lower in tag.lower():
                                            relevant = True
                                            break
                                if not relevant:
                                    logger.warning(f"笔记 {note_id} 与关键词 '{keyword}' 不相关（默认逻辑），跳过。")
                            
                            if not relevant:
                                continue
                        # -----------------------
                        
                        # 提取其他元数据
                        publish_time = note_card.get("time") or note_card.get("publish_time")
                        last_update_time = note_card.get("last_update_time")
                        ip_location = note_card.get("ip_location")
                        
                        # 准备图片下载目录：data/image/note_id
                        folder_name = note_id
                        current_note_dir = os.path.join(data_dir, "image", folder_name)
                        os.makedirs(current_note_dir, exist_ok=True)
                        
                        logger.info(f"笔记 {note_id} 解析: image_list长度={len(image_list)}, text_content长度={len(text_content)}")

                        if not text_content or not image_list:
                            logger.warning(f"笔记 {note_id} 缺少文本或图片，跳过。")
                            continue
                        
                        note_success = False
                        for img_info in image_list:
                            # --- 数据过滤：图像分辨率不低于500p ---
                            width = img_info.get("width", 0)
                            height = img_info.get("height", 0)
                            if width < 500 or height < 500:
                                logger.warning(f"图片分辨率过低 ({width}x{height})，跳过: {img_info.get('url', '')[:30]}...")
                                continue
                            # ------------------------------------

                            # 优先获取 url，如果没有则尝试 url_default (通常是高质量图)，最后尝试 url_pre
                            img_url = img_info.get("url") or img_info.get("url_default") or img_info.get("url_pre")
                            if not img_url:
                                logger.warning(f"图片信息中未找到有效URL: {img_info}")
                                continue
                            
                            # 4. 下载图片
                            async with httpx.AsyncClient() as client:
                                img_response = await client.get(img_url, timeout=60)
                            img_response.raise_for_status()
                            
                            file_name = f"{image_list.index(img_info)}.jpg"
                            relative_path = os.path.join(current_note_dir, file_name)
                            
                            with open(relative_path, "wb") as f:
                                f.write(img_response.content)
                            
                            # 5. 记录标注数据
                            annotations[relative_path] = {
                                "image_path": relative_path,
                                "content": {
                                    "title": title,
                                    "desc": text_content,
                                    "tags": tags
                                },
                                "user": user_data,
                                "stats": interact_data,
                                "info": {
                                    "note_id": note_id,
                                    "type": note_card.get("type"),
                                    "publish_time": publish_time,
                                    "last_update_time": last_update_time,
                                    "ip_location": ip_location,
                                    "url": f"https://www.xiaohongshu.com/explore/{note_id}"
                                }
                            }
                            image_count += 1
                            logger.info(f"成功下载图片 {relative_path}，当前图文对: {image_count}")
                            note_success = True
                        
                        if self.display_mode and note_success:
                            logger.info(f"关键词 '{keyword}' 已处理1条笔记: {note_id}")
                            break
                        if note_success:
                            processed_notes_count += 1
                            logger.info(f"关键词 '{keyword}' 已处理 {processed_notes_count}/{self.max_notes_count} 条笔记: {note_id}")
                            if processed_notes_count >= self.max_notes_count:
                                break

                    except Exception as e:
                        logger.error(f"处理笔记 {note_id} 时发生错误: {e}")
                        continue
                if self.display_mode:
                    logger.info(f"演示笔记已爬取完毕")
                    break
                if not response_data.get("has_more"):
                    logger.info(f"关键词 '{keyword}' 已搜索完毕。")
                    break
                
                page_num += 1

        
        # 6. 保存汇总的标注文件
        if annotations:
            with open(os.path.join("data", "annotations.json"), "w", encoding="utf-8") as f:
                json.dump(annotations, f, ensure_ascii=False, indent=4)
            logger.info(f"标注文件 annotations.json 已保存，共包含 {len(annotations)} 条记录。")
        else:
            logger.warning("没有生成任何标注数据。")

    async def start(self):
        """
        启动爬虫主流程
        
        1. 启动 Playwright 浏览器。
        2. 如果开启演示模式，启动 Visualizer。
        3. 登录并执行搜索。
        """
        logger.info("开始启动小红书爬虫...准备登录中")
        async with async_playwright() as p:
            self.browser = await p.chromium.launch(headless=False)
            self.context = await self.browser.new_context()
            
            # 初始化演示器
            if self.display_mode:
                self.visualizer = Visualizer(self.context)
                await self.visualizer.start()

            # 执行登录和搜索
            if await self._login_with_cookies():
                await self.search()
            else:
                logger.error("因登录失败，程序即将退出。")
            
            # 停止演示器（如有）
            if self.visualizer:
                await self.visualizer.stop()

            await self.browser.close()
            logger.info("浏览器已关闭。")

if __name__ == '__main__':
    # --- 配置区域 ---
    SEARCH_KEYWORDS = ["网购题材手绘漫画","退货题材手绘漫画","拆快递题材手绘漫画"]  # 搜索关键词列表
    TEST_SEARCH_KEYWORDS = ["网购题材手绘漫画"]  # 演示用搜索关键词列表
    MAX_NOTES_COUNT = 15       # 想要爬取的帖子总数量
    ENABLE_FILTERING = False    # 是否开启关键词相关性过滤（True=开启，False=关闭）
    # ----------------

    try:
        crawler = XhsCrawler( 
                            keywords=SEARCH_KEYWORDS, 
                            max_notes_count=MAX_NOTES_COUNT, 
                            display_mode=False,
                            enable_filtering=ENABLE_FILTERING)
        asyncio.run(crawler.start())
        logger.info("脚本执行完毕。")
    except KeyboardInterrupt:
        logger.warning("脚本被用户手动中断。")
