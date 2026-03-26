import pytesseract
from pytesseract import Output
from PIL import Image
import os
import cv2

# 指定 Tesseract 的可执行文件路径
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 设置 tessdata 环境变量，防止 Tesseract 找不到语言包
os.environ['TESSDATA_PREFIX'] = r'C:\Program Files\Tesseract-OCR\tessdata'

def test_tesseract_ocr(image_path, keyword):
    """
    测试 Tesseract 是否能从图片中识别特定文字，并返回其坐标。
    """
    if not os.path.exists(image_path):
        print(f"错误：找不到测试图片 '{image_path}'")
        return

    try:
        # 使用 OpenCV 读取并进行图像预处理以提升识别率
        img = cv2.imread(image_path)
        if img is None:
            print("图片加载失败")
            return
            
        # 预处理：放大、灰度化、二值化
        resized = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        # 整张截图测试时，建议使用 psm 11 寻找分散的文本，或 psm 3 (默认)
        config = "--oem 3 --psm 11"
        
        # 使用 image_to_data 获取包含坐标的详细信息字典
        d = pytesseract.image_to_data(binary, lang='chi_sim', config=config, output_type=Output.DICT)

        print("="*30)
        results = []
        n_boxes = len(d['text'])
        for i in range(n_boxes):
            text = d['text'][i].strip()
            if keyword in text:
                # 因为预处理时图像放大了 2 倍，所以识别出的坐标需要除以 2 来还原到原图
                x = int(d['left'][i] / 2)
                y = int(d['top'][i] / 2)
                w = int(d['width'][i] / 2)
                h = int(d['height'][i] / 2)
                center_x, center_y = x + w // 2, y + h // 2
                results.append({"text": text, "box": (x, y, w, h), "center": (center_x, center_y)})

        if results:
            print(f"识别到 '{keyword}'！共找到 {len(results)} 处：")
            for item in results:
                print(f"- 匹配文本: '{item['text']}', 区域(x,y,w,h): {item['box']}, 推荐点击中心点: {item['center']}")
        else:
            print(f"未能识别出 '{keyword}' 字样。")
        print("="*30)
        
        return results if results else None

    except Exception as e:
        print(f"发生了一个错误：{e}")

def print_all_text(image_path):
    """
    读取图片并打印出识别到的所有文字。
    """
    if not os.path.exists(image_path):
        print(f"错误：找不到测试图片 '{image_path}'")
        return

    try:
        img = cv2.imread(image_path)
        if img is None:
            print("图片加载失败")
            return
            
        # 预处理：放大、灰度化、二值化
        resized = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        config = "--oem 3 --psm 11"
        text = pytesseract.image_to_string(binary, lang='chi_sim', config=config)

        print("="*30)
        print(f"图片 '{image_path}' 中的全部文字识别结果：\n")
        print(text.strip() if text.strip() else "未能识别出任何文字。")
        print("="*30)
        return text.strip()

    except Exception as e:
        print(f"发生了一个错误：{e}")

if __name__ == "__main__":
    test_image = os.path.join("screenshots", "N0URB50103_screen.png")
    
    # 打印图片中所有的文字
    print_all_text(test_image)
    
    # 传入图片路径和想要查找的关键词
    test_tesseract_ocr(test_image, keyword="领取成功")