import asyncio
from typing import Any, Dict, List

import adb_util
import util


class ActionExecutor:
    """执行单个或多个 action，支持多种 action 类型（点击坐标、点击文字、滑动等）。"""

    def __init__(self, adb_path: str, keep_scope_temp_images: bool = False):
        self.adb_path = adb_path
        self.keep_scope_temp_images = keep_scope_temp_images

    async def execute_actions(
        self,
        device_serial: str,
        screenshot_path: str,
        actions: List[Dict[str, Any]],
        interval_seconds: float = 2.0,
    ) -> bool:
        """
        按顺序执行多个 action。

        :param device_serial: 设备序列号
        :param screenshot_path: 当前截图路径（用于点击文字操作）
        :param actions: action 列表
        :param interval_seconds: 每个 action 之间的间隔秒数
        :return: 是否全部执行成功
        """
        if not actions:
            return True

        for index, action in enumerate(actions, 1):
            action_type = action.get("type")
            if not action_type:
                continue

            print(f"[{device_serial}] 执行进入动作 ({index}/{len(actions)}): {action_type}")

            try:
                if action_type == "click_coords":
                    x = action.get("x")
                    y = action.get("y")
                    if x is None or y is None:
                        print(f"[{device_serial}] click_coords 缺少坐标信息，跳过")
                        continue
                    adb_util.click(self.adb_path, device_serial, x, y)

                elif action_type == "click_text":
                    target_text = action.get("target")
                    scope = action.get("scope")
                    if not target_text:
                        print(f"[{device_serial}] click_text 缺少目标文字，跳过")
                        continue
                    print(f"[{device_serial}] 查找并点击文字: '{target_text}'" + (f" (范围: {scope})" if scope else ""))
                    target_coords = await self._find_text(screenshot_path, target_text, scope)
                    if not target_coords:
                        print(f"[{device_serial}] 未能找到文字: '{target_text}'，跳过")
                        continue
                    x, y, w, h = target_coords
                    adb_util.click(self.adb_path, device_serial, x + w - 10, y + h // 2)

                elif action_type == "swipe":
                    start_x = action.get("start_x")
                    start_y = action.get("start_y")
                    end_x = action.get("end_x")
                    end_y = action.get("end_y")
                    duration_ms = action.get("duration_ms", 300)
                    if None in (start_x, start_y, end_x, end_y):
                        print(f"[{device_serial}] swipe 缺少坐标信息，跳过")
                        continue
                    adb_util.swipe(self.adb_path, device_serial, start_x, start_y, end_x, end_y, duration_ms)

                elif action_type == "back":
                    adb_util.back(self.adb_path, device_serial)

                elif action_type == "home":
                    adb_util.back_home(self.adb_path, device_serial)

                elif action_type == "sleep":
                    # 允许在 action 序列中插入等待
                    sleep_seconds = action.get("seconds", 1)
                    print(f"[{device_serial}] 等待 {sleep_seconds} 秒")
                    await asyncio.sleep(sleep_seconds)
                    continue  # 跳过后面的 interval_seconds 等待

                else:
                    print(f"[{device_serial}] 未知的 action 类型: {action_type}")
                    continue

                # action 执行后等待一段时间（便于界面加载）
                if interval_seconds > 0 and index < len(actions):
                    await asyncio.sleep(interval_seconds)

            except Exception as exc:
                print(f"[{device_serial}] 执行 action ({action_type}) 失败: {exc}")
                return False

        return True

    async def _find_text(self, screenshot_path: str, text: str, scope: str = None):
        """查找文字在截图中的位置（支持 scope 限制范围）。"""
        if scope:
            return await util.find_text_in_image_with_scope(
                screenshot_path,
                text,
                scope,
                keep_temp=self.keep_scope_temp_images,
            )
        return await util.find_text_in_image(screenshot_path, text)
