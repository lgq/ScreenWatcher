import asyncio
import os
import time
from typing import Any, Dict, Optional

import adb_util

from .action_executor import ActionExecutor
from .config_service import ConfigService
from .device_processor import DeviceProcessor
from .remote_sync import RemoteControlService


class DeviceMonitor:
    def __init__(
        self,
        config_service: ConfigService,
        device_processor: DeviceProcessor,
        remote_control_service: Optional[RemoteControlService] = None,
    ):
        self.config_service = config_service
        self.device_processor = device_processor
        self.remote_control_service = remote_control_service

    def _get_settings(self) -> Dict[str, Any]:
        return self.config_service.load_settings()

    def _get_device_app_loop_config(self, device_id: str) -> Optional[Dict[str, Any]]:
        app_loop_config = self._get_settings().get("app_loop", [])
        for loop_item in app_loop_config:
            device_info = loop_item.get("device", {})
            if device_info.get("id") == device_id:
                return loop_item
        return None

    def _get_device_app_monitor_cycle_config(self, device_id: str) -> Optional[Dict[str, Any]]:
        """从 app_monitor_cycle 配置中获取指定设备的循环应用列表配置。"""
        app_monitor_cycles = self._get_settings().get("app_monitor_cycle", [])
        for cycle_item in app_monitor_cycles:
            if cycle_item.get("device_id") == device_id:
                return cycle_item
        return None

    async def monitor_device_with_app_loop(self, device_id: str, device_config: Dict[str, Any]) -> None:
        device_name = device_config.get("name", device_id)
        icon_positions = device_config.get("test_icon_position_list", [])

        print(f"\n[{device_id}] {device_name} - 启用 APP 轮换监控")

        while True:
            settings = self._get_settings()
            adb_path = settings["adb_path"]
            poll_interval = settings["poll_interval_seconds"]
            run_duration_seconds = settings.get("run_duration_minutes", 30) * 60

            for index, position in enumerate(icon_positions):
                x, y = position.get("x"), position.get("y")
                if x is None or y is None:
                    continue

                print(
                    f"\n[{device_id}] --- ({index + 1}/{len(icon_positions)}) 启动位于 ({x}, {y}) 的应用，"
                    f"持续 {settings.get('run_duration_minutes', 30)} 分钟 ---"
                )
                adb_util.back_home(adb_path, device_id)
                await asyncio.sleep(2)
                adb_util.click(adb_path, device_id, x, y)
                await asyncio.sleep(5)

                start_time = time.time()
                while time.time() - start_time < run_duration_seconds:
                    await self.device_processor.process_device(device_id)
                    await asyncio.sleep(poll_interval)

                print(f"[{device_id}] --- 应用 ({x}, {y}) 测试结束 ---")

    async def monitor_device_with_app_cycle(self, device_id: str, cycle_config: Dict[str, Any]) -> None:
        """循环监控指定应用：启动应用 -> 执行进入动作 -> 监控指定时间 -> 返回桌面 -> 下一个应用。"""
        apps = cycle_config.get("apps", [])
        default_duration = cycle_config.get("default_duration_minutes", 30)

        print(f"\n[{device_id}] 启用应用循环监控模式，共 {len(apps)} 个应用")

        while True:
            settings = self._get_settings()
            adb_path = settings["adb_path"]
            poll_interval = settings["poll_interval_seconds"]
            keep_scope_temp_images = bool(settings.get("keep_scope_temp_images", False))
            action_executor = ActionExecutor(adb_path, keep_scope_temp_images)

            for index, app_info in enumerate(apps):
                package = app_info.get("package", "")
                app_name = app_info.get("name", package)
                if not package:
                    continue

                # 若应用单独配置了时长，使用应用级别配置；否则使用默认时长
                app_duration = app_info.get("duration_minutes")
                if app_duration is None:
                    app_duration = default_duration
                run_duration_seconds = app_duration * 60

                print(
                    f"\n[{device_id}] --- ({index + 1}/{len(apps)}) 启动应用: {app_name} ({package})，"
                    f"持续 {app_duration} 分钟 ---"
                )

                # 返回桌面
                adb_util.back_home(adb_path, device_id)
                await asyncio.sleep(2)

                # 启动应用
                try:
                    adb_util.launch_app(adb_path, device_id, package)
                    await asyncio.sleep(5)
                except Exception as exc:
                    print(f"[{device_id}] 启动应用 {app_name} 失败: {exc}")
                    continue

                # 执行进入应用后的动作序列（如点击进入特定界面）
                enter_actions = app_info.get("enter_actions", [])
                if enter_actions:
                    print(f"[{device_id}] 执行应用 {app_name} 的进入动作序列（{len(enter_actions)} 步）")
                    # 先截图用于点击文字的 OCR
                    screenshot_path = self._build_screenshot_path(settings["screenshot_dir"], device_id, app_name)
                    if adb_util.take_screenshot(adb_path, device_id, screenshot_path):
                        await action_executor.execute_actions(device_id, screenshot_path, enter_actions)
                        self._cleanup_screenshot(screenshot_path)
                    else:
                        print(f"[{device_id}] 截图失败，跳过进入动作")
                    await asyncio.sleep(3)
                else:
                    # 即使没有进入动作，也等待一段时间让应用加载
                    await asyncio.sleep(3)

                # 监控指定时长
                start_time = time.time()
                while time.time() - start_time < run_duration_seconds:
                    await self.device_processor.process_device(device_id)
                    await asyncio.sleep(poll_interval)

                print(f"[{device_id}] --- 应用 {app_name} 监控结束 ---")

    def _build_screenshot_path(self, screenshot_dir: str, device_serial: str, tag: str = "") -> str:
        """生成截图文件路径。"""
        safe_serial = device_serial.replace(":", "_")
        if tag:
            filename = f"{safe_serial}_{tag}_{int(time.time())}.png"
        else:
            filename = f"{safe_serial}_{int(time.time())}.png"
        return os.path.join(screenshot_dir, filename)

    def _cleanup_screenshot(self, screenshot_path: str) -> None:
        """删除临时截图文件。"""
        try:
            os.remove(screenshot_path)
        except OSError as exc:
            print(f"删除截图 {screenshot_path} 失败: {exc}")

    async def monitor_device_simple(self, device_id: str) -> None:
        print(f"\n[{device_id}] 启用简单监控模式（无 APP 轮换）")

        while True:
            try:
                settings = self._get_settings()
                adb_path = settings["adb_path"]
                poll_interval = settings["poll_interval_seconds"]
                devices = adb_util.get_devices(adb_path)
                if device_id not in devices:
                    print(f"[{device_id}] 设备已断开连接，停止监控")
                    break

                await self.device_processor.process_device(device_id)
                await asyncio.sleep(poll_interval)
            except Exception as exc:
                print(f"[{device_id}] 监控过程中出错: {exc}")
                await asyncio.sleep(self._get_settings().get("poll_interval_seconds", 3))

    async def _wifi_reconnect_loop(self) -> None:
        """后台任务：定期重连 WiFi 设备，通过线程池执行，不阻塞事件循环。"""
        loop = asyncio.get_event_loop()
        while True:
            settings = self._get_settings()
            wifi_devices = settings.get("adb_wifi_devices", [])
            if wifi_devices:
                await loop.run_in_executor(
                    None,
                    adb_util.ensure_wifi_devices_connected,
                    settings["adb_path"],
                    wifi_devices,
                )
            await asyncio.sleep(30)

    async def _remote_sync_loop(self, device_tasks: Dict[str, asyncio.Task]) -> None:
        if not self.remote_control_service:
            return

        loop = asyncio.get_event_loop()
        while True:
            settings = self._get_settings()
            remote_settings = settings.get("remote_control", {})
            interval = min(
                remote_settings.get("config_poll_seconds", 10),
                remote_settings.get("status_upload_seconds", 10),
            )
            # 只把仍在运行的设备任务传给远控服务，便于服务端看到当前活跃监控集合。
            active_monitor_devices = [
                device_id for device_id, task in device_tasks.items() if task and not task.done()
            ]
            await loop.run_in_executor(None, self.remote_control_service.run_cycle, active_monitor_devices)
            await asyncio.sleep(interval)

    def _cancel_all_device_tasks(self, device_tasks: Dict[str, asyncio.Task]) -> None:
        for task in device_tasks.values():
            if task and not task.done():
                task.cancel()
        device_tasks.clear()

    async def run(self) -> None:
        device_tasks: Dict[str, asyncio.Task] = {}
        last_check_time = time.time()
        check_interval = 5
        was_paused = False

        print("=" * 50)
        print(" 多设备动态监控开始（支持热插拔设备） ")
        print("=" * 50)

        settings = self._get_settings()
        if settings.get("adb_wifi_devices"):
            asyncio.create_task(self._wifi_reconnect_loop())
        if self.remote_control_service:
            asyncio.create_task(self._remote_sync_loop(device_tasks))

        try:
            while True:
                current_time = time.time()
                if current_time - last_check_time >= check_interval:
                    last_check_time = current_time
                    settings = self._get_settings()
                    adb_path = settings["adb_path"]

                    if self.remote_control_service and self.remote_control_service.get_monitor_state() == "paused":
                        if not was_paused:
                            print("[系统] 远程控制要求暂停监控，正在停止所有设备任务")
                            was_paused = True
                        # paused 状态下不再维持已有监控任务，保证远程暂停能快速生效。
                        self._cancel_all_device_tasks(device_tasks)
                        await asyncio.sleep(check_interval)
                        continue
                    if was_paused:
                        print("[系统] 远程控制恢复为运行状态，重新开始设备监控")
                        was_paused = False

                    try:
                        connected_devices = adb_util.get_devices(adb_path)
                    except Exception as exc:
                        print(f"获取设备列表失败: {exc}")
                        await asyncio.sleep(check_interval)
                        continue

                    print(f"\n[系统] 当前连接的设备: {connected_devices if connected_devices else '无'}")

                    for device_id in connected_devices:
                        if device_id in device_tasks and not device_tasks[device_id].done():
                            continue

                        print(f"[{device_id}] 检测到新设备或任务已结束，启动监控...")
                        # 优先级：1. app_monitor_cycle > 2. app_loop > 3. simple
                        app_cycle_config = self._get_device_app_monitor_cycle_config(device_id)
                        if app_cycle_config:
                            task = asyncio.create_task(
                                self.monitor_device_with_app_cycle(device_id, app_cycle_config)
                            )
                        else:
                            app_loop_item = self._get_device_app_loop_config(device_id)
                            if app_loop_item:
                                device_config = app_loop_item.get("device", {})
                                task = asyncio.create_task(
                                    self.monitor_device_with_app_loop(device_id, device_config)
                                )
                            else:
                                task = asyncio.create_task(self.monitor_device_simple(device_id))
                        device_tasks[device_id] = task

                    disconnected_devices = [device_id for device_id in device_tasks if device_id not in connected_devices]
                    for device_id in disconnected_devices:
                        task = device_tasks[device_id]
                        if task:
                            task.cancel()
                        print(f"[{device_id}] 设备已断开，取消监控任务")
                        del device_tasks[device_id]

                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n\n" + "=" * 50)
            print(" 监控已停止（用户中断） ")
            print("=" * 50)
            self._cancel_all_device_tasks(device_tasks)
