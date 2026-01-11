import os
import shutil
import json

# ================= 配置区域 =================
# 在这里填写需要添加到 final 数据集的笔记 ID (文件夹名)
# 每次执行此脚本，会将这些 ID 对应的图片和标注添加到 data_final 中
TARGET_NOTE_IDS = [
    "695e3afd000000002200bcde",
    "680655d5000000001b038363"
]

# 基础路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 源目录 (data)
SRC_DATA_DIR = os.path.join(BASE_DIR, 'data')
SRC_IMAGE_DIR = os.path.join(SRC_DATA_DIR, 'image')
SRC_ANNOTATIONS_FILE = os.path.join(SRC_DATA_DIR, 'annotations.json')

# 目标目录 (data_final)
DST_DATA_DIR = os.path.join(BASE_DIR, 'data_final')
DST_IMAGE_DIR = os.path.join(DST_DATA_DIR, 'image')
DST_ANNOTATIONS_FILE = os.path.join(DST_DATA_DIR, 'annotations.json')

# ===========================================

def add_to_final():
    print("Starting data selection process...")
    
    # 1. 确保源数据存在
    if not os.path.exists(SRC_IMAGE_DIR) or not os.path.exists(SRC_ANNOTATIONS_FILE):
        print("Error: Source data (data/image or data/annotations.json) not found.")
        return

    # 2. 确保目标目录存在
    if not os.path.exists(DST_IMAGE_DIR):
        os.makedirs(DST_IMAGE_DIR)
        print(f"Created directory: {DST_IMAGE_DIR}")

    # 3. 加载源标注数据
    try:
        with open(SRC_ANNOTATIONS_FILE, 'r', encoding='utf-8') as f:
            src_annotations = json.load(f)
    except Exception as e:
        print(f"Error loading source annotations: {e}")
        return

    # 4. 加载或初始化目标标注数据
    dst_annotations = {}
    if os.path.exists(DST_ANNOTATIONS_FILE):
        try:
            with open(DST_ANNOTATIONS_FILE, 'r', encoding='utf-8') as f:
                dst_annotations = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load existing final annotations, starting fresh. ({e})")

    # 5. 处理每个目标 ID
    added_count = 0
    updated_count = 0
    
    for note_id in TARGET_NOTE_IDS:
        print(f"\nProcessing Note ID: {note_id}")
        
        # --- 复制图片 ---
        src_note_path = os.path.join(SRC_IMAGE_DIR, note_id)
        dst_note_path = os.path.join(DST_IMAGE_DIR, note_id)
        
        if os.path.exists(src_note_path):
            # 如果目标已存在，先删除再复制，确保同步最新状态
            if os.path.exists(dst_note_path):
                shutil.rmtree(dst_note_path)
                updated_count += 1
                print(f"  - Updated image folder: {note_id}")
            else:
                added_count += 1
                print(f"  - Added image folder: {note_id}")
            
            shutil.copytree(src_note_path, dst_note_path)
        else:
            print(f"  - Warning: Source image folder not found for {note_id}")
            continue

        # --- 处理标注 ---
        # 查找属于该 note_id 的所有标注条目
        # 假设路径包含该 ID，例如 data\image\<note_id>\...
        
        for key, data in src_annotations.items():
            # 简单的字符串包含检查，或者根据路径结构解析
            # 路径分隔符可能是 / 或 \，统一处理
            normalized_key = key.replace('\\', '/')
            if f"/{note_id}/" in normalized_key or f"\\{note_id}\\" in key:
                
                # 构造新的 key 和 image_path
                # 将路径中的 data/ 替换为 data_final/
                # 注意：这里假设原始 key 以 data/ 或 data\ 开头
                
                new_key = key.replace('data\\', 'data_final\\').replace('data/', 'data_final/')
                
                # 深拷贝数据以免修改源数据
                new_data = data.copy()
                if 'image_path' in new_data:
                    new_data['image_path'] = new_data['image_path'].replace('data\\', 'data_final\\').replace('data/', 'data_final/')
                
                # 添加/更新到目标标注字典
                dst_annotations[new_key] = new_data
                # print(f"  - Added annotation: {new_key}")

    # 6. 保存目标标注数据
    try:
        with open(DST_ANNOTATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(dst_annotations, f, indent=4, ensure_ascii=False)
        print(f"\nSuccess! Saved annotations to {DST_ANNOTATIONS_FILE}")
        print(f"Total entries in final dataset: {len(dst_annotations)}")
        
    except Exception as e:
        print(f"Error saving final annotations: {e}")

if __name__ == "__main__":
    add_to_final()
