
import asyncio
import json
import os
import random
import re
from typing import Any, Dict, Optional, List
from urllib.parse import quote, urlparse
import httpx
from playwright.async_api import async_playwright
from loguru import logger
from xhs_sign_utils import sign_with_playwright

class XhsUrlCrawler:
    """
    小红书指定URL爬虫类
    负责根据给定的笔记URL列表，解析笔记详情及下载图片
    """
    def __init__(self):
        self.cookie_path = "cookies.json"
        self.browser = None
        self.context = None
        self.page = None
        self.cookie_dict = {}
        self._host = "https://edith.xiaohongshu.com"
        self.data_dir = "data"
        os.makedirs(self.data_dir, exist_ok=True)

    async def _login_with_cookies(self) -> bool:
        """
        使用 cookies.json 文件进行免密登录
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
        """
        logger.info(f"正在通过API获取笔记详情: {note_id}")

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
            
            if "items" in response_data and response_data["items"]:
                return response_data["items"][0]
            else:
                logger.warning(f"笔记 {note_id} 的详情API未返回有效items。")
                return None
        except Exception as e:
            logger.error(f"获取笔记 {note_id} 详情时出错: {e}")
            return None

    def _extract_note_id(self, url: str) -> Optional[str]:
        """
        从URL中提取笔记ID
        支持格式: 
        - https://www.xiaohongshu.com/explore/64a...
        - https://www.xiaohongshu.com/discovery/item/64a...
        """
        try:
            # 移除 query 参数
            url_no_query = url.split('?')[0]
            if "/explore/" in url_no_query:
                return url_no_query.split("/explore/")[-1]
            elif "/discovery/item/" in url_no_query:
                return url_no_query.split("/discovery/item/")[-1]
            else:
                # 尝试直接正则匹配 24位 hex 字符串
                match = re.search(r'[0-9a-f]{24}', url)
                if match:
                    return match.group(0)
            return None
        except Exception:
            return None

    async def process_urls(self, urls: List[str]):
        """
        批量处理 URL 列表
        """
        annotations = {}
        
        for url in urls:
            note_id = self._extract_note_id(url)
            if not note_id:
                logger.error(f"无法从 URL 提取笔记 ID: {url}")
                continue
            
            logger.info(f"开始处理笔记: {note_id} ({url})")
            
            try:
                # 1. 跳转到页面以获取上下文和 xsec_token
                logger.info(f"正在跳转到页面: {url}")
                await self.page.goto(url, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(2, 4)) # 等待页面初始数据加载

                # 2. 从页面状态中提取 xsec_token
                xsec_token = await self.page.evaluate(f"""() => {{
                    try {{
                        return window.__INITIAL_STATE__.note.noteDetailMap['{note_id}'].xsecToken;
                    }} catch (e) {{
                        return null;
                    }}
                }}""")
                
                if not xsec_token:
                    logger.warning(f"无法从页面提取 xsec_token，尝试直接从 URL 参数获取或置空...")
                    # 尝试从 URL query 获取
                    parsed = urlparse(url)
                    from urllib.parse import parse_qs
                    qs = parse_qs(parsed.query)
                    xsec_token = qs.get('xsec_token', [''])[0]
                
                if not xsec_token:
                    logger.warning(f"未找到 xsec_token，API 请求可能会失败。")
                else:
                    logger.info(f"成功提取 xsec_token: {xsec_token}")

                # 3. 调用 API 获取详情
                detail_data = await self.get_note_detail(note_id, xsec_token)
                if not detail_data:
                    logger.error(f"获取笔记 {note_id} 详情失败，跳过。")
                    continue

                # 4. 解析数据并下载图片 (复用 xhs_crawler 逻辑)
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
                
                # 构建文件夹路径
                folder_name = note_id
                current_note_dir = os.path.join(self.data_dir, "image", folder_name)
                os.makedirs(current_note_dir, exist_ok=True)
                
                if not text_content or not image_list:
                    logger.warning(f"笔记 {note_id} 缺少文本或图片，跳过。")
                    continue
                
                for img_info in image_list:
                    img_url = img_info.get("url") or img_info.get("url_default") or img_info.get("url_pre")
                    if not img_url:
                        continue
                    
                    await asyncio.sleep(random.uniform(1, 2))
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
                    logger.info(f"成功下载图片: {relative_path}")
                
                logger.info(f"笔记 {note_id} 处理完成。")
                await asyncio.sleep(random.uniform(2, 4))

            except Exception as e:
                logger.error(f"处理 URL {url} 时发生异常: {e}")
                continue

        # 保存标注文件 (追加模式或合并模式，这里简单起见先覆盖或新建)
        # 注意：如果多次运行，可能需要读取旧文件合并。这里简化处理，直接写入新文件。
        if annotations:
            output_file = os.path.join(self.data_dir, "url_annotations.json")
            
            # 如果文件存在，先读取旧数据合并
            if os.path.exists(output_file):
                try:
                    with open(output_file, 'r', encoding='utf-8') as f:
                        old_data = json.load(f)
                    old_data.update(annotations)
                    annotations = old_data
                except Exception:
                    pass

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(annotations, f, ensure_ascii=False, indent=4)
            logger.info(f"标注文件 {output_file} 已保存。")

    async def start(self, urls: List[str]):
        """
        启动爬虫
        """
        logger.info("开始启动小红书 URL 爬虫...")
        async with async_playwright() as p:
            self.browser = await p.chromium.launch(headless=False)
            self.context = await self.browser.new_context()
            
            if await self._login_with_cookies():
                await self.process_urls(urls)
            else:
                logger.error("登录失败，退出。")
            
            await self.browser.close()
            logger.info("浏览器已关闭。")

if __name__ == '__main__':
    # --- 配置区域 ---
    # 在此处填入想要爬取的笔记链接列表
    TARGET_URLS = [
        "https://www.xiaohongshu.com/search_result?keyword=%25E7%25BD%2591%25E8%25B4%25AD%25E9%25A2%2598%25E6%259D%2590%25E6%2589%258B%25E7%25BB%2598%25E6%25BC%25AB%25E7%2594%25BB&source=unknown", # 示例链接
        # "https://www.xiaohongshu.com/explore/xxxxxxxxxxxxxxxxxxxxxxxx",
    ]
    # ----------------

    if not TARGET_URLS:
        logger.warning("请在代码中配置 TARGET_URLS 列表。")
    else:
        crawler = XhsUrlCrawler()
        asyncio.run(crawler.start(TARGET_URLS))
