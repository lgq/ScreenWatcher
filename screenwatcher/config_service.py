import json
import os
from typing import Any, Dict, List, Tuple


class ConfigError(Exception):
    pass


class ConfigService:
    def __init__(self, base_config_path: str = "config.json", settings_path: str = "settings_config.json"):
        self.base_config_path = base_config_path
        self.settings_path = settings_path

    def _read_json(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError as exc:
            raise ConfigError(f"配置文件不存在: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"配置文件解析失败: {path}: {exc}") from exc

    def _normalize_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        settings["adb_path"] = str(settings.get("adb_path", "adb"))
        settings["keep_scope_temp_images"] = bool(settings.get("keep_scope_temp_images", False))

        poll_interval = settings.get("poll_interval_seconds", 3)
        run_duration = settings.get("run_duration_minutes", 30)
        settings["poll_interval_seconds"] = max(1, self._to_int(poll_interval, 3))
        settings["run_duration_minutes"] = max(1, self._to_int(run_duration, 30))

        screenshot_dir = settings.get("screenshot_dir", "temp_screenshots")
        if not os.path.exists(screenshot_dir):
            os.makedirs(screenshot_dir)
        settings["screenshot_dir"] = screenshot_dir

        settings["app_loop"] = self._normalize_app_loop(settings.get("app_loop", []))
        return settings

    def _normalize_app_loop(self, app_loop: Any) -> List[Dict[str, Any]]:
        if not isinstance(app_loop, list):
            return []

        normalized_loop: List[Dict[str, Any]] = []
        for item in app_loop:
            if not isinstance(item, dict):
                continue

            device = item.get("device") if isinstance(item.get("device"), dict) else {}
            device_id = str(device.get("id", "")).strip()
            if not device_id:
                continue

            name = str(device.get("name", device_id)).strip() or device_id
            test_icon_position_list = device.get("test_icon_position_list", [])
            if not isinstance(test_icon_position_list, list):
                test_icon_position_list = []

            normalized_positions = []
            for position in test_icon_position_list:
                if not isinstance(position, dict):
                    continue
                if "x" not in position or "y" not in position:
                    continue
                try:
                    x = int(position["x"])
                    y = int(position["y"])
                except (TypeError, ValueError):
                    continue
                normalized_positions.append({"x": x, "y": y})

            normalized_loop.append(
                {
                    "device": {
                        "id": device_id,
                        "name": name,
                        "test_icon_position_list": normalized_positions,
                    }
                }
            )

        return normalized_loop

    def _normalize_activity_random_swipe_up(self, value: Any) -> Dict[str, Any]:
        if value is False:
            return {"enabled": False}

        cfg = value if isinstance(value, dict) else {}
        enabled = bool(cfg.get("enabled", True))

        activities = cfg.get("activities", [])
        if isinstance(activities, str):
            activities = [activities]
        elif not isinstance(activities, list):
            activities = []
        activities = [str(item).strip() for item in activities if str(item).strip()]

        interval_min = max(1, self._to_int(cfg.get("interval_min_seconds", 10), 10))
        interval_max = max(interval_min, self._to_int(cfg.get("interval_max_seconds", 15), 15))

        # 兼容旧配置 duration_ms：若未显式配置 min/max，则按固定时长处理。
        duration_ms_legacy = max(1, self._to_int(cfg.get("duration_ms", 120), 120))
        duration_min_ms = max(1, self._to_int(cfg.get("duration_min_ms", duration_ms_legacy), duration_ms_legacy))
        duration_max_ms = max(
            duration_min_ms,
            self._to_int(cfg.get("duration_max_ms", duration_ms_legacy), duration_ms_legacy),
        )

        return {
            "enabled": enabled,
            "activities": activities,
            "interval_min_seconds": interval_min,
            "interval_max_seconds": interval_max,
            "start_x": self._to_int(cfg.get("start_x", 500), 500),
            "start_y": self._to_int(cfg.get("start_y", 900), 900),
            "end_x": self._to_int(cfg.get("end_x", 500), 500),
            "end_y": self._to_int(cfg.get("end_y", 660), 660),
            "x_variance": max(0, self._to_int(cfg.get("x_variance", 20), 20)),
            "start_y_variance": max(0, self._to_int(cfg.get("start_y_variance", 12), 12)),
            "end_y_variance": max(0, self._to_int(cfg.get("end_y_variance", 18), 18)),
            "duration_min_ms": duration_min_ms,
            "duration_max_ms": duration_max_ms,
            "duration_ms": duration_ms_legacy,
        }

    def _normalize_action(self, action: Any) -> Dict[str, Any]:
        if not isinstance(action, dict):
            return {}

        normalized = dict(action)
        action_type = normalized.get("type")

        if action_type == "click_coords":
            normalized["x"] = self._to_int(normalized.get("x", 0), 0)
            normalized["y"] = self._to_int(normalized.get("y", 0), 0)
        elif action_type == "click_text":
            normalized["target"] = str(normalized.get("target", ""))
        elif action_type == "swipe":
            normalized["start_x"] = self._to_int(normalized.get("start_x", 0), 0)
            normalized["start_y"] = self._to_int(normalized.get("start_y", 0), 0)
            normalized["end_x"] = self._to_int(normalized.get("end_x", 0), 0)
            normalized["end_y"] = self._to_int(normalized.get("end_y", 0), 0)
            normalized["duration_ms"] = max(1, self._to_int(normalized.get("duration_ms", 200), 200))
        elif action_type == "launch_app":
            normalized["package"] = str(normalized.get("package", ""))

        return normalized

    def _normalize_scenarios(self, scenarios: Any) -> List[Dict[str, Any]]:
        if not isinstance(scenarios, list):
            return []

        normalized_scenarios: List[Dict[str, Any]] = []
        for index, scenario in enumerate(scenarios):
            if not isinstance(scenario, dict):
                continue

            screen_text = scenario.get("screen_text")
            if isinstance(screen_text, str):
                screen_text_list = [screen_text]
            elif isinstance(screen_text, list):
                screen_text_list = [str(item) for item in screen_text if str(item)]
            else:
                screen_text_list = []

            if not screen_text_list:
                continue

            not_include = scenario.get("screen_text_not_include")
            if isinstance(not_include, str):
                not_include_list = [not_include]
            elif isinstance(not_include, list):
                not_include_list = [str(item) for item in not_include if str(item)]
            else:
                not_include_list = []

            normalized = {
                "name": str(scenario.get("name", f"Scenario-{index + 1}")),
                "screen_text": screen_text_list,
                "action": self._normalize_action(scenario.get("action", {})),
            }

            scope = scenario.get("scope")
            if isinstance(scope, str) and scope:
                normalized["scope"] = scope

            if not_include_list:
                normalized["screen_text_not_include"] = not_include_list

            normalized_scenarios.append(normalized)

        return normalized_scenarios

    def _normalize_runtime_config(self, config: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(config)
        normalized["settings"] = settings
        normalized["activity_random_swipe_up"] = self._normalize_activity_random_swipe_up(
            normalized.get("activity_random_swipe_up", {})
        )
        normalized["scenarios"] = self._normalize_scenarios(normalized.get("scenarios", []))
        return normalized

    def _to_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def load_settings(self) -> Dict[str, Any]:
        settings = self._read_json(self.settings_path)
        return self._normalize_settings(settings)

    def resolve_runtime_config_path(self, package_name: str = "") -> str:
        if package_name:
            app_config_path = f"{package_name}_config.json"
            if os.path.exists(app_config_path):
                return app_config_path
        return self.base_config_path

    def load_runtime_config(self, package_name: str = "") -> Tuple[Dict[str, Any], str]:
        config_path = self.resolve_runtime_config_path(package_name)
        config = self._read_json(config_path)
        settings = self.load_settings()
        return self._normalize_runtime_config(config, settings), config_path
