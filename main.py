
import asyncio
import os
import time
from typing import Dict, Any

import adb_util
import util
from config_manager import CONFIG, load_config

async def process_device(device_serial: str):
    """
    处理单个设备：截图、识别、执行操作。
    """
    print(f"\n----- 正在处理设备: {device_serial} -----")
    
    # 1. 截图
    screenshot_dir = CONFIG['settings']['screenshot_dir']
    screenshot_path = os.path.join(screenshot_dir, f"{device_serial}_{int(time.time())}.png")
    
    if not adb_util.take_screenshot(CONFIG['settings']['adb_path'], device_serial, screenshot_path):
        # 截图失败，跳过此设备
        return

    # 2. 识别界面并执行操作
    for scenario in CONFIG['scenarios']:
        print(f"[{device_serial}] 正在检查界面: '{scenario['name']}'")
        screen_text_config = scenario['screen_text']
        
        # 兼容单个字符串或字符串列表（若是列表，则必须全部包含）
        if isinstance(screen_text_config, str):
            screen_texts = [screen_text_config]
        else:
            screen_texts = screen_text_config
            
        # 检查是否所有要求的文字都在屏幕上
        is_match = True
        for text in screen_texts:
            coords = await util.find_text_in_image(screenshot_path, text)
            if not coords:
                is_match = False
                break
                
        if is_match:
            print(f"[{device_serial}] 识别到界面: '{scenario['name']}' (匹配文字: {screen_texts})")
            action = scenario['action']
            action_type = action['type']
            adb_path = CONFIG['settings']['adb_path']

            if action_type == 'click_coords':
                adb_util.click(adb_path, device_serial, action['x'], action['y'])

            elif action_type == 'click_text':
                target_text = action['target']
                print(f"[{device_serial}] 正在查找并点击文字: '{target_text}'")
                target_coords = await util.find_text_in_image(screenshot_path, target_text)
                if target_coords:
                    x, y, w, h = target_coords
                    # center_x, center_y = x + w // 2, y + h // 2
                    center_x, center_y = x + w -10, y + h // 2
                    adb_util.click(adb_path, device_serial, center_x, center_y)
                else:
                    print(f"[{device_serial}] 未在屏幕上找到可点击的文字: '{target_text}'")

            elif action_type == 'swipe':
                adb_util.swipe(
                    adb_path, device_serial,
                    action['start_x'], action['start_y'],
                    action['end_x'], action['end_y'], action['duration_ms']
                )

            elif action_type == 'launch_app':
                adb_util.launch_app(adb_path, device_serial, action['package'])
            
            # 找到匹配的场景并执行操作后，就不再检查此屏幕的其他场景
            break 
    else:
        print(f"[{device_serial}] 未识别到任何已配置的界面。")
    
    # 3. 清理截图
    try:
        os.remove(screenshot_path)
    except OSError as e:
        print(f"删除截图 {screenshot_path} 失败: {e}")


def main_loop():
    """
    主轮询循环。
    """
    if not load_config():
        return

    # 循环设定
    run_duration_seconds = CONFIG['settings']['run_duration_minutes'] * 60
    poll_interval = CONFIG['settings']['poll_interval_seconds']
    start_time = time.time()
    
    print("="*20 + " 屏幕监控开始 " + "="*20)
    print(f"配置加载成功！将运行 {CONFIG['settings']['run_duration_minutes']} 分钟，每 {poll_interval} 秒轮询一次。")

    while time.time() - start_time < run_duration_seconds:
        adb_path = CONFIG['settings']['adb_path']
        
        # 获取连接的设备
        devices = adb_util.get_connected_devices(adb_path)
        
        if not devices:
            print("未检测到任何设备，等待中...")
        else:
            print(f"\n检测到 {len(devices)} 个设备: {devices}")
            for device in devices:
                # 对每个设备异步执行处理函数
                asyncio.run(process_device(device))
        
        # 等待下一次轮询
        time.sleep(poll_interval)

    print("\n="*20 + " 运行时间结束，程序退出。 " + "="*20)


if __name__ == "__main__":
    main_loop()
