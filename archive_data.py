import os
import shutil
from datetime import datetime

def archive_data():
    # 定义基础路径
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data')
    data_past_dir = os.path.join(base_dir, 'data_past')
    
    # 源文件/文件夹
    image_dir = os.path.join(data_dir, 'image')
    annotations_file = os.path.join(data_dir, 'annotations.json')
    
    # 检查源文件是否存在
    has_image = os.path.exists(image_dir)
    has_annotations = os.path.exists(annotations_file)
    
    if not has_image and not has_annotations:
        print("No data to archive (image folder and annotations.json not found).")
        return

    # 生成时间戳文件夹名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive_dir = os.path.join(data_past_dir, timestamp)
    
    # 创建归档目录
    try:
        if not os.path.exists(archive_dir):
            os.makedirs(archive_dir)
            print(f"Created archive directory: {archive_dir}")
            
        # 移动 image 文件夹
        if has_image:
            # 目标路径: data_past/<timestamp>/image
            # shutil.move(src, dst) 如果 dst 是目录，src 会被移动到 dst 内部
            shutil.move(image_dir, archive_dir)
            print(f"Moved {image_dir} to {archive_dir}")
        else:
            print(f"Image directory not found: {image_dir}")

        # 移动 annotations.json
        if has_annotations:
            shutil.move(annotations_file, archive_dir)
            print(f"Moved {annotations_file} to {archive_dir}")
        else:
            print(f"Annotations file not found: {annotations_file}")

        print("Archive completed successfully.")
        
    except Exception as e:
        print(f"An error occurred during archiving: {e}")

if __name__ == "__main__":
    archive_data()
