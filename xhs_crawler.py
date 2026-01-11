
import asyncio
import json
import os
import random
from typing import Any, Dict, Optional
from urllib.parse import quote
import httpx
from playwright.async_api import async_playwright
from loguru import logger
from xhs_sign_utils import sign_with_playwright

# --- 主爬虫类 ---

class XhsCrawler:
    """
    小红书爬虫类
    负责登录、搜索关键词、解析笔记详情及下载图片
    """
    def __init__(self, keywords=None, max_notes_count=10):
        self.keywords = keywords if keywords else ["爬虫"]
        self.max_notes_count = max_notes_count
        self.cookie_path = "cookies.json"
        self.browser = None
        self.context = None
        self.page = None
        self.cookie_dict = {}
        self._host = "https://edith.xiaohongshu.com"

    async def _login_with_cookies(self) -> bool:
        """
        使用 cookies.json 文件进行免密登录
        
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
            await self.context.add_cookies(cookies)
            logger.info("Cookie 已添加到浏览器上下文。")
            
            self.page = await self.context.new_page()
            logger.info("正在打开新页面并导航到小红书首页...")
            await self.page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")
            logger.info("页面加载完成。")

            # 验证登录是否成功
            logger.info("正在检查登录状态...")
            login_success_element = await self.page.query_selector(".search-input")
            if login_success_element:
                logger.info("Cookie 登录成功，找到搜索框元素。")
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

    async def _request(self, method, url, **kwargs):
        """
        封装 HTTP 请求，包含错误处理
        """
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, timeout=60, **kwargs)
        response.raise_for_status()
        data = response.json()
        if data.get("success"):
            return data.get("data")
        else:
            raise Exception(f"API 请求失败: {data.get('msg', '未知错误')}")

    async def get_note_detail(self, note_id: str, xsec_token: str) -> Optional[Dict]:
        """
        获取笔记详情数据
        
        Args:
            note_id: 笔记 ID
            xsec_token: 笔记的安全令牌
            
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
        a1_value = self.cookie_dict.get("a1", "")
        
        try:
            # 生成签名头
            signs = await sign_with_playwright(self.page, uri, data, a1_value, "POST")
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "X-S": signs["x-s"],
                "X-T": signs["x-t"],
                "x-S-Common": signs["x-s-common"],
                "X-B3-Traceid": signs["x-b3-traceid"],
                "Cookie": "; ".join([f"{k}={v}" for k, v in self.cookie_dict.items()]),
            }
            json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            response_data = await self._request(
                method="POST",
                url=f"{self._host}{uri}",
                content=json_str,
                headers=headers,
            )
            
            # API返回的数据结构可能有多层，需要找到items
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
        执行搜索任务
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
                search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_search_result_notes"
                logger.info(f"演示：正在跳转到搜索页面: {search_url}")
                await self.page.goto(search_url)
                await asyncio.sleep(random.uniform(3, 5)) # 等待页面加载，展示效果
            except Exception as e:
                logger.warning(f"跳转搜索页面失败: {e}")
            # ---------------------------

            page_num = 1
            search_id = "".join(random.choice("0123456789abcdef") for _ in range(32))
            while True:
                if processed_notes_count >= self.max_notes_count:
                    break
                logger.info(f"正在 API 搜索 '{keyword}' 的第 {page_num} 页...")
                
                # 1. 直接调用搜索API
                uri = "/api/sns/web/v1/search/notes"
                data = {
                    "keyword": keyword,
                    "page": page_num,
                    "page_size": 20,
                    "search_id": search_id,
                    "sort": "general",
                    "note_type": 0,
                }
                
                a1_value = self.cookie_dict.get("a1", "")
                try:
                    # 生成签名并请求
                    signs = await sign_with_playwright(self.page, uri, data, a1_value, "POST")
                    headers = {
                        "Content-Type": "application/json;charset=UTF-8",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        "X-S": signs["x-s"],
                        "X-T": signs["x-t"],
                        "x-S-Common": signs["x-s-common"],
                        "X-B3-Traceid": signs["x-b3-traceid"],
                        "Cookie": "; ".join([f"{k}={v}" for k, v in self.cookie_dict.items()]),
                    }
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

                if not response_data or not response_data.get("items"):
                    logger.info(f"关键词 '{keyword}' 第 {page_num} 页没有更多内容了。")
                    break

                # 2. 遍历搜索结果，提取 xsec_token 并获取详情
                for item in response_data.get("items", []):
                    if item.get("model_type") != "note":
                        continue
                    if processed_notes_count >= self.max_notes_count:
                        break
                    note_id = item.get("id")
                    if '#' in note_id:
                        note_id = note_id.split('#')[0]
                    xsec_token = item.get("xsec_token") # 提取 xsec_token
                    if not note_id or not xsec_token:
                        continue
                    
                    try:
                        # --- 演示用：跳转到详情页（已注释） ---
                        # detail_url = f"https://www.xiaohongshu.com/explore/{note_id}"
                        # logger.info(f"演示：正在跳转到详情页: {detail_url}")
                        # await self.page.goto(detail_url)
                        # await asyncio.sleep(random.uniform(3, 5))
                        # ----------------------------------

                        logger.info(f"准备获取笔记 {note_id} 的详情...")
                        # await asyncio.sleep(random.uniform(3, 6))
                        # 3. 传入 xsec_token 获取详情
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

                        # 提取用户信息
                        user_info = note_card.get("user", {})
                        user_data = {
                            "user_id": user_info.get("user_id"),
                            "nickname": user_info.get("nickname"),
                            "avatar": user_info.get("avatar"),
                        }
                        
                        # 提取交互信息
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
                        
                        # 提取其他信息
                        publish_time = note_card.get("time") or note_card.get("publish_time")
                        last_update_time = note_card.get("last_update_time")
                        ip_location = note_card.get("ip_location")
                        
                        # 构建文件夹路径：data/image/note_id
                        folder_name = note_id
                        current_note_dir = os.path.join(data_dir, "image", folder_name)
                        os.makedirs(current_note_dir, exist_ok=True)
                        
                        logger.info(f"笔记 {note_id} 解析: image_list长度={len(image_list)}, text_content长度={len(text_content)}")

                        if not text_content or not image_list:
                            logger.warning(f"笔记 {note_id} 缺少文本或图片，跳过。")
                            continue
                        
                        note_success = False
                        for img_info in image_list:
                            # 优先获取 url，如果没有则尝试 url_default (通常是高质量图)，最后尝试 url_pre
                            img_url = img_info.get("url") or img_info.get("url_default") or img_info.get("url_pre")
                            if not img_url:
                                logger.warning(f"图片信息中未找到有效URL: {img_info}")
                                continue
                            
                            # await asyncio.sleep(random.uniform(2, 4))
                            async with httpx.AsyncClient() as client:
                                img_response = await client.get(img_url, timeout=60)
                            img_response.raise_for_status()
                            
                            file_name = f"{image_list.index(img_info)}.jpg"
                            relative_path = os.path.join(current_note_dir, file_name)
                            
                            with open(relative_path, "wb") as f:
                                f.write(img_response.content)
                            
                            # 记录数据
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
                        
                        if note_success:
                            processed_notes_count += 1
                            logger.info(f"关键词 '{keyword}' 已处理 {processed_notes_count}/{self.max_notes_count} 条笔记: {note_id}")
                            if processed_notes_count >= self.max_notes_count:
                                break

                    except Exception as e:
                        logger.error(f"处理笔记 {note_id} 时发生错误: {e}")
                        continue
                
                if not response_data.get("has_more"):
                    logger.info(f"关键词 '{keyword}' 已搜索完毕。")
                    break
                
                page_num += 1
                # await asyncio.sleep(random.uniform(5, 10))
        
        # 保存标注文件
        if annotations:
            with open(os.path.join("data", "annotations.json"), "w", encoding="utf-8") as f:
                json.dump(annotations, f, ensure_ascii=False, indent=4)
            logger.info(f"标注文件 annotations.json 已保存，共包含 {len(annotations)} 条记录。")
        else:
            logger.warning("没有生成任何标注数据。")

    async def start(self):
        """
        启动爬虫流程
        """
        logger.info("开始启动小红书爬虫...")
        async with async_playwright() as p:
            self.browser = await p.chromium.launch(headless=False)
            self.context = await self.browser.new_context()
            
            if await self._login_with_cookies():
                await self.search()
            else:
                logger.error("因登录失败，程序即将退出。")
            
            await self.browser.close()
            logger.info("浏览器已关闭。")

if __name__ == '__main__':
    # --- 配置区域 ---
    SEARCH_KEYWORDS = ["网购相关六格漫画","退货相关六格漫画","拆快递相关六格漫画"]  # 搜索关键词列表
    MAX_NOTES_COUNT = 10       # 想要爬取的帖子总数量
    # ----------------

    try:
        crawler = XhsCrawler(keywords=SEARCH_KEYWORDS, max_notes_count=MAX_NOTES_COUNT)
        asyncio.run(crawler.start())
        logger.info("脚本执行完毕。")
    except KeyboardInterrupt:
        logger.warning("脚本被用户手动中断。")
