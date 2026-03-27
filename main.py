
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
    
    # 0. 获取当前运行的 App 包名并加载对应配置
    adb_path = CONFIG['settings']['adb_path']
    current_app = adb_util.get_foreground_app(adb_path, device_serial)
    
    if current_app:
        app_config_path = f"{current_app}_config.json"
        if os.path.exists(app_config_path):
            print(f"[{device_serial}] 当前前台应用: '{current_app}'，正在加载专属配置: {app_config_path}")
            load_config(config_path=app_config_path)
        else:
            print(f"[{device_serial}] 未找到 '{current_app}' 的专属配置，回退使用默认 config.json")
            load_config(config_path="config.json")
    else:
        print(f"[{device_serial}] 无法获取前台应用或处于桌面，回退使用默认 config.json")
        load_config(config_path="config.json")

    # 1. 若当前 activity 在配置的 back_activities 列表中，执行返回操作并结束
    back_activities = CONFIG.get('back_activities', [])
    if back_activities:
        current_activity = adb_util.get_current_activity(adb_path, device_serial)
        if current_activity and any(current_activity.endswith(act) or act in current_activity for act in back_activities):
            print(f"[{device_serial}] 当前 Activity '{current_activity}' 命中 back_activities，执行返回操作。")
            adb_util.back(adb_path, device_serial)
            return

    # 2. 截图
    screenshot_dir = CONFIG['settings']['screenshot_dir']
    screenshot_path = os.path.join(screenshot_dir, f"{device_serial}_{int(time.time())}.png")
    
    if not adb_util.take_screenshot(CONFIG['settings']['adb_path'], device_serial, screenshot_path):
        # 截图失败，跳过此设备
        return

    # 3. 识别界面并执行操作
    scenarios = CONFIG.get('scenarios', [])
    if not scenarios:
        print(f"[{device_serial}] 当前配置中没有可用场景，跳过处理。")
        
    for scenario in scenarios:
        # print(f"[{device_serial}] 正在检查界面: '{scenario['name']}'")
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
                
        # 检查是否包含不能出现的文字
        if is_match and 'screen_text_not_include' in scenario:
            not_include_config = scenario['screen_text_not_include']
            if isinstance(not_include_config, str):
                not_include_texts = [not_include_config]
            else:
                not_include_texts = not_include_config
                
            for text in not_include_texts:
                coords = await util.find_text_in_image(screenshot_path, text)
                if coords:
                    is_match = False
                    print(f"[{device_serial}] 界面 '{scenario['name']}' 匹配失败: 包含被排除的文字 '{text}'")
                    break

        if is_match:
            print(f"[{device_serial}] 识别到界面: '{scenario['name']}' (匹配文字: {screen_texts})")
            action = scenario['action']
            action_type = action['type']

            if action_type == 'click_coords':
                adb_util.click(adb_path, device_serial, action['x'], action['y'])

            elif action_type == 'click_text':
                target_text = action['target']
                scope = action.get('scope')
                
                print(f"[{device_serial}] 正在查找并点击文字: '{target_text}'" + (f" (范围: {scope})" if scope else ""))
                
                if scope:
                    target_coords = await util.find_text_in_image_with_scope(screenshot_path, target_text, scope)
                else:
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
    
    # 4. 清理截图
    try:
        os.remove(screenshot_path)
    except OSError as e:
        print(f"删除截图 {screenshot_path} 失败: {e}")


def main_loop():
    """
    主循环，按顺序测试在 settings_config.json 中配置的应用。
    """
    if not load_config():
        return

    app_loop_config = CONFIG['settings'].get('app_loop', [])
    if not app_loop_config:
        print("settings_config.json 中未配置 'app_loop'，程序退出。")
        return

    adb_path = CONFIG['settings']['adb_path']
    poll_interval = CONFIG['settings']['poll_interval_seconds']
    run_duration_minutes_per_app = CONFIG['settings'].get('run_duration_minutes', 30)
    run_duration_seconds_per_app = run_duration_minutes_per_app * 60
    
    print("="*20 + " 应用顺序监控开始 " + "="*20)

    for loop_item in app_loop_config:
        device_info = loop_item.get('device')
        if not device_info:
            continue

        device_id = device_info.get('id')
        device_name = device_info.get('name', device_id)
        icon_positions = device_info.get('test_icon_position_list', [])

        if not device_id or not icon_positions:
            print(f"设备 '{device_name}' 配置不完整 (缺少 id 或 test_icon_position_list)，跳过。")
            continue

        print(f"\n===== 开始在设备 {device_name} ({device_id}) 上执行测试 =====")

        for i, position in enumerate(icon_positions):
            x, y = position.get('x'), position.get('y')
            if x is None or y is None:
                continue

            print(f"\n--- ({i+1}/{len(icon_positions)}) 启动位于 ({x}, {y}) 的应用，持续 {run_duration_minutes_per_app} 分钟 ---")

            # 1. 返回桌面并点击图标启动应用
            adb_util.back_home(adb_path, device_id)
            time.sleep(2)  # 等待桌面稳定
            adb_util.click(adb_path, device_id, x, y)
            time.sleep(5)  # 等待应用启动

            # 2. 在指定时间内循环监控
            start_time = time.time()
            while time.time() - start_time < run_duration_seconds_per_app:
                asyncio.run(process_device(device_id))
                time.sleep(poll_interval)
            
            print(f"--- 应用 ({x}, {y}) 测试结束 ---")

        print(f"===== 设备 {device_name} ({device_id}) 所有测试完成 =====")

    print("\n="*20 + " 所有应用测试完成，程序退出。 " + "="*20)


if __name__ == "__main__":
    main_loop()
