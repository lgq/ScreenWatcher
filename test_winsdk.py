import asyncio
import os
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.storage import StorageFile, FileAccessMode

async def windows_ocr_demo(image_path: str):
    # UWP StorageFile API 强制要求传入绝对路径
    abs_path = os.path.abspath(image_path)
    if not os.path.exists(abs_path):
        print(f"图片不存在: {abs_path}")
        return

    # 1. 读取文件流
    file = await StorageFile.get_file_from_path_async(abs_path)
    stream = await file.open_async(FileAccessMode.READ)

    # 2. 解码图像数据获取 SoftwareBitmap
    decoder = await BitmapDecoder.create_async(stream)
    software_bitmap = await decoder.get_software_bitmap_async()

    # 3. 初始化 OCR 引擎
    # "zh-Hans-CN" 代表简体中文。也可以用 "en-US" 等。
    lang = Language("zh-Hans-CN")
    
    # 检查系统是否安装了对应的语言包
    if not OcrEngine.is_language_supported(lang):
        print(f"当前 Windows 系统未安装该语言包: {lang.language_tag}")
        print("请在 'Windows设置 -> 时间和语言 -> 语言' 中添加对应的首选语言。")
        return

    # 创建对应语言的 OCR 引擎
    # 也可以使用 OcrEngine.try_create_from_user_profile_languages() 使用系统默认语言
    engine = OcrEngine.try_create_from_language(lang)

    # 4. 执行识别
    print("正在识别中...")
    result = await engine.recognize_async(software_bitmap)

    # 5. 打印识别结果
    print("=" * 40)
    print("完整文本内容:")
    print(result.text)
    print("=" * 40)

    # 提取具体的坐标信息 (按行和词遍历)
    print("详细坐标信息:")
    for line_index, line in enumerate(result.lines):
        print(f"--- 第 {line_index + 1} 行: '{line.text}' ---")
        for word in line.words:
            rect = word.bounding_rect
            # 计算中心点坐标 (常用于自动化点击)
            center_x = rect.x + rect.width / 2
            center_y = rect.y + rect.height / 2
            print(f"  词: '{word.text: <6}', "
                  f"坐标: [x:{rect.x: >4}, y:{rect.y: >4}, w:{rect.width: >3}, h:{rect.height: >3}], "
                  f"中心点: ({center_x:.1f}, {center_y:.1f})")

if __name__ == "__main__":
    # 替换为你想要测试的图片路径
    # test_image = "test_screenshot.png" 
    test_image = os.path.join("screenshots", "N0URB50103_screen.png")
    
    # 因为涉及到异步操作，使用 asyncio.run 来执行
    asyncio.run(windows_ocr_demo(test_image))
