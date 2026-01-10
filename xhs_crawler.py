
import asyncio
import json
import os
import sys
import hashlib
import time
from typing import Any, Dict, Optional, Union
from urllib.parse import urlparse, quote
import httpx
from playwright.async_api import async_playwright, Page
from loguru import logger

# --- 从 xhs_sign.py 移植过来的辅助函数 ---
import ctypes
import random

BASE64_CHARS = list("ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5")
CRC32_TABLE = [
    0, 1996959894, 3993919788, 2567524794, 124634137, 1886057615, 3915621685,
    2657392035, 249268274, 2044508324, 3772115230, 2547177864, 162941995,
    2125561021, 3887607047, 2428444049, 498536548, 1789927666, 4089016648,
    2227061214, 450548861, 1843258603, 4107580753, 2211677639, 325883990,
    1684777152, 4251122042, 2321926636, 335633487, 1661365465, 4195302755,
    2366115317, 997073096, 1281953886, 3579855332, 2724688242, 1006888145,
    1258607687, 3524101629, 2768942443, 901097722, 1119000684, 3686517206,
    2898065728, 853044451, 1172266101, 3705015759, 2882616665, 651767980,
    1373503546, 3369554304, 3218104598, 565507253, 1454621731, 3485111705,
    3099436303, 671266974, 1594198024, 3322730930, 2970347812, 795835527,
    1483230225, 3244367275, 3060149565, 1994146192, 31158534, 2563907772,
    4023717930, 1907459465, 112637215, 2680153253, 3904427059, 2013776290,
    251722036, 2517215374, 3775830040, 2137656763, 141376813, 2439277719,
    3865271297, 1802195444, 476864866, 2238001368, 4066508878, 1812370925,
    453092731, 2181625025, 4111451223, 1706088902, 314042704, 2344532202,
    4240017532, 1658658271, 366619977, 2362670323, 4224994405, 1303535960,
    984961486, 2747007092, 3569037538, 1256170817, 1037604311, 2765210733,
    3554079995, 1131014506, 879679996, 2909243462, 3663771856, 1141124467,
    855842277, 2852801631, 3708648649, 1342533948, 654459306, 3188396048,
    3373015174, 1466479909, 544179635, 3110523913, 3462522015, 1591671054,
    702138776, 2966460450, 3352799412, 1504918807, 783551873, 3082640443,
    3233442989, 3988292384, 2596254646, 62317068, 1957810842, 3939845945,
    2647816111, 81470997, 1943803523, 3814918930, 2489596804, 225274430,
    2053790376, 3826175755, 2466906013, 167816743, 2097651377, 4027552580,
    2265490386, 503444072, 1762050814, 4150417245, 2154129355, 426522225,
    1852507879, 4275313526, 2312317920, 282753626, 1742555852, 4189708143,
    2394877945, 397917763, 1622183637, 3604390888, 2714866558, 953729732,
    1340076626, 3518719985, 2797360999, 1068828381, 1219638859, 3624741850,
    2936675148, 906185462, 1090812512, 3747672003, 2825379669, 829329135,
    1181335161, 3412177804, 3160834842, 628085408, 1382605366, 3423369109,
    3138078467, 570562233, 1426400815, 3317316542, 2998733608, 733239954,
    1555261956, 3268935591, 3050360625, 752459403, 1541320221, 2607071920,
    3965973030, 1969922972, 40735498, 2617837225, 3943577151, 1913087877,
    83908371, 2512341634, 3803740692, 2075208622, 213261112, 2463272603,
    3855990285, 2094854071, 198958881, 2262029012, 4057260610, 1759359992,
    534414190, 2176718541, 4139329115, 1873836001, 414664567, 2282248934,
    4279200368, 1711684554, 285281116, 2405801727, 4167216745, 1634467795,
    376229701, 2685067896, 3608007406, 1308918612, 956543938, 2808555105,
    3495958263, 1231636301, 1047427035, 2932959818, 3654703836, 1088359270,
    936918000, 2847714899, 3736837829, 1202900863, 817233897, 3183342108,
    3401237130, 1404277552, 615818150, 3134207493, 3453421203, 1423857449,
    601450431, 3009837614, 3294710456, 1567103746, 711928724, 3020668471,
    3272380065, 1510334235, 755167117,
]

def _right_shift_unsigned(num: int, bit: int = 0) -> int:
    val = ctypes.c_uint32(num).value >> bit
    MAX32INT = 4294967295
    return (val + (MAX32INT + 1)) % (2 * (MAX32INT + 1)) - MAX32INT - 1

def mrc(e: str) -> int:
    o = -1
    for n in range(min(57, len(e))):
        o = CRC32_TABLE[(o & 255) ^ ord(e[n])] ^ _right_shift_unsigned(o, 8)
    return o ^ -1 ^ 3988292384

def _triplet_to_base64(e: int) -> str:
    return (
        BASE64_CHARS[(e >> 18) & 63]
        + BASE64_CHARS[(e >> 12) & 63]
        + BASE64_CHARS[(e >> 6) & 63]
        + BASE64_CHARS[e & 63]
    )

def _encode_chunk(data: list, start: int, end: int) -> str:
    result = []
    for i in range(start, end, 3):
        c = ((data[i] << 16) & 0xFF0000) + ((data[i + 1] << 8) & 0xFF00) + (data[i + 2] & 0xFF)
        result.append(_triplet_to_base64(c))
    return "".join(result)

def encode_utf8(s: str) -> list:
    encoded = quote(s, safe="~()*!.'")
    result = []
    i = 0
    while i < len(encoded):
        if encoded[i] == "%":
            result.append(int(encoded[i + 1: i + 3], 16))
            i += 3
        else:
            result.append(ord(encoded[i]))
            i += 1
    return result

def b64_encode(data: list) -> str:
    length = len(data)
    remainder = length % 3
    chunks = []
    main_length = length - remainder
    for i in range(0, main_length, 16383):
        chunks.append(_encode_chunk(data, i, min(i + 16383, main_length)))
    if remainder == 1:
        a = data[length - 1]
        chunks.append(BASE64_CHARS[a >> 2] + BASE64_CHARS[(a << 4) & 63] + "==")
    elif remainder == 2:
        a = (data[length - 2] << 8) + data[length - 1]
        chunks.append(
            BASE64_CHARS[a >> 10] + BASE64_CHARS[(a >> 4) & 63] + BASE64_CHARS[(a << 2) & 63] + "="
        )
    return "".join(chunks)

def get_trace_id() -> str:
    return "".join(random.choice("abcdef0123456789") for _ in range(16))

# --- 从 playwright_sign.py 移植过来的辅助函数 ---

def _build_sign_string(uri: str, data: Optional[Union[Dict, str]] = None, method: str = "POST") -> str:
    if method.upper() == "POST":
        c = uri
        if data is not None:
            if isinstance(data, dict):
                c += json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            elif isinstance(data, str):
                c += data
        return c
    else:
        if not data or (isinstance(data, dict) and len(data) == 0):
            return uri
        if isinstance(data, dict):
            params = []
            for key, value in data.items():
                value_str = str(value)
                value_str = quote(value_str, safe='')
                params.append(f"{key}={value_str}")
            return f"{uri}?{'&'.join(params)}"
        elif isinstance(data, str):
            return f"{uri}?{data}"
        return uri

def _md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def _build_xs_payload(x3_value: str, data_type: str = "object") -> str:
    s = {
        "x0": "4.2.1",
        "x1": "xhs-pc-web",
        "x2": "Mac OS",
        "x3": x3_value,
        "x4": data_type,
    }
    return "XYS_" + b64_encode(encode_utf8(json.dumps(s, separators=(",", ":"))))

def _build_xs_common(a1: str, b1: str, x_s: str, x_t: str) -> str:
    payload = {
        "s0": 3, "s1": "", "x0": "1", "x1": "4.2.2", "x2": "Mac OS",
        "x3": "xhs-pc-web", "x4": "4.74.0", "x5": a1, "x6": x_t,
        "x7": x_s, "x8": b1, "x9": mrc(x_t + x_s + b1), "x10": 154,
        "x11": "normal",
    }
    return b64_encode(encode_utf8(json.dumps(payload, separators=(",", ":"))))

async def get_b1_from_localstorage(page: Page) -> str:
    try:
        local_storage = await page.evaluate("() => window.localStorage")
        return local_storage.get("b1", "")
    except Exception:
        return ""

async def call_mnsv2(page: Page, sign_str: str, md5_str: str) -> str:
    sign_str_escaped = sign_str.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    md5_str_escaped = md5_str.replace("\\", "\\\\").replace("'", "\\'")
    try:
        result = await page.evaluate(f"window.mnsv2('{sign_str_escaped}', '{md5_str_escaped}')")
        return result if result else ""
    except Exception:
        return ""

async def sign_with_playwright(page: Page, uri: str, data: Optional[Union[Dict, str]] = None, a1: str = "", method: str = "POST") -> Dict[str, Any]:
    b1 = await get_b1_from_localstorage(page)
    
    # sign_xs_with_playwright logic
    sign_str = _build_sign_string(uri, data, method)
    md5_str = _md5_hex(sign_str)
    x3_value = await call_mnsv2(page, sign_str, md5_str)
    data_type = "object" if isinstance(data, (dict, list)) else "string"
    x_s = _build_xs_payload(x3_value, data_type)
    
    x_t = str(int(time.time() * 1000))

    return {
        "x-s": x_s,
        "x-t": x_t,
        "x-s-common": _build_xs_common(a1, b1, x_s, x_t),
        "x-b3-traceid": get_trace_id(),
    }

# --- 主爬虫类 ---

class XhsCrawler:
    def __init__(self):
        self.keywords = ["爬虫"]
        self.cookie_path = "cookies.json"
        self.browser = None
        self.context = None
        self.page = None
        self.cookie_dict = {}
        self._host = "https://edith.xiaohongshu.com"

    async def _login_with_cookies(self) -> bool:
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
                # 增加截图以便调试
                screenshot_path = "login_failure_screenshot.png"
                await self.page.screenshot(path=screenshot_path)
                logger.error(f"已截取当前页面保存至 {screenshot_path} 以供分析。")
                return False
        except Exception as e:
            logger.error(f"使用 Cookie 登录时发生异常: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _request(self, method, url, **kwargs):
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, timeout=60, **kwargs)
        response.raise_for_status()
        data = response.json()
        if data.get("success"):
            return data.get("data")
        else:
            raise Exception(f"API 请求失败: {data.get('msg', '未知错误')}")

    async def search(self):
        logger.info(f"开始搜索关键词: {self.keywords}")
        for keyword in self.keywords:
            page_num = 1
            while True:
                logger.info(f"正在搜索 '{keyword}' 的第 {page_num} 页...")
                uri = "/api/sns/web/v1/search/notes"
                search_id = "".join(random.choice("0123456789abcdef") for _ in range(32))
                data = {
                    "keyword": keyword,
                    "page": page_num,
                    "page_size": 20,
                    "search_id": search_id,
                    "sort": "general",
                    "note_type": 0,
                }
                
                a1_value = self.cookie_dict.get("a1", "")
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

                try:
                    json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
                    response_data = await self._request(
                        method="POST",
                        url=f"{self._host}{uri}",
                        content=json_str,
                        headers=headers,
                    )
                    
                    if not response_data or not response_data.get("items"):
                        logger.info(f"关键词 '{keyword}' 第 {page_num} 页没有更多内容了。")
                        break

                    # 保存数据
                    file_path = f"data/xhs_search_{keyword}_page_{page_num}.json"
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(response_data["items"], f, ensure_ascii=False, indent=4)
                    logger.info(f"已将 '{keyword}' 第 {page_num} 页的结果保存到 {file_path}")

                    if not response_data.get("has_more"):
                        logger.info(f"关键词 '{keyword}' 已搜索完毕。")
                        break
                    
                    page_num += 1
                    await asyncio.sleep(random.uniform(2, 4))

                except Exception as e:
                    logger.error(f"搜索 '{keyword}' 第 {page_num} 页时出错: {e}")
                    import traceback
                    traceback.print_exc()
                    break

    async def start(self):
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
    try:
        crawler = XhsCrawler()
        asyncio.run(crawler.start())
        logger.info("脚本执行完毕。")
    except Exception as e:
        logger.error(f"在脚本顶层捕获到异常: {e}")
        import traceback
        traceback.print_exc()
