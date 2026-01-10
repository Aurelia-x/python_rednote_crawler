import os
import time
import json
import requests
import re
from urllib.parse import quote

# Configuration
KEYWORDS = "网购 退货 拆快递 六格 漫画"
SAVE_DIR = os.path.join("data", "images")
JSON_PATH = os.path.join("data", "baidu_raw_data.json")
MIN_RESOLUTION = 500
MIN_TEXT_LEN = 10
TARGET_COUNT = 30  # Aim for a bit more than 20 to be safe

def init_dirs():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)
    
    # Ensure parent dir for JSON exists
    json_dir = os.path.dirname(JSON_PATH)
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)

def get_image_url(url):
    """
    Sometimes the URL from Baidu API is not direct or needs headers.
    Usually thumbURL or middleURL works directly.
    """
    return url

def clean_text(text):
    """
    Clean the text title: remove html tags, extra spaces.
    """
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove special chars and extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def download_image(url, save_path):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            "Referer": "https://image.baidu.com/"
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(response.content)
            return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
    return False

def run_crawler():
    init_dirs()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/plain, */*; q=0.01",
        "Referer": "https://image.baidu.com/search/index?tn=baiduimage",
        "X-Requested-With": "XMLHttpRequest",
    }
    
    encoded_keyword = quote(KEYWORDS)
    base_url = "https://image.baidu.com/search/acjson"
    
    collected_data = {}
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                collected_data = json.load(f)
        except:
            pass
            
    current_count = len(collected_data)
    page_pn = 0
    page_rn = 30 # items per page
    
    print(f"Starting crawl for keyword: {KEYWORDS}")
    print(f"Target count: {TARGET_COUNT}, Current count: {current_count}")
    
    while current_count < TARGET_COUNT:
        params = {
            "tn": "resultjson_com",
            "logid": "8846387063499426462",
            "ipn": "rj",
            "ct": "201326592",
            "is": "",
            "fp": "result",
            "queryWord": KEYWORDS,
            "cl": "2",
            "lm": "-1",
            "ie": "utf-8",
            "oe": "utf-8",
            "adpicid": "",
            "st": "-1",
            "z": "",
            "ic": "",
            "hd": "",
            "latest": "",
            "copyright": "",
            "word": KEYWORDS,
            "s": "",
            "se": "",
            "tab": "",
            "width": "",
            "height": "",
            "face": "0",
            "istype": "2",
            "qc": "",
            "nc": "1",
            "fr": "",
            "expermode": "",
            "force": "undefined",
            "pn": page_pn,
            "rn": page_rn,
            "gsm": hex(page_pn)[2:],
            "1689234834834": "" # Timestamp-like
        }
        
        try:
            print(f"Fetching page starting at {page_pn}...")
            response = requests.get(base_url, params=params, headers=headers, timeout=10)
            
            try:
                # Sometimes the response might be weird or not valid JSON if we get blocked
                # But Baidu Images is usually lenient
                # The content type might be text/plain or text/javascript
                # We need to handle potential JSON errors
                # Clean up response text if it has invalid chars? Usually requests.json() handles it if headers are right.
                # But sometimes Baidu returns single quotes which is not valid JSON strictly but Python's eval might handle, 
                # but json.loads expects double quotes. 
                # Let's try standard json decode first.
                
                # Sometimes Baidu returns `text/html` with error if blocked.
                if "text/html" in response.headers.get("Content-Type", ""):
                     print("Received HTML instead of JSON. Might be blocked or end of results.")
                     # Check content
                     # print(response.text[:200])
                     break
                
                # Baidu sometimes escapes forward slashes as \/, which is fine.
                # But sometimes there are issues.
                # Let's try to parse.
                # Some implementations suggest `response.content.decode('utf-8')` then replace `\'`?
                # Actually, standard json.loads usually works for this API.
                
                # However, if there are issues, we might need a custom parser or `demjson`.
                # For now, let's assume valid JSON.
                data = response.json()
                
            except json.JSONDecodeError:
                print("Failed to decode JSON. Response might be malformed.")
                # Fallback: try to clean specific known issues if any
                try:
                    # simplistic fix for common single quote issue if it exists (rare for this specific API endpoint)
                    text = response.text.replace("'", '"')
                    data = json.loads(text)
                except:
                    print("Could not recover JSON.")
                    break
            
            if not data or "data" not in data:
                print("No data in response.")
                break
                
            items = data["data"]
            if not items:
                print("Empty data list.")
                break
                
            new_items_found = False
            
            for item in items:
                if current_count >= TARGET_COUNT:
                    break
                
                # item can be empty sometimes in the list (last element often empty)
                if not item:
                    continue
                    
                # Extract fields
                thumb_url = item.get("thumbURL")
                middle_url = item.get("middleURL")
                hover_url = item.get("hoverURL")
                
                # Prefer middle or hover for better quality
                image_url = middle_url or hover_url or thumb_url
                
                if not image_url:
                    continue
                    
                # Text
                from_page_title = item.get("fromPageTitle", "")
                from_page_title = clean_text(from_page_title)
                
                # Resolution
                width = item.get("width", 0)
                height = item.get("height", 0)
                
                # Filter
                # 1. Resolution
                # Note: width/height in JSON might be int or string
                try:
                    w = int(width)
                    h = int(height)
                except:
                    w = 0
                    h = 0
                
                if w < MIN_RESOLUTION and h < MIN_RESOLUTION:
                    # print(f"Skipping low res: {w}x{h}")
                    continue
                    
                # 2. Text Length
                if len(from_page_title) < MIN_TEXT_LEN:
                    # print(f"Skipping short text: {from_page_title}")
                    continue
                
                # Check duplication by URL or Title?
                # Image URL is better key.
                # But we want to use a unique ID for filename.
                
                # Let's check if we already have this image_url in our data
                # We iterate collected_data values to check 'source_url'
                is_duplicate = False
                for k, v in collected_data.items():
                    if v.get("source_url") == image_url:
                        is_duplicate = True
                        break
                
                if is_duplicate:
                    continue
                
                # Generate ID
                # Use timestamp + index to ensure uniqueness
                img_id = f"baidu_{int(time.time())}_{current_count+1}"
                
                # Download
                ext = ".jpg"
                if ".png" in image_url:
                    ext = ".png"
                elif ".webp" in image_url:
                    ext = ".webp"
                elif ".gif" in image_url:
                    ext = ".gif"
                
                filename = f"{img_id}{ext}"
                save_path = os.path.join(SAVE_DIR, filename)
                
                print(f"Downloading {image_url} -> {filename}")
                if download_image(image_url, save_path):
                    # Save metadata
                    # Use filename as key
                    collected_data[filename] = {
                        "id": img_id,
                        "image_path": save_path,
                        "relative_path": os.path.join("data", "images", filename),
                        "text": from_page_title,
                        "source_url": image_url,
                        "width": w,
                        "height": h
                    }
                    current_count += 1
                    new_items_found = True
                    print(f"Saved. Total: {current_count}")
                else:
                    print("Download failed.")
            
            if not new_items_found:
                print("No new valid items found on this page.")
                # If we keep getting no new items, we might need to stop eventually
                # But maybe next page has some.
            
            page_pn += page_rn
            time.sleep(1) # Be polite
            
        except Exception as e:
            print(f"Error during request: {e}")
            time.sleep(2)
            
    # Save JSON
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(collected_data, f, ensure_ascii=False, indent=4)
        
    print(f"Finished. Total items: {len(collected_data)}")
    print(f"Metadata saved to {JSON_PATH}")

if __name__ == "__main__":
    run_crawler()
