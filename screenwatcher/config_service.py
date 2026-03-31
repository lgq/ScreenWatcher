import json
import os
import socket
from typing import Any, Dict, List, Tuple

from screenwatcher import runtime_paths


class ConfigError(Exception):
    pass


class ConfigService:
    def __init__(self, base_config_path: str = "config.json", settings_path: str = "settings_config.json"):
        # 启动时先确保运行目录和默认配置已经准备好，后续所有读写都基于该目录展开。
        data_root = runtime_paths.sync_default_runtime_files()
        self.data_root = data_root
        self.base_config_path = self._resolve_runtime_path(base_config_path)
        self.settings_path = self._resolve_runtime_path(settings_path)

    def _resolve_runtime_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.join(self.data_root, path)

    def _read_json(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError as exc:
            raise ConfigError(f"配置文件不存在: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"配置文件解析失败: {path}: {exc}") from exc

    def _normalize_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        adb_path = str(settings.get("adb_path", "adb")).strip() or "adb"
        bundled_adb_path = runtime_paths.get_bundled_adb_path()
        # 当用户没有显式指定 adb 路径时，优先使用安装包内自带 adb，减少环境依赖。
        if adb_path == "adb" and bundled_adb_path:
            adb_path = bundled_adb_path
        settings["adb_path"] = adb_path
        settings["keep_scope_temp_images"] = bool(settings.get("keep_scope_temp_images", False))

        poll_interval = settings.get("poll_interval_seconds", 3)
        run_duration = settings.get("run_duration_minutes", 30)
        settings["poll_interval_seconds"] = max(1, self._to_int(poll_interval, 3))
        settings["run_duration_minutes"] = max(1, self._to_int(run_duration, 30))

        screenshot_dir = str(settings.get("screenshot_dir", "temp_screenshots")).strip() or "temp_screenshots"
        if not os.path.isabs(screenshot_dir):
            screenshot_dir = os.path.join(self.data_root, screenshot_dir)
        if not os.path.exists(screenshot_dir):
            os.makedirs(screenshot_dir)
        settings["screenshot_dir"] = screenshot_dir

        settings["adb_wifi_devices"] = self._normalize_adb_wifi_devices(settings.get("adb_wifi_devices", []))
        settings["app_loop"] = self._normalize_app_loop(settings.get("app_loop", []))
        settings["app_monitor_cycle"] = self._normalize_app_monitor_cycle(settings.get("app_monitor_cycle", []))
        settings["remote_control"] = self._normalize_remote_control(settings.get("remote_control", {}))
        return settings

    def _normalize_remote_control(self, value: Any) -> Dict[str, Any]:
        config = value if isinstance(value, dict) else {}
        # 默认用主机名生成 device_id/device_name，避免首启时因为未配置而无法注册到服务端。
        default_device_id = socket.gethostname().strip() or "screenwatcher-pc"
        device_id = str(config.get("device_id", default_device_id)).strip() or default_device_id
        device_name = str(config.get("device_name", device_id)).strip() or device_id

        return {
            "enabled": bool(config.get("enabled", False)),
            "supabase_url": str(config.get("supabase_url", "")).strip().rstrip("/"),
            "supabase_key": str(config.get("supabase_key", "")).strip(),
            "access_token": str(config.get("access_token", "")).strip(),
            "project_id": str(config.get("project_id", "screenwatcher-prod")).strip() or "screenwatcher-prod",
            "device_id": device_id,
            "device_name": device_name,
            "config_poll_seconds": max(5, self._to_int(config.get("config_poll_seconds", 10), 10)),
            "status_upload_seconds": max(5, self._to_int(config.get("status_upload_seconds", 10), 10)),
            # 表名也纳入配置，便于后续做测试环境/正式环境隔离。
            "config_table": str(config.get("config_table", "watch_config_versions")).strip() or "watch_config_versions",
            "device_table": str(config.get("device_table", "watch_devices")).strip() or "watch_devices",
            "status_table": str(config.get("status_table", "watch_device_status_logs")).strip() or "watch_device_status_logs",
        }

    def _normalize_adb_wifi_devices(self, adb_wifi_devices: Any) -> List[Dict[str, Any]]:
        if not isinstance(adb_wifi_devices, list):
            return []

        normalized_devices: List[Dict[str, Any]] = []
        for item in adb_wifi_devices:
            serial = ""
            auto_connect = True

            if isinstance(item, str):
                serial = item.strip()
            elif isinstance(item, dict):
                host = str(item.get("host", "")).strip()
                port = self._to_int(item.get("port", 5555), 5555)
                serial = str(item.get("serial", "")).strip() or (f"{host}:{port}" if host else "")
                auto_connect = bool(item.get("auto_connect", True))
            else:
                continue

            if not serial or ":" not in serial:
                continue

            normalized_devices.append(
                {
                    "serial": serial,
                    "auto_connect": auto_connect,
                }
            )

        return normalized_devices

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

    def _normalize_app_monitor_cycle(self, app_monitor_cycle: Any) -> List[Dict[str, Any]]:
        if not isinstance(app_monitor_cycle, list):
            return []

        normalized_cycles: List[Dict[str, Any]] = []
        for item in app_monitor_cycle:
            if not isinstance(item, dict):
                continue

            device_id = str(item.get("device_id", "")).strip()
            if not device_id:
                continue

            apps = item.get("apps", [])
            if not isinstance(apps, list):
                apps = []

            normalized_apps = []
            for app in apps:
                if not isinstance(app, dict):
                    continue
                package = str(app.get("package", "")).strip()
                if not package:
                    continue
                name = str(app.get("name", package)).strip() or package
                # 每个应用可独立配置监控时长，若未配置则使用设备级别的默认值
                app_duration = app.get("duration_minutes")
                if app_duration is not None:
                    app_duration = max(1, self._to_int(app_duration, 30))
                # 进入应用后的动作序列（可能多步）
                enter_actions = app.get("enter_actions")
                if not isinstance(enter_actions, list):
                    enter_actions = []
                # 规范化每个 action，保持与 scenario executor 一致的格式
                normalized_actions = []
                for action in enter_actions:
                    if isinstance(action, dict) and action.get("type"):
                        normalized_actions.append(action)
                normalized_apps.append({
                    "package": package,
                    "name": name,
                    "duration_minutes": app_duration,
                    "enter_actions": normalized_actions,
                })

            if not normalized_apps:
                continue

            # 设备级别的默认监控时长（若应用未指定）
            default_duration_minutes = max(1, self._to_int(item.get("duration_minutes", 30), 30))

            normalized_cycles.append(
                {
                    "device_id": device_id,
                    "apps": normalized_apps,
                    "default_duration_minutes": default_duration_minutes,
                }
            )

        return normalized_cycles

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
            app_config_path = self._resolve_runtime_path(f"{package_name}_config.json")
            if os.path.exists(app_config_path):
                return app_config_path
        return self.base_config_path

    def load_runtime_config(self, package_name: str = "") -> Tuple[Dict[str, Any], str]:
        config_path = self.resolve_runtime_config_path(package_name)
        config = self._read_json(config_path)
        settings = self.load_settings()
        return self._normalize_runtime_config(config, settings), config_path
