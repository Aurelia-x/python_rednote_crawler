
import json
import os
import re
from PIL import Image
from loguru import logger

def filter_data():
    data_dir = "data_final"
    json_path = os.path.join(data_dir, "annotations.json")
    
    if not os.path.exists(json_path):
        logger.error(f"{json_path} 不存在。")
        return

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            annotations = json.load(f)
    except Exception as e:
        logger.error(f"读取 {json_path} 失败: {e}")
        return

    logger.info(f"开始过滤，当前共有 {len(annotations)} 条数据。")
    
    keys_to_remove = []
    removed_counts = {
        "text_too_short": 0,
        "image_too_small": 0,
        "file_not_found": 0
    }

    for key, item in annotations.items():
        image_path = item.get("image_path")
        desc = item.get("content", {}).get("desc", "")
        
        # 1. 检查文件是否存在
        if not os.path.exists(image_path):
            logger.warning(f"文件不存在: {image_path}")
            keys_to_remove.append(key)
            removed_counts["file_not_found"] += 1
            continue

        # 2. 检查文本长度 (中文字符 >= 10)
        chinese_char_count = len(re.findall(r'[\u4e00-\u9fa5]', desc))
        if chinese_char_count < 10:
            logger.info(f"删除 {key}: 中文字符数不足 ({chinese_char_count})")
            keys_to_remove.append(key)
            removed_counts["text_too_short"] += 1
            # 删除文件
            try:
                os.remove(image_path)
            except Exception as e:
                logger.error(f"删除文件 {image_path} 失败: {e}")
            continue

        # 3. 检查图像分辨率 (宽和高 >= 500)
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                if width < 500 or height < 500:
                    logger.info(f"删除 {key}: 分辨率过低 ({width}x{height})")
                    keys_to_remove.append(key)
                    removed_counts["image_too_small"] += 1
                    # 删除文件 (需要先关闭图片，但 with 语句会自动关闭)
                else:
                    continue # 通过检查
        except Exception as e:
            logger.error(f"打开图片 {image_path} 失败: {e}")
            keys_to_remove.append(key)
            # 可能是损坏的文件，尝试删除
            try:
                os.remove(image_path)
            except:
                pass
            continue

        # 如果分辨率检查失败，需要在这里删除文件
        # 注意：在 with 块内不能删除，因为文件被占用（Windows下特别明显）
        # 所以上面的 else continue 是为了跳过下面的删除逻辑
        try:
            os.remove(image_path)
        except Exception as e:
             logger.error(f"删除文件 {image_path} 失败: {e}")

    # 从字典中移除
    for key in keys_to_remove:
        if key in annotations:
            del annotations[key]

    # 清理空文件夹
    # 遍历 data_final/image 下的所有子文件夹
    image_root = os.path.join(data_dir, "image")
    if os.path.exists(image_root):
        for note_id in os.listdir(image_root):
            note_dir = os.path.join(image_root, note_id)
            if os.path.isdir(note_dir):
                if not os.listdir(note_dir): # 如果文件夹为空
                    try:
                        os.rmdir(note_dir)
                        logger.info(f"移除空文件夹: {note_dir}")
                    except Exception as e:
                        logger.error(f"移除文件夹 {note_dir} 失败: {e}")

    # 保存更新后的 JSON
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(annotations, f, ensure_ascii=False, indent=4)

    logger.info("过滤完成。")
    logger.info(f"剩余数据量: {len(annotations)}")
    logger.info(f"删除统计: {removed_counts}")

if __name__ == "__main__":
    filter_data()
