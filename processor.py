import json
import os
from PIL import Image

# ================= 配置区域 =================
# 输入：爬虫抓取的原始数据元数据
RAW_DATA = os.path.join("data", "raw_data.json")
# 输出：经过清洗和处理后的最终数据
RESULT_DATA = os.path.join("data", "result.json")
# ===========================================

def process_data():
    """
    数据清洗与处理主函数
    功能：
    1. 读取爬虫生成的原始数据（支持多图结构）
    2. 验证图片文件是否存在
    3. 过滤低分辨率图片
    4. 过滤无效或过短的文本
    5. 生成最终的发布文案（添加Tag）
    6. 输出标准化的结果文件
    """
    if not os.path.exists(RAW_DATA):
        print(f"未找到原始数据: {RAW_DATA}")
        return

    with open(RAW_DATA, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
        
    final_data = {}
    valid_count = 0
    
    print("开始清洗数据...")
    
    for key, item in raw_data.items():
        # 兼容旧版数据结构（虽然现在应该都是新的了，但为了健壮性）
        if 'images' in item:
            img_paths = item['images']
        elif 'path' in item:
            img_paths = [item['path']]
        else:
            print(f"[-]{key}: 数据结构错误，无图片路径")
            continue

        raw_title = item.get('title', '')
        raw_content = item.get('content', '')
        # 如果旧版数据只有 text，则尝试作为 title
        if not raw_title and 'text' in item:
            raw_title = item['text']

        # 1. 图片清洗
        valid_imgs = []
        for img_path in img_paths:
            # 完整性检查
            if not os.path.exists(img_path):
                print(f"[-]{key}: 图片文件缺失 {img_path}")
                continue
            
            # 质量检查
            try:
                with Image.open(img_path) as img:
                    w, h = img.size
                    # 阈值 300x300
                    if w < 300 and h < 300:
                        print(f"[-]{key}: 分辨率过低 {w}x{h} ({os.path.basename(img_path)})")
                        continue
                    valid_imgs.append(os.path.abspath(img_path))
            except Exception as e:
                print(f"[-]{key}: 图片损坏 {e}")
                continue
        
        if not valid_imgs:
            print(f"[-]{key}: 无有效图片")
            continue

        # 2. 内容清洗
        # 简单清洗标题和正文
        clean_title = raw_title.strip()
        clean_content = raw_content.strip()

        if len(clean_title) < 2 and len(clean_content) < 5:
             print(f"[-]{key}: 文本内容过少")
             continue
             
        # 3. 数据标准化与文案优化
        # 组合标题和正文，并添加标签
        final_text = f"{clean_title}\n\n{clean_content}\n\n😂😂😂\n\n#网购 #搞笑 #日常 #避坑指南 #拆快递 #退货 #漫画分享 #六宫格"
        
        final_data[key] = {
            "images": valid_imgs,           # 有效图片列表（绝对路径）
            "title": clean_title,           # 单独保存标题，方便发布
            "text": final_text,             # 处理后的完整发布文案
            "original_title": raw_title,
            "original_content": raw_content
        }
        valid_count += 1
        print(f"[+]{key}: 有效 ({len(valid_imgs)} 张图片)")
        
    # 保存处理结果
    with open(RESULT_DATA, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=4)
        
    print(f"\n处理完成！")
    print(f"原始笔记: {len(raw_data)} 条")
    print(f"有效笔记: {valid_count} 条")
    print(f"结果已保存至: {RESULT_DATA}")

if __name__ == "__main__":
    process_data()
