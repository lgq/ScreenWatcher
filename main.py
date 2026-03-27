
import asyncio
import os
import random
import time
from typing import Dict, Any

import adb_util
import util
from config_manager import CONFIG, load_config


def _is_activity_match(current_activity: str, targets: Any) -> bool:
    """
    判断当前 activity 是否命中配置。
    targets 支持字符串或字符串列表，命中规则为 contains。
    """
    if not current_activity:
        return False

    if isinstance(targets, str):
        target_list = [targets]
    else:
        target_list = targets or []

    for target in target_list:
        if not target:
            continue
        if target in current_activity:
            return True

    return False


async def _maybe_activity_random_swipe_up(device_serial: str, current_activity: str, adb_path: str) -> bool:
    """
    若命中指定 activity，则随机等待后执行上滑并返回 True。
    配置示例（放在 config.json 或 app 专属配置根节点）:
    {
      "activity_random_swipe_up": {
        "enabled": true,
        "activities": ["com.xxx/.VideoActivity", "ShortPlayActivity"],
        "interval_min_seconds": 10,
        "interval_max_seconds": 15,
        "start_x": 500,
        "start_y": 1500,
        "end_x": 500,
        "end_y": 500,
        "duration_ms": 200
      }
    }
    """
    swipe_cfg = CONFIG.get('activity_random_swipe_up')
    if not swipe_cfg:
        return False

    if not isinstance(swipe_cfg, dict):
        return False

    if swipe_cfg.get('enabled', True) is False:
        return False

    activities = swipe_cfg.get('activities', [])
    if not _is_activity_match(current_activity, activities):
        return False

    interval_min = int(swipe_cfg.get('interval_min_seconds', 10))
    interval_max = int(swipe_cfg.get('interval_max_seconds', 15))
    if interval_min < 1:
        interval_min = 1
    if interval_max < interval_min:
        interval_max = interval_min

    # 获取基准坐标（配置中的默认值）
    base_start_x = int(swipe_cfg.get('start_x', 500))
    base_start_y = int(swipe_cfg.get('start_y', 901))
    base_end_x = int(swipe_cfg.get('end_x', 500))
    base_end_y = int(swipe_cfg.get('end_y', 600))
    base_duration_ms = int(swipe_cfg.get('duration_ms', 150))

    # 获取随机生成的范围（可选配置）
    swipe_distance_min = int(swipe_cfg.get('swipe_distance_min', -50))
    swipe_distance_max = int(swipe_cfg.get('swipe_distance_max', 50))
    x_variance = int(swipe_cfg.get('x_variance', 20))  # 水平方向浮动范围
    duration_min_ms = int(swipe_cfg.get('duration_min_ms', 50))
    duration_max_ms = int(swipe_cfg.get('duration_max_ms', 100))

    # 随机生成实际执行的滑动参数
    actual_start_x = base_start_x + random.randint(-x_variance, x_variance)
    actual_start_y = base_start_y
    swipe_distance = random.randint(swipe_distance_min, swipe_distance_max)
    actual_end_x = base_start_x + random.randint(-x_variance, x_variance)
    actual_end_y = base_end_y - swipe_distance
    actual_duration_ms = random.randint(duration_min_ms, duration_max_ms)

    wait_seconds = random.uniform(interval_min, interval_max)
    print(
        f"[{device_serial}] 当前 Activity '{current_activity}' 命中 activity_random_swipe_up，"
        f"将在 {wait_seconds:.1f}s 后执行上滑并跳过本轮监控"
    )
    await asyncio.sleep(wait_seconds)

    print(
        f"[{device_serial}] 执行随机上滑: ({actual_start_x}, {actual_start_y}) "
        f"-> ({actual_end_x}, {actual_end_y})，耗时 {actual_duration_ms}ms"
    )
    adb_util.swipe(adb_path, device_serial, actual_start_x, actual_start_y, actual_end_x, actual_end_y, actual_duration_ms)
    return True

async def process_device(device_serial: str):
    """
    处理单个设备：截图、识别、执行操作。
    """
    print(f"\n----- 正在处理设备: {device_serial} -----")
    
    # 0. 获取当前运行的 App 包名并加载对应配置
    adb_path = CONFIG['settings']['adb_path']
    keep_scope_temp_images = bool(CONFIG['settings'].get('keep_scope_temp_images', False))
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

    current_activity = adb_util.get_current_activity(adb_path, device_serial)

    # 1. 若当前 activity 命中 activity_random_swipe_up，则随机延时后上滑并结束本轮
    if await _maybe_activity_random_swipe_up(device_serial, current_activity, adb_path):
        return

    # 2. 若当前 activity 在配置的 back_activities 列表中，执行返回操作并结束
    back_activities = CONFIG.get('back_activities', [])
    if back_activities:
        if current_activity and any(current_activity.endswith(act) or act in current_activity for act in back_activities):
            print(f"[{device_serial}] 当前 Activity '{current_activity}' 命中 back_activities，执行返回操作。")
            adb_util.back(adb_path, device_serial)
            return

    # 3. 截图
    screenshot_dir = CONFIG['settings']['screenshot_dir']
    screenshot_path = os.path.join(screenshot_dir, f"{device_serial}_{int(time.time())}.png")
    
    if not adb_util.take_screenshot(CONFIG['settings']['adb_path'], device_serial, screenshot_path):
        # 截图失败，跳过此设备
        return

    # 4. 识别界面并执行操作
    scenarios = CONFIG.get('scenarios', [])
    if not scenarios:  
        print(f"[{device_serial}] 当前配置中没有可用场景，跳过处理。")
        
    for scenario in scenarios:
        # print(f"[{device_serial}] 正在检查界面: '{scenario['name']}'")
        action = scenario.get('action', {})
        scope = scenario.get('scope') or action.get('scope')

        async def find_text_for_scenario(text: str):
            if scope:
                return await util.find_text_in_image_with_scope(
                    screenshot_path,
                    text,
                    scope,
                    keep_temp=keep_scope_temp_images,
                )
            return await util.find_text_in_image(screenshot_path, text)

        screen_text_config = scenario['screen_text']
        
        # 兼容单个字符串或字符串列表（若是列表，则必须全部包含）
        if isinstance(screen_text_config, str):
            screen_texts = [screen_text_config]
        else:
            screen_texts = screen_text_config
            
        # 检查是否所有要求的文字都在屏幕上
        is_match = True
        for text in screen_texts:
            coords = await find_text_for_scenario(text)
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
                coords = await find_text_for_scenario(text)
                if coords:
                    is_match = False
                    print(f"[{device_serial}] 界面 '{scenario['name']}' 匹配失败: 包含被排除的文字 '{text}'")
                    break

        if is_match:
            print(
                f"[{device_serial}] 识别到界面: '{scenario['name']}' "
                f"(匹配文字: {screen_texts}" + (f", scope: {scope}" if scope else "") + ")"
            )
            action_type = action.get('type')

            if not action_type:
                # 允许场景仅识别，不配置 action
                break

            if action_type == 'click_coords':
                adb_util.click(adb_path, device_serial, action['x'], action['y'])

            elif action_type == 'click_text':
                target_text = action['target']
                
                print(f"[{device_serial}] 正在查找并点击文字: '{target_text}'" + (f" (范围: {scope})" if scope else ""))
                target_coords = await find_text_for_scenario(target_text)
                    
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
    
    # 5. 清理截图
    try:
        os.remove(screenshot_path)
    except OSError as e:
        print(f"删除截图 {screenshot_path} 失败: {e}")


def get_device_app_loop_config(device_id: str) -> Dict[str, Any]:
    """
    根据设备ID从app_loop配置中查找对应的配置。
    如果找到则返回该配置，否则返回空字典。
    """
    app_loop_config = CONFIG['settings'].get('app_loop', [])
    for loop_item in app_loop_config:
        device_info = loop_item.get('device', {})
        if device_info.get('id') == device_id:
            return loop_item
    return {}


async def monitor_device_with_app_loop(device_id: str, device_config: Dict[str, Any], adb_path: str, poll_interval: int):
    """
    对有 app_loop 配置的设备，进行 APP 轮换监控。
    """
    device_name = device_config.get('name', device_id)
    icon_positions = device_config.get('test_icon_position_list', [])
    run_duration_minutes = CONFIG['settings'].get('run_duration_minutes', 30)
    run_duration_seconds = run_duration_minutes * 60
    
    print(f"\n[{device_id}] {device_name} - 启用 APP 轮换监控")
    
    while True:  # 持续监控此设备
        for i, position in enumerate(icon_positions):
            x, y = position.get('x'), position.get('y')
            if x is None or y is None:
                continue

            print(f"\n[{device_id}] --- ({i+1}/{len(icon_positions)}) 启动位于 ({x}, {y}) 的应用，持续 {run_duration_minutes} 分钟 ---")

            # 1. 返回桌面并点击图标启动应用
            adb_util.back_home(adb_path, device_id)
            await asyncio.sleep(2)  # 等待桌面稳定
            adb_util.click(adb_path, device_id, x, y)
            await asyncio.sleep(5)  # 等待应用启动

            # 2. 在指定时间内循环监控
            start_time = time.time()
            while time.time() - start_time < run_duration_seconds:
                await process_device(device_id)
                await asyncio.sleep(poll_interval)
            
            print(f"[{device_id}] --- 应用 ({x}, {y}) 测试结束 ---")


async def monitor_device_simple(device_id: str, adb_path: str, poll_interval: int):
    """
    对没有 app_loop 配置的设备，直接监控（不进行 APP 切换）。
    """
    print(f"\n[{device_id}] 启用简单监控模式（无 APP 轮换）")
    
    while True:  # 持续监控此设备
        try:
            # 检查设备是否仍然连接
            devices = adb_util.get_devices(adb_path)
            if device_id not in devices:
                print(f"[{device_id}] 设备已断开连接，停止监控")
                break
            
            await process_device(device_id)
            await asyncio.sleep(poll_interval)
        except Exception as e:
            print(f"[{device_id}] 监控过程中出错: {e}")
            await asyncio.sleep(poll_interval)


async def detect_and_monitor_devices(adb_path: str, poll_interval: int):
    """
    持续监听设备连接，为新设备启动监控任务。
    """
    device_tasks: Dict[str, asyncio.Task] = {}  # 跟踪每个设备的监控任务
    last_check_time = time.time()
    check_interval = 5  # 每5秒检查一次设备列表
    
    print("="*50)
    print(" 多设备动态监控开始（支持热插拔设备） ")
    print("="*50)
    
    try:
        while True:
            current_time = time.time()
            
            # 每5秒检查一次设备列表
            if current_time - last_check_time >= check_interval:
                last_check_time = current_time
                
                try:
                    connected_devices = adb_util.get_devices(adb_path)
                except Exception as e:
                    print(f"获取设备列表失败: {e}")
                    await asyncio.sleep(check_interval)
                    continue
                
                print(f"\n[系统] 当前连接的设备: {connected_devices if connected_devices else '无'}")
                
                # 为新连接的设备启动监控任务
                for device_id in connected_devices:
                    if device_id not in device_tasks or device_tasks[device_id].done():
                        print(f"[{device_id}] 检测到新设备或任务已结束，启动监控...")
                        
                        # 查询设备是否在 app_loop 配置中
                        app_loop_item = get_device_app_loop_config(device_id)
                        
                        if app_loop_item:
                            # 该设备有 APP 轮换配置
                            device_config = app_loop_item.get('device', {})
                            task = asyncio.create_task(
                                monitor_device_with_app_loop(device_id, device_config, adb_path, poll_interval)
                            )
                        else:
                            # 该设备无 APP 轮换配置，直接监控
                            task = asyncio.create_task(
                                monitor_device_simple(device_id, adb_path, poll_interval)
                            )
                        
                        device_tasks[device_id] = task
                
                # 清理已断开连接的设备的任务
                disconnected_devices = [d for d in device_tasks if d not in connected_devices]
                for device_id in disconnected_devices:
                    if device_tasks[device_id]:
                        device_tasks[device_id].cancel()
                        print(f"[{device_id}] 设备已断开，取消监控任务")
                        del device_tasks[device_id]
            
            # 保持主循环
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n" + "="*50)
        print(" 监控已停止（用户中断） ")
        print("="*50)
        # 取消所有任务
        for task in device_tasks.values():
            if task and not task.done():
                task.cancel()


async def main():
    """
    主异步函数，初始化配置并启动多设备监控。
    """
    if not load_config():
        print("配置加载失败，程序退出。")
        return

    adb_path = CONFIG['settings']['adb_path']
    poll_interval = CONFIG['settings']['poll_interval_seconds']
    
    # 启动设备监听和监控
    await detect_and_monitor_devices(adb_path, poll_interval)


if __name__ == "__main__":
    asyncio.run(main())
