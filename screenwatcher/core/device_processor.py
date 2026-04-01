import os
import time

import adb_util

from .activity_rules import ActivityRuleHandler
from .config_service import ConfigService
from .scenario_executor import ScenarioExecutor


class DeviceProcessor:
    def __init__(self, config_service: ConfigService):
        self.config_service = config_service

    async def process_device(self, device_serial: str) -> None:
        print(f"\n----- 正在处理设备: {device_serial} -----")

        settings = self.config_service.load_settings()
        adb_path = settings["adb_path"]
        current_app = adb_util.get_foreground_app(adb_path, device_serial)
        runtime_config, config_path = self.config_service.load_runtime_config(current_app)
        keep_scope_temp_images = bool(runtime_config["settings"].get("keep_scope_temp_images", False))

        if current_app:
            if config_path != self.config_service.base_config_path:
                print(f"[{device_serial}] 当前前台应用: '{current_app}'，正在加载专属配置: {config_path}")
            else:
                print(f"[{device_serial}] 未找到 '{current_app}' 的专属配置，回退使用默认 config.json")
        else:
            print(f"[{device_serial}] 无法获取前台应用或处于桌面，回退使用默认 config.json")

        current_activity = adb_util.get_current_activity(adb_path, device_serial)
        activity_handler = ActivityRuleHandler(adb_path, runtime_config)
        if await activity_handler.handle(device_serial, current_activity):
            return

        screenshot_path = self._build_screenshot_path(runtime_config["settings"]["screenshot_dir"], device_serial)
        if not adb_util.take_screenshot(adb_path, device_serial, screenshot_path):
            return

        try:
            executor = ScenarioExecutor(adb_path, keep_scope_temp_images=keep_scope_temp_images)
            await executor.execute(device_serial, screenshot_path, runtime_config.get("scenarios", []))
        finally:
            self._cleanup_screenshot(screenshot_path)

    def _build_screenshot_path(self, screenshot_dir: str, device_serial: str) -> str:
        safe_serial = device_serial.replace(":", "_")
        return os.path.join(screenshot_dir, f"{safe_serial}_{int(time.time())}.png")

    def _cleanup_screenshot(self, screenshot_path: str) -> None:
        try:
            os.remove(screenshot_path)
        except OSError as exc:
            print(f"删除截图 {screenshot_path} 失败: {exc}")
