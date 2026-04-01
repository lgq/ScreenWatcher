from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass(slots=True)
class ScenarioConfig:
    name: str
    screen_text: list[str]
    action: dict[str, Any]
    scope: str = "full"
    stop_task: bool = False


@dataclass(slots=True)
class EntryConfig:
    start_from_home: bool = True
    launch: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ExecuteConfig:
    poll_interval_seconds: int = 5
    required_activities: list[str] = field(default_factory=list)
    screenshot_dir: str = "task_engine_v2/screenshots"
    scenarios: list[ScenarioConfig] = field(default_factory=list)
    activity_random_swipe_up: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExitConfig:
    max_duration_seconds: int = 1800
    stop_on_action_types: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskConfig:
    name: str
    entry: EntryConfig
    execute: ExecuteConfig
    exit: ExitConfig


@dataclass(slots=True)
class DeviceAssignment:
    device_id: str
    task_file: str
    need_loop: bool = False


@dataclass(slots=True)
class WifiDeviceConfig:
    serial: str          # host:port，例如 192.168.1.100:5555
    auto_connect: bool = True


def _parse_scenarios(raw_scenarios: list[dict[str, Any]]) -> list[ScenarioConfig]:
    scenarios: list[ScenarioConfig] = []
    for item in raw_scenarios:
        scenarios.append(
            ScenarioConfig(
                name=str(item.get("name", "unnamed-scenario")),
                scope=str(item.get("scope", "full")),
                screen_text=[str(x) for x in item.get("screen_text", [])],
                action=dict(item.get("action", {})),
                stop_task=bool(item.get("stop_task", False)),
            )
        )
    return scenarios


def load_task_config(path: str | Path) -> TaskConfig:
    file_path = Path(path)
    data = json.loads(file_path.read_text(encoding="utf-8"))

    entry_data = data.get("entry", {})
    execute_data = data.get("execute", {})
    exit_data = data.get("exit", {})

    entry = EntryConfig(
        start_from_home=bool(entry_data.get("start_from_home", True)),
        launch=entry_data.get("launch"),
        steps=[dict(step) for step in entry_data.get("steps", [])],
    )

    execute = ExecuteConfig(
        poll_interval_seconds=max(1, int(execute_data.get("poll_interval_seconds", 5))),
        required_activities=[str(x) for x in execute_data.get("required_activities", [])],
        screenshot_dir=str(execute_data.get("screenshot_dir", "task_engine_v2/screenshots")),
        scenarios=_parse_scenarios(execute_data.get("scenarios", [])),
        activity_random_swipe_up=dict(execute_data.get("activity_random_swipe_up", {})),
    )

    exit_cfg = ExitConfig(
        max_duration_seconds=max(1, int(exit_data.get("max_duration_seconds", 1800))),
        stop_on_action_types=[str(x) for x in exit_data.get("stop_on_action_types", [])],
    )

    return TaskConfig(name=str(data.get("name", file_path.stem)), entry=entry, execute=execute, exit=exit_cfg)


def load_assignments(path: str | Path) -> list[DeviceAssignment]:
    file_path = Path(path)
    data = json.loads(file_path.read_text(encoding="utf-8"))
    raw_assignments = data.get("assignments", [])
    assignments: list[DeviceAssignment] = []
    for item in raw_assignments:
        device_id = str(item.get("device_id", "")).strip()
        task_file = str(item.get("task_file", "")).strip()
        need_loop = bool(item.get("need_loop", False))
        if not task_file:
            continue
        assignments.append(DeviceAssignment(device_id=device_id, task_file=task_file, need_loop=need_loop))
    return assignments


def load_wifi_devices(path: str | Path) -> list[WifiDeviceConfig]:
    file_path = Path(path)
    data = json.loads(file_path.read_text(encoding="utf-8"))
    wifi_devices: list[WifiDeviceConfig] = []
    for item in data.get("wifi_devices", []):
        serial = str(item.get("serial", "")).strip()
        if not serial:
            continue
        auto_connect = bool(item.get("auto_connect", True))
        wifi_devices.append(WifiDeviceConfig(serial=serial, auto_connect=auto_connect))
    return wifi_devices
