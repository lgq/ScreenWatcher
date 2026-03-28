from typing import Any, Dict, List

import adb_util
import util


class ScenarioExecutor:
    def __init__(self, adb_path: str, keep_scope_temp_images: bool = False):
        self.adb_path = adb_path
        self.keep_scope_temp_images = keep_scope_temp_images

    async def execute(self, device_serial: str, screenshot_path: str, scenarios: List[Dict[str, Any]]) -> bool:
        if not scenarios:
            print(f"[{device_serial}] 当前配置中没有可用场景，跳过处理。")
            return False

        for scenario in scenarios:
            if await self._is_match(screenshot_path, scenario):
                await self._execute_action(device_serial, screenshot_path, scenario)
                return True

        print(f"[{device_serial}] 未识别到任何已配置的界面。")
        return False

    async def _find_text(self, screenshot_path: str, text: str, scope: str):
        if scope:
            return await util.find_text_in_image_with_scope(
                screenshot_path,
                text,
                scope,
                keep_temp=self.keep_scope_temp_images,
            )
        return await util.find_text_in_image(screenshot_path, text)

    async def _is_match(self, screenshot_path: str, scenario: Dict[str, Any]) -> bool:
        action = scenario.get("action", {})
        scope = scenario.get("scope") or action.get("scope")

        screen_text_config = scenario["screen_text"]
        if isinstance(screen_text_config, str):
            screen_texts = [screen_text_config]
        else:
            screen_texts = screen_text_config

        for text in screen_texts:
            coords = await self._find_text(screenshot_path, text, scope)
            if not coords:
                return False

        not_include_config = scenario.get("screen_text_not_include")
        if not not_include_config:
            return True

        if isinstance(not_include_config, str):
            not_include_texts = [not_include_config]
        else:
            not_include_texts = not_include_config

        for text in not_include_texts:
            coords = await self._find_text(screenshot_path, text, scope)
            if coords:
                print(f"界面 '{scenario['name']}' 匹配失败: 包含被排除的文字 '{text}'")
                return False

        return True

    async def _execute_action(self, device_serial: str, screenshot_path: str, scenario: Dict[str, Any]) -> None:
        action = scenario.get("action", {})
        scope = scenario.get("scope") or action.get("scope")
        screen_text_config = scenario["screen_text"]
        screen_texts = [screen_text_config] if isinstance(screen_text_config, str) else screen_text_config

        print(
            f"[{device_serial}] 识别到界面: '{scenario['name']}' "
            f"(匹配文字: {screen_texts}" + (f", scope: {scope}" if scope else "") + ")"
        )

        action_type = action.get("type")
        if not action_type:
            return

        if action_type == "click_coords":
            adb_util.click(self.adb_path, device_serial, action["x"], action["y"])
            return

        if action_type == "click_text":
            target_text = action["target"]
            print(f"[{device_serial}] 正在查找并点击文字: '{target_text}'" + (f" (范围: {scope})" if scope else ""))
            target_coords = await self._find_text(screenshot_path, target_text, scope)
            if not target_coords:
                print(f"[{device_serial}] 未在屏幕上找到可点击的文字: '{target_text}'")
                return
            x, y, w, h = target_coords
            adb_util.click(self.adb_path, device_serial, x + w - 10, y + h // 2)
            return

        if action_type == "swipe":
            adb_util.swipe(
                self.adb_path,
                device_serial,
                action["start_x"],
                action["start_y"],
                action["end_x"],
                action["end_y"],
                action["duration_ms"],
            )
            return

        if action_type == "launch_app":
            adb_util.launch_app(self.adb_path, device_serial, action["package"])
