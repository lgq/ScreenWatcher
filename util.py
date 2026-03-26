
import asyncio
import os
import time
from typing import Optional, Tuple, List, Dict, Any

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage import StorageFile, FileAccessMode
from PIL import Image

import adb_util
from config_manager import CONFIG, load_config


async def find_text_in_image(image_path: str, target_text: str) -> Optional[Tuple[int, int, int, int]]:
    """
    使用 winrt OCR 识别指定图片中是否包含指定的文字。

    :param image_path: 图片的路径
    :param target_text: 要查找的文字
    :return: 如果找到，返回文字在图片中的坐标 (x, y, width, height)，否则返回 None
    """
    abs_path = os.path.abspath(image_path)
    if not os.path.exists(abs_path):
        print(f"图片不存在: {abs_path}")
        return None

    try:
        # 1. 读取文件并解码为 SoftwareBitmap
        file = await StorageFile.get_file_from_path_async(abs_path)
        stream = await file.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        software_bitmap = await decoder.get_software_bitmap_async()

        # 2. 初始化 OCR 引擎
        lang = Language("zh-Hans-CN")
        if not OcrEngine.is_language_supported(lang):
            print(f"当前 Windows 系统未安装该语言包: {lang.language_tag}")
            return None
        engine = OcrEngine.try_create_from_language(lang)
        if not engine:
            print("创建 OCR 引擎失败")
            return None

        # 3. 执行识别
        result = await engine.recognize_async(software_bitmap)

        # 4. 查找目标文字并计算坐标
        for line in result.lines:
            # 移除空格以便更稳定地匹配
            cleaned_line_text = line.text.replace(' ', '')

            if target_text in cleaned_line_text:
                # 如果找到，则合并该行所有单词的边界框
                if not line.words:
                    continue
                
                min_x = min(w.bounding_rect.x for w in line.words)
                min_y = min(w.bounding_rect.y for w in line.words)
                max_right = max(w.bounding_rect.x + w.bounding_rect.width for w in line.words)
                max_bottom = max(w.bounding_rect.y + w.bounding_rect.height for w in line.words)

                return (min_x, min_y, max_right - min_x, max_bottom - min_y)

    except Exception as e:
        print(f"处理图片时发生错误: {e}")

    return None


async def find_text_in_image_with_scope(image_path: str, target_text: str, scope: str) -> Optional[Tuple[int, int, int, int]]:
    """
    先按范围裁剪图片，然后再调用 OCR 识别文字，并将坐标映射回原图。
    
    :param image_path: 图片的路径
    :param target_text: 要查找的文字
    :param scope: 裁剪范围，'top' / 'center' / 'bottom'
    :return: 映射回原图的坐标 (x, y, width, height)
    """
    if scope not in ['top', 'center', 'bottom']:
        return await find_text_in_image(image_path, target_text)
        
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            
            if scope == 'top':
                box = (0, 0, width, int(height * 0.2))
            elif scope == 'center':
                box = (0, int(height * 0.2), width, int(height * 0.8))
            elif scope == 'bottom':
                box = (0, int(height * 0.8), width, height)
                
            cropped_img = img.crop(box)
            temp_path = f"{image_path}.{scope}.png"
            cropped_img.save(temp_path)
            
        try:
            coords = await find_text_in_image(temp_path, target_text)
        finally:
            # 无论识别成功还是失败，都清理掉裁剪的临时图片
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
        if coords:
            x, y, w, h = coords
            return (x + box[0], y + box[1], w, h)
    except Exception as e:
        print(f"裁剪图片时发生错误: {e}")
        
    return None

async def get_all_text_from_image(image_path: str) -> List[Dict[str, Any]]:
    """
    使用 winrt OCR 识别图片中所有的文字及其坐标。

    :param image_path: 图片的路径
    :return: 一个列表，包含识别到的每一行文字及其边界框坐标，例如 [{"text": "示例", "box": (x, y, w, h)}]
    """
    abs_path = os.path.abspath(image_path)
    if not os.path.exists(abs_path):
        print(f"图片不存在: {abs_path}")
        return []

    try:
        file = await StorageFile.get_file_from_path_async(abs_path)
        stream = await file.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        software_bitmap = await decoder.get_software_bitmap_async()

        lang = Language("zh-Hans-CN")
        if not OcrEngine.is_language_supported(lang):
            print(f"当前 Windows 系统未安装该语言包: {lang.language_tag}")
            return []
        engine = OcrEngine.try_create_from_language(lang)
        if not engine:
            print("创建 OCR 引擎失败")
            return []

        result = await engine.recognize_async(software_bitmap)
        
        recognized_texts = []
        for line in result.lines:
            if not line.words:
                continue
                
            min_x = int(min(w.bounding_rect.x for w in line.words))
            min_y = int(min(w.bounding_rect.y for w in line.words))
            max_right = int(max(w.bounding_rect.x + w.bounding_rect.width for w in line.words))
            max_bottom = int(max(w.bounding_rect.y + w.bounding_rect.height for w in line.words))

            recognized_texts.append({
                "text": line.text,
                "box": (min_x, min_y, max_right - min_x, max_bottom - min_y)
            })

        return recognized_texts

    except Exception as e:
        print(f"处理图片时发生错误: {e}")

    return []


async def main():
    """测试函数"""
    if not load_config():
        return
    
    adb_path_str = CONFIG['settings']['adb_path']
    # 获取连接的设备
    devices = adb_util.get_connected_devices(adb_path_str)
        
    if not devices:
        print("未检测到任何设备，等待中...")
    else:
        print(f"\n检测到 {len(devices)} 个设备: {devices}")
        for device_serial in devices:

            screenshot_dir = CONFIG['settings']['screenshot_dir']
            screenshot_path = os.path.join(screenshot_dir, f"{device_serial}_{int(time.time())}.png")
            if not adb_util.take_screenshot(CONFIG['settings']['adb_path'], device_serial, screenshot_path):
                # 截图失败，跳过此设备
                return

            image_path = screenshot_path
            # text_to_find = "允许"
            # text_to_find = "设置"
            # text_to_find = "×"
            # text_to_find = "领取奖励"
            # text_to_find = "坚持退出"
            text_to_find = "看视频+"
            
            print(f"在图片 '{image_path}' 中查找文字: '{text_to_find}'")
            
            coordinates = await find_text_in_image(image_path, text_to_find)
            
            if coordinates:
                x, y, w, h = coordinates
                # center_x = x + w / 2
                center_x = x + w -10 # 尝试点击文字右侧一点的位置，避免点击到文字本身可能较小的区域
                center_y = y + h / 2
                print(f"找到了！")
                print(f"  > 坐标: [x:{x}, y:{y}, w:{w}, h:{h}]")
                print(f"  > 中心点: ({center_x:.1f}, {center_y:.1f})")
                
                # adb_util.click(CONFIG['settings']['adb_path'], device_serial, center_x, center_y)
            else:
                print("没有找到指定的文字。")
                
            print("\n--- 测试获取所有文字 ---")
            all_texts = await get_all_text_from_image(image_path)
            if all_texts:
                print(f"共识别到 {len(all_texts)} 行文字：")
                for item in all_texts:
                    print(f"  > 文本: '{item['text']}', 坐标: {item['box']}")
            else:
                print("未能识别到任何文字或图片不存在。")


if __name__ == "__main__":
    asyncio.run(main())
