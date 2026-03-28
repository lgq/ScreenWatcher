import asyncio
import time
from typing import Any, Dict, Optional

import adb_util

from screenwatcher.config_service import ConfigService
from screenwatcher.device_processor import DeviceProcessor


class DeviceMonitor:
    def __init__(self, config_service: ConfigService, device_processor: DeviceProcessor):
        self.config_service = config_service
        self.device_processor = device_processor

    def _get_settings(self) -> Dict[str, Any]:
        return self.config_service.load_settings()

    def _get_device_app_loop_config(self, device_id: str) -> Optional[Dict[str, Any]]:
        app_loop_config = self._get_settings().get("app_loop", [])
        for loop_item in app_loop_config:
            device_info = loop_item.get("device", {})
            if device_info.get("id") == device_id:
                return loop_item
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

    async def run(self) -> None:
        device_tasks: Dict[str, asyncio.Task] = {}
        last_check_time = time.time()
        check_interval = 5

        print("=" * 50)
        print(" 多设备动态监控开始（支持热插拔设备） ")
        print("=" * 50)

        settings = self._get_settings()
        if settings.get("adb_wifi_devices"):
            asyncio.create_task(self._wifi_reconnect_loop())

        try:
            while True:
                current_time = time.time()
                if current_time - last_check_time >= check_interval:
                    last_check_time = current_time
                    settings = self._get_settings()
                    adb_path = settings["adb_path"]

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
                        app_loop_item = self._get_device_app_loop_config(device_id)
                        if app_loop_item:
                            device_config = app_loop_item.get("device", {})
                            task = asyncio.create_task(self.monitor_device_with_app_loop(device_id, device_config))
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
            for task in device_tasks.values():
                if task and not task.done():
                    task.cancel()
