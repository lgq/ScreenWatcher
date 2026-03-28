import asyncio
import random
from typing import Any, Dict

import adb_util


def is_activity_match(current_activity: str, targets: Any) -> bool:
    if not current_activity:
        return False

    if isinstance(targets, str):
        target_list = [targets]
    else:
        target_list = targets or []

    for target in target_list:
        if target and target in current_activity:
            return True
    return False


class ActivityRuleHandler:
    def __init__(self, adb_path: str, config: Dict[str, Any]):
        self.adb_path = adb_path
        self.config = config

    async def handle(self, device_serial: str, current_activity: str) -> bool:
        if await self._handle_random_swipe_up(device_serial, current_activity):
            return True
        if self._handle_back(device_serial, current_activity):
            return True
        return False

    async def _handle_random_swipe_up(self, device_serial: str, current_activity: str) -> bool:
        swipe_cfg = self.config.get("activity_random_swipe_up")
        if not isinstance(swipe_cfg, dict):
            return False
        if swipe_cfg.get("enabled", True) is False:
            return False

        activities = swipe_cfg.get("activities", [])
        if not is_activity_match(current_activity, activities):
            return False

        interval_min = max(1, int(swipe_cfg.get("interval_min_seconds", 10)))
        interval_max = max(interval_min, int(swipe_cfg.get("interval_max_seconds", 15)))

        start_x = int(swipe_cfg.get("start_x", 500))
        start_y = int(swipe_cfg.get("start_y", 900))
        end_x = int(swipe_cfg.get("end_x", start_x))
        end_y = int(swipe_cfg.get("end_y", start_y - 240))

        x_variance = max(0, int(swipe_cfg.get("x_variance", 20)))
        start_y_variance = max(0, int(swipe_cfg.get("start_y_variance", 12)))
        end_y_variance = max(0, int(swipe_cfg.get("end_y_variance", 18)))
        duration_min_ms = max(1, int(swipe_cfg.get("duration_min_ms", 80)))
        duration_max_ms = max(duration_min_ms, int(swipe_cfg.get("duration_max_ms", 180)))

        actual_start_x = start_x + random.randint(-x_variance, x_variance)
        actual_start_y = start_y + random.randint(-start_y_variance, start_y_variance)
        actual_end_x = end_x + random.randint(-x_variance, x_variance)
        actual_end_y = end_y + random.randint(-end_y_variance, end_y_variance)
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
        adb_util.swipe(
            self.adb_path,
            device_serial,
            actual_start_x,
            actual_start_y,
            actual_end_x,
            actual_end_y,
            actual_duration_ms,
        )
        return True

    def _handle_back(self, device_serial: str, current_activity: str) -> bool:
        back_activities = self.config.get("back_activities", [])
        if not current_activity or not back_activities:
            return False

        if any(current_activity.endswith(act) or act in current_activity for act in back_activities):
            print(f"[{device_serial}] 当前 Activity '{current_activity}' 命中 back_activities，执行返回操作。")
            adb_util.back(self.adb_path, device_serial)
            return True
        return False
